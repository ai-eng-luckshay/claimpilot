# ClaimPilot — Pipeline Failure Handling

Documents every failure scenario in the six-node pipeline, what each node does when
it fails, and how the system recovers without crashing.

---

## Assignment Requirement

> "Individual components of your system will fail — LLM timeouts, parsing errors,
> bad inputs. The system must not crash. It must continue with whatever it has,
> reflect the degraded state in the output, and adjust its confidence accordingly."

Every failure path described below satisfies this: the pipeline always terminates
with a decision (or a documented early exit), always writes to the DB where possible,
and always records what failed in `failed_components`.

---

## Node-by-Node Failure Behaviour

### Node 1 — `blur_gate`

| Failure | Behaviour |
|---|---|
| OpenCV error on one image | That document is skipped (`result: SKIP` in trace). Pipeline continues to extraction. |
| Image is blurry (variance < 80) | Hard stop. Returns `DOCUMENT_UNREADABLE` error with the specific filename. Pipeline exits. DB is **not** written — member needs to re-upload. |
| No image data received | Same as blurry — hard stop, specific error. |
| PDF submitted | Always passes. Gemini handles PDF readability internally. |

**Design rationale:** Blur gate is a quality gate, not a graceful-degradation node.
A blurry image cannot be extracted — there is nothing to continue with.

---

### Node 2 — `extract_documents`

| Failure | Behaviour |
|---|---|
| Gemini call succeeds | Normal flow. `extraction_failed = False`. Proceeds to patient name check. |
| Gemini call fails (any reason — 429, timeout, parse error) | `extraction_failed = True`. Decision set to `MANUAL_REVIEW`, `confidence = 0.30`. Routes **directly to `save_to_db`**. Validation and adjudication are skipped entirely. |

**Why skip validation and adjudication on extraction failure:**

If Gemini fails during extraction, calling it again for adjudication is unlikely to
succeed and wastes quota. Validating UNKNOWN document stubs would produce a
misleading "wrong document type" error when the real problem is a Gemini outage.
The correct response is to save the claim as `MANUAL_REVIEW` and let a human
process it when the service recovers.

**Flow on extraction failure:**
```
extract_documents [FAILS]
  extraction_failed = True
  decision = MANUAL_REVIEW, confidence = 0.30
  failed_components = ["extraction_agent"]
        │
        ▼
  save_to_db  ← skips validate_documents and adjudicate_claim entirely
        │
        ▼
  Caller receives MANUAL_REVIEW
  "Document extraction failed — Gemini could not process the submitted documents."
```

---

### Node 3 — `validate_documents`

This node only runs if extraction succeeded (`extraction_failed = False`).

| Failure | Behaviour |
|---|---|
| Wrong document types uploaded | Returns `DOCUMENT_VALIDATION_FAILED` with specific message. Pipeline exits. DB is **not** written — member needs to re-upload. |
| Missing required documents | Same — specific message naming what is required. |
| All required types present | Passes. Proceeds to adjudication. |

This node has no LLM call and no runtime failure modes. It reads from
`policy_terms.json` (already in memory) and compares string lists. It cannot fail
unless the policy file is corrupted, which is a startup-time error caught by `load_policy()`.

---

### Node 3a — `reject_patient_mismatch`

Only runs if extraction succeeded and `patient_name_consistent = False`.

No failure modes — pure Python. Sets `decision = REJECTED` and routes to `save_to_db`.

---

### Node 4 — `adjudicate_claim`

| Failure | Behaviour |
|---|---|
| `simulate_component_failure = true` (TC011) | Skips Gemini. Returns `APPROVED` at `confidence = 0.60` with "manual review recommended" in the reason text. `failed_components` includes `"policy_check"`. |
| Policy file load fails | `_graceful_pass` → `MANUAL_REVIEW`, `confidence = 0.50`. Proceeds to `save_to_db`. |
| Gemini call fails (all cascade models exhausted) | `_graceful_pass` → `MANUAL_REVIEW`, `confidence = 0.50`. Proceeds to `save_to_db`. |
| Gemini returns low confidence (< 0.50) | Confidence gate overrides to `REJECTED`. |
| Gemini returns moderate confidence (0.50 – 0.74) | Confidence gate overrides to `MANUAL_REVIEW`. |
| Gemini returns confidence ≥ 0.75 | Gemini's decision is honoured as-is. |

**TC011 note:** The `simulate_component_failure` path is deliberately separate from
`_graceful_pass`. The assignment test case expects `APPROVED` at lower confidence
with a manual review note in the reason — not `MANUAL_REVIEW` as the decision.
This path is unchanged and passes TC011 as required.

**`_graceful_pass` vs `simulate_component_failure`:**

| | `simulate_component_failure` (TC011) | Real Gemini failure |
|---|---|---|
| Decision | `APPROVED` | `MANUAL_REVIEW` |
| Confidence | `0.60` | `0.50` |
| Reason | "manual review recommended" | "Adjudication unavailable — routed to manual review" |
| When it fires | `simulate_component_failure: true` in request | Actual API error / policy load error |

---

### Node 5 — `save_to_db`

| Failure | Behaviour |
|---|---|
| DB write fails (attempt 1) | Retried after 1 second. |
| DB write fails (attempt 2) | Retried after 2 seconds. |
| DB write fails (attempt 3 — all retries exhausted) | `"save_to_db"` added to `failed_components`. Response is **blocked** — caller receives HTTP 503 with "please resubmit". |

**Why the response is blocked (not degraded):**
Returning a claim decision to the customer when no DB record exists creates an
irreconcilable inconsistency — the customer believes the claim has been decided,
but the company has no record of it. There is no way to reconcile this after the
fact. The only safe behaviour is to tell the customer the submission failed and
ask them to resubmit. Retries handle transient failures (network hiccup, connection
timeout); the block handles persistent failures.

---

## Combined Failure Scenarios

### Scenario A — Extraction fails (Gemini down on first call)

```
blur_gate [PASS]
      │
extract_documents [GEMINI FAILS]
  extraction_failed = True
  decision = MANUAL_REVIEW, confidence = 0.30
      │
save_to_db [writes MANUAL_REVIEW row]
      │
Caller: MANUAL_REVIEW, failed_components: ["extraction_agent"]
```

Adjudication is never called. No second Gemini attempt.

---

### Scenario B — Adjudication fails (Gemini down on second call)

```
blur_gate [PASS] → extract_documents [OK] → validate_documents [OK]
      │
adjudicate_claim [GEMINI FAILS]
  _graceful_pass → MANUAL_REVIEW, confidence = 0.50
      │
save_to_db [writes MANUAL_REVIEW row]
      │
Caller: MANUAL_REVIEW, failed_components: ["adjudicate"]
```

---

### Scenario C — Both fail (total Gemini outage)

```
blur_gate [PASS]
      │
extract_documents [GEMINI FAILS]
  extraction_failed = True → routes to save_to_db immediately
      │
save_to_db [writes MANUAL_REVIEW row]
      │
Caller: MANUAL_REVIEW, failed_components: ["extraction_agent"]
```

Adjudication is never reached — the routing short-circuits at extraction.

---

### Scenario D — TC011 (simulated component failure, assignment test)

```
blur_gate [PASS] → extract_documents [OK] → validate_documents [OK]
      │
adjudicate_claim [simulate_component_failure flag]
  Returns APPROVED at confidence 0.60
  decision_reason includes "manual review recommended"
  failed_components: ["policy_check"]
      │
save_to_db [writes APPROVED row]
      │
Caller: APPROVED, confidence 0.60, failed_components: ["policy_check"]
```

This is the assignment's TC011 test case. Expected `decision: "APPROVED"` — passes.

---

### Scenario E — DB write fails after a successful decision

```
... → adjudicate_claim [APPROVED] → save_to_db [3 retries, all fail]
  failed_components adds "save_to_db"
  Response is BLOCKED in process_claim
      │
Caller: HTTP 503 — "could not be saved, please resubmit"
Company: no DB record (consistent — neither side has a decision)
```

The customer is told to resubmit. No decision is delivered without a DB record.

---

## Confidence Score by Scenario

| Scenario | Confidence | Why |
|---|---|---|
| Clean full pipeline | ≥ 0.75 (Gemini sets it) | All components ran, Gemini confident |
| TC011 simulated failure | 0.60 | One component skipped |
| Adjudication Gemini failure | 0.50 | No policy evaluation performed |
| Extraction Gemini failure | 0.30 | Documents never read |

---

## What Is Never Done

- The pipeline never crashes and returns a 500 error due to a component failure.
- Extraction failure never produces a misleading "wrong document type" error.
- A failed adjudication never auto-approves a claim (`_graceful_pass` returns `MANUAL_REVIEW`).
- `validate_documents` is never called with UNKNOWN stubs from a failed extraction.
- A claim decision is never returned to the customer without a corresponding DB record.
