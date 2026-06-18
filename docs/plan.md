# ClaimPilot — Project Plan

> Living alignment document. Scaffold complete — active development in progress.

---

## 1. What We Are Building

An automated health insurance claims processing system for Plum. When an employee submits a claim (member details + medical documents), ClaimPilot reviews the documents against the member's policy and produces a decision: **APPROVED**, **PARTIAL**, **REJECTED**, or **MANUAL_REVIEW** — with a full explanation and confidence score.

This is a real problem Plum operates today, done manually. The assignment is to automate it.

---

## 2. What the Assignment Requires (Non-Negotiables)

| # | Requirement | Notes |
|---|-------------|-------|
| 1 | Accept a claim submission (member details + docs) | Single batch — all docs submitted at once |
| 2 | Catch wrong/unreadable documents early, with specific error messages | Stop before any processing; message must name the exact problem |
| 3 | Extract structured info from documents (OCR) | Handwritten, stamped, blurry — must handle all |
| 4 | Make a claim decision with reason + approved amount + confidence score | APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW |
| 5 | Full trace — every check visible, why every decision was made | 20% of grade |
| 6 | Graceful failure — components can fail without crashing the system | TC011 specifically tests this |

**Every significant component must have tests.** (Stated explicitly — no tests = incomplete.)

---

## 3. What We Are NOT Building (Scope Boundary)

- A conversational document collection agent (the system receives all docs at once)
- Multi-turn intake sessions or chat history
- Pre-authorization request flows (we detect missing pre-auth and reject, we don't initiate it)
- A dedicated OCR library (we use Gemini 2.5 Flash vision for extraction; OpenCV only for a local blur gate)

---

## 4. Tech Stack Decisions

### Core Pipeline
| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python 3.11+ | Standard for AI/ML work; assignment expects it |
| Agent Orchestration | **LangGraph** | True multi-agent graph with state; bonus points for multi-agentic architecture; built-in tracing |
| LLM Integration | **LangChain `ChatGoogleGenerativeAI`** + Gemini (Google AI Studio) | Free tier (250 req/day); vision-native; structured output via `with_structured_output(schema, method="json_schema")`; accepts images and PDFs directly |
| Extraction model | `gemini-3.1-flash-lite` (primary) | Lightest and fastest; falls back through `gemini-2.5-flash-lite` → `gemini-2.0-flash-lite` → `gemini-3.5-flash` → `gemini-3.0-flash` → `gemini-2.5-flash` → `gemini-2.0-flash` on 429 |
| Adjudication model | `gemini-3.1-flash-lite` (primary) | Same cascade as extraction; both use the same model list so a rate-limited model is skipped globally across both calls |
| Readability gate | **OpenCV** (`cv2.Laplacian` blur variance) | Local, free, no API call — detects unreadable images before sending to Gemini (TC002 gate) |
| Observability | **LangSmith** | Free tier; plug-and-play with LangGraph; gives per-step trace automatically |
| API | **FastAPI** | Async, typed, auto-generates OpenAPI docs |
| Database | **PostgreSQL** | Needed for claims history (TC009 fraud check) + decision review UI |
| ORM | **SQLAlchemy + Alembic** | Migrations, typed models |

### Frontend
| Layer | Choice | Why |
|-------|--------|-----|
| UI | **Streamlit** | Python-native, no context switch from backend; fast to build; sufficient for demo video |

### Infrastructure
| Layer | Choice | Why |
|-------|--------|-----|
| Hosting | **Render.com** | Free tier: 2 web services + PostgreSQL; CI/CD via git push to main |
| Config | **render.yaml** | Defines both services + DB in one file; Render reads it on repo connect for one-click infra creation |
| Keep-alive | **cron-job.org** | Free external pings every 5 min to prevent cold starts; also doubles as uptime alerting |
| Docker | **Not needed** | Render's native Python buildpack handles the full stack; no system binaries required |

### What We Rejected and Why
- **LangChain (standalone)** — LangGraph is the multi-agent evolution; better state management
- **Next.js / React** — More polished but adds a full JS frontend to a 5-day Python assignment; Streamlit is sufficient for the demo and keeps the stack homogeneous
- **Redis** — No clear need; policy JSON loads at startup; no async queuing required
- **EasyOCR** — Originally considered; replaced by Gemini 2.5 Flash which handles vision natively in one call, is free on AI Studio, and accepts PDFs directly — no need for a separate OCR library
- **Tesseract** — Poor on handwriting; requires system binary; superseded by Gemini vision
- **Claude / Anthropic API** — No free tier; for an assignment Gemini AI Studio free tier is the right call
- **AWS Textract / Azure Vision** — Paid; require cloud accounts; unnecessary complexity
- **pdf2image + poppler** — Not needed; Gemini 2.5 Flash accepts PDFs natively via base64 or Files API
- **Surya OCR / PaddleOCR** — Need GPU; Render free tier is CPU-only

---

## 5. Project Structure

```
Plum - ClaimPilot/
├── backend/                        # FastAPI service
│   ├── requirements.in             # unpinned deps (edit this)
│   ├── requirements.txt            # pinned deps (pip-compile output)
│   └── src/
│       ├── main.py                 # FastAPI app, health check, CORS
│       ├── agents/
│       │   ├── blur_gate.py            # blur_gate node (OpenCV)
│       │   ├── extraction.py           # extract_documents node (Gemini call 1)
│       │   ├── patient_name_check.py   # reject_patient_mismatch node
│       │   ├── validate_documents.py   # validate_documents node (pure Python)
│       │   ├── adjudicate.py           # adjudicate_claim node (Gemini call 2)
│       │   ├── save_to_db.py           # save_to_db node (retry + DLQ stub)
│       │   └── prompts/
│       │       ├── extraction.py       # extraction LLM prompt
│       │       └── adjudication.py     # adjudication LLM prompt
│       ├── pipeline/
│       │   ├── graph.py            # LangGraph wiring + conditional edges
│       │   └── state.py            # ClaimState TypedDict
│       ├── schemas/                # Pydantic request/response models
│       ├── models/                 # SQLAlchemy DB models
│       └── services/
│           ├── llm.py              # LLMService, cascade fallback, 24h reset
│           ├── policy.py           # policy loader + context builder
│           ├── claim_processor.py  # pipeline runner + response mapper
│           ├── claim_repository.py # DB reads (get_claim, list_claims)
│           └── dead_letter.py      # DLQ stub (NoOpDLQ)
│
├── frontend/                       # Streamlit service
│   ├── requirements.in
│   ├── requirements.txt
│   └── app.py                      # Streamlit UI
│
├── docs/
│   ├── plan.md                     # this file
│   ├── design_decisions.md         # architectural decisions and trade-offs
│   ├── assumptions.md              # system assumptions (document collection, DB, policy)
│   ├── failure_handling.md         # per-node failure behaviour + combined scenarios
│   ├── architecture.md             # (deliverable — pending)
│   ├── contracts.md                # (deliverable — pending)
│   └── eval_report.md              # (deliverable — pending)
│
├── render.yaml                     # Render infra + CI/CD config
├── .env.example                    # committed — keys only, no values
├── .env.dev                        # gitignored — local dev values
└── .gitignore
```

---

## 6. System Architecture Overview

```
                        ┌─────────────────────────────┐
                        │        Entry Points          │
                        │                              │
                        │       ┌─────────┐            │
                        │       │ Web UI  │            │
                        │       │Streamlit│            │
                        │       └────┬────┘            │
                        └────────────┼─────────────────┘
                                     │ POST /api/claims
                                      ▼
                        ┌─────────────────────────────┐
                        │         FastAPI              │
                        │  - Request validation        │
                        │  - Saves raw files to disk   │
                        │  - Triggers LangGraph        │
                        └──────────────┬──────────────┘
                                       │
                                       ▼
                        ┌─────────────────────────────────────────┐
                        │           LangGraph Pipeline             │
                        │                                          │
                        │  [blur_gate]  OpenCV only, free, fast   │
                        │  Image variance < 80 → FAIL (stop)      │
                        │  Image with no data → FAIL (stop)       │
                        │  PDF → SKIP (Gemini handles internally)  │
                        │                 │                        │
                        │                 ▼ (all readable)         │
                        │  ┌─────────────────────────────────┐    │
                        │  │  GEMINI CALL 1: Extract Agent   │    │
                        │  │  gemini-3.1-flash-lite (primary) │    │
                        │  │  → classifies each doc type      │    │
                        │  │  → extracts all fields           │    │
                        │  │  → self-reported confidence      │    │
                        │  │  → patient_name_consistent check │    │
                        │  └──────────────┬──────────────────┘    │
                        │                 │                        │
                        │      ┌──────────┴──────────┐            │
                        │      │ patient_name_        │            │
                        │      │ consistent=False?    │            │
                        │      └──────────┬──────────┘            │
                        │    MISMATCH ◄───┘ ───► OK               │
                        │    [reject_patient_mismatch]             │
                        │    REJECTED, save_to_db, END            │
                        │                 │ (names OK)             │
                        │                 ▼                        │
                        │  [validate_documents]  Python, no LLM   │
                        │  Checks classified types vs policy reqs  │
                        │  Wrong/missing docs → FAIL (stop)        │
                        │                 │ PASS                   │
                        │                 ▼                        │
                        │  ┌─────────────────────────────────┐    │
                        │  │  GEMINI CALL 2: Adjudicate      │    │
                        │  │  gemini-3.1-flash-lite (primary) │    │
                        │  │  → policy eligibility (7 checks) │    │
                        │  │  → fraud detection               │    │
                        │  │  → network discount + co-pay     │    │
                        │  │  → APPROVED/PARTIAL/REJECTED/    │    │
                        │  │    MANUAL_REVIEW + confidence    │    │
                        │  └──────────────┬──────────────────┘    │
                        │                 │                        │
                        │  [save_to_db]  Claim + ClaimDocuments   │
                        │                 │                        │
                        └─────────────────┼────────────────────────┘
                                          │
                                          ▼
                        ┌─────────────────────────────┐
                        │      Decision Output         │
                        │  decision: APPROVED          │
                        │  approved_amount: 1350       │
                        │  confidence_score: 0.91      │
                        │  reason: "..."               │
                        │  trace: { full step log }    │
                        └─────────────────────────────┘
                                          │
                              ┌───────────┴───────────┐
                              │                       │
                              ▼                       ▼
                     Saved to PostgreSQL        LangSmith trace
                     (UI decision review)       (observability)
```

### LangGraph node sequence and conditional edges

```
START → blur_gate
  ├── image blurry or no data → END (DOCUMENT_UNREADABLE error, not saved to DB)
  └── all OK → extract_documents  [GEMINI CALL 1]
        ├── patient_name_consistent=False → reject_patient_mismatch → save_to_db → END
        └── names OK → validate_documents  (Python, no LLM)
              ├── FAIL → END (DOCUMENT_VALIDATION_FAILED error, not saved to DB)
              └── PASS → adjudicate_claim  [GEMINI CALL 2]
                    → confidence gate (Python)
                    → save_to_db → END
```

Early exits for blur and wrong doc type do NOT write to DB. Patient mismatch and adjudication decisions DO write to DB (REJECTED row created).

---

## 7. The Six Nodes — Responsibilities

---

### Node 1 — `blur_gate`
**OpenCV only. Runs first. Zero API calls.**

- For every image (JPEG/PNG): compute `cv2.Laplacian(gray, cv2.CV_64F).var()`
- If variance < 80 → `DOCUMENT_UNREADABLE` → stop immediately, tell member which file to re-upload
- If no `file_data` present for an image → `DOCUMENT_UNREADABLE` → stop
- PDFs always pass — Gemini accepts PDFs natively and handles readability internally
- Purpose: avoid wasting Gemini quota on images Gemini can't read anyway (TC002)

---

### Node 2 — `extract_documents`
**Gemini Call 1. Single call for ALL documents.**

One Gemini call processes all submitted documents simultaneously:
1. **Classify** — what type is each document? (`PRESCRIPTION / HOSPITAL_BILL / LAB_REPORT / PHARMACY_BILL / DENTAL_REPORT / DISCHARGE_SUMMARY / UNKNOWN`)
2. **Extract** — all relevant fields: `patient_name`, `doctor_name`, `date`, `diagnosis`, `total`, `line_items`, etc.
3. **Patient name cross-check** — compares `patient_name` across all documents; `patient_name_consistent=False` only when names clearly belong to different individuals (handles initials, titles, minor spelling variants)

We do not trust the client's declared document type label. Gemini reads the image and determines what it actually is.

- Confidence is self-reported per field — Gemini fills a `confidence: float` field in the response schema
- Gemini returns `null` for unreadable fields; confidence for that field = 0.0
- Accepts images and PDFs natively — no conversion step
- Graceful degradation: Gemini failure → `extraction_failed = True`, decision set to `MANUAL_REVIEW` at confidence 0.30, routes **directly to `save_to_db`** — validation and adjudication are skipped entirely

**Quality flags set:**
- `RUBBER_STAMP_OVER_TEXT` — field present but partially obscured
- `DOCUMENT_ALTERATION` — amounts crossed out and rewritten (surfaced to fraud agent)
- `MULTILINGUAL` — regional language fields detected, not extracted
- `PARTIAL_DOCUMENT` — required fields missing due to page cut-off

Output per document: `ExtractedDocument` with `classified_type`, typed fields, field-level confidence, quality flags.

---

### Node 3 — `validate_documents`
**Pure Python. No LLM. Uses Gemini-classified types — not client labels.**

1. Read required document types for this claim category from `policy_terms.json → document_requirements[category].required`
2. Compare against Gemini-classified `classified_type` for each submitted document
3. If wrong or missing types → stop with a specific error naming what was uploaded vs what is required (TC001)

Output: `PASS` or `FAIL` with actionable error message.

---

### Node 3a — `reject_patient_mismatch`
**Pure Python. Conditional branch off Node 2.**

Fast early exit when `extract_documents` sets `patient_name_consistent=False`. Returns `REJECTED` with `PATIENT_NAME_MISMATCH` reason, persists to DB, and ends the pipeline. No Gemini call consumed.

---

### Node 4 — `adjudicate_claim`
**Gemini Call 2. Single call handles all adjudication.**

One Gemini call performs all of the following:
1. **Policy eligibility** — member lookup, waiting periods (initial 30d, condition-specific 90–365d), exclusions, pre-auth requirements, per-claim limit, annual limit, sub-limit
2. **Fraud detection** — same-day duplicate claims, document alteration flags, high-value threshold (>₹25,000), monthly claim count
3. **Financial calculation** — network discount applied before co-pay; dental claims itemized (covered vs excluded procedures)
4. **Final decision** — APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW + structured rejection reasons + confidence score

**Confidence gate (Python, runs after Gemini returns):**
- ≥ 0.75 → honor Gemini's decision
- 0.50 – 0.74 → override to MANUAL_REVIEW regardless of Gemini's decision
- < 0.50 → override to REJECTED

REJECTED and MANUAL_REVIEW from Gemini are always honored — the gate only overrides APPROVED/PARTIAL decisions with insufficient confidence.

**Graceful degradation:** Gemini failure → APPROVED at confidence 0.50, `adjudicate` added to `failed_components`, manual review recommended in decision reason.

---

### Node 5 — `save_to_db`
**Pure Python. Runs last on every path that reaches a decision.**

Writes one `Claim` row and one `ClaimDocument` row per uploaded document to PostgreSQL. Stores the full `trace` JSONB so the Streamlit UI can reconstruct the decision audit trail without requiring LangSmith access.

**Graceful degradation:** DB write retried 3 times (1s, 2s delays). On total failure → HTTP 503 returned to caller; decision is **not** delivered without a DB record. Failed claim published to dead letter queue stub for manual recovery.

---

## 8. Database Schema

```sql
-- One row per submitted claim
claims (
  id              UUID PRIMARY KEY,
  member_id       VARCHAR,
  policy_id       VARCHAR,
  claim_category  VARCHAR,
  treatment_date  DATE,
  claimed_amount  NUMERIC,
  submitted_at    TIMESTAMP,

  -- Decision output
  decision        VARCHAR,   -- APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW / ERROR
  approved_amount NUMERIC,
  confidence_score FLOAT,
  rejection_reasons JSONB,   -- list of rejection reason codes
  decision_reason TEXT,

  -- Full pipeline trace (dumped LangGraph state)
  trace           JSONB,

  -- Component failure tracking
  failed_components JSONB,   -- list of agent names that failed

  -- Channel tracking
  source_channel  VARCHAR    -- WEB / WHATSAPP / EMAIL
)

-- One row per uploaded document per claim
claim_documents (
  id              UUID PRIMARY KEY,
  claim_id        UUID REFERENCES claims(id),
  file_name       VARCHAR,
  document_type   VARCHAR,   -- PRESCRIPTION / HOSPITAL_BILL / etc.
  extraction      JSONB,     -- ExtractedDocument output
  quality_flags   JSONB,
  confidence      FLOAT
)
```

---

## 9. API Contract

### `POST /api/claims`
Submit a claim for processing.

**Request:**
```json
{
  "member_id": "EMP001",
  "policy_id": "PLUM_GHI_2024",
  "claim_category": "CONSULTATION",
  "treatment_date": "2024-11-01",
  "claimed_amount": 1500,
  "documents": [
    {
      "file_name": "prescription.jpg",
      "file_data": "<base64-encoded>",
      "mime_type": "image/jpeg"
    }
  ]
}
```

**Response (success):**
```json
{
  "claim_id": "uuid",
  "decision": "APPROVED",
  "approved_amount": 1350,
  "confidence_score": 0.91,
  "reason": "Claim approved. Co-pay of 10% (₹150) deducted.",
  "rejection_reasons": [],
  "trace": { ... },
  "failed_components": []
}
```

**Response (document error):**
```json
{
  "claim_id": null,
  "decision": null,
  "error_type": "DOCUMENT_VALIDATION_FAILED",
  "message": "You uploaded two prescriptions. A CONSULTATION claim requires a PRESCRIPTION and a HOSPITAL_BILL. Please upload your hospital bill and resubmit.",
  "what_was_uploaded": ["PRESCRIPTION", "PRESCRIPTION"],
  "what_is_required": ["PRESCRIPTION", "HOSPITAL_BILL"]
}
```

### `GET /api/claims/{claim_id}`
Retrieve a claim decision + full trace.

### `GET /api/claims?member_id=EMP001`
List all claims for a member (for fraud check + UI).

### `GET /api/health`
Health check for Render.

---

## 10. Observability

Three layers, no extra tooling needed:

| Layer | Tool | What it covers |
|-------|------|----------------|
| AI pipeline | **LangSmith** | Per-claim trace: which agent ran, inputs/outputs, why confidence dropped, latency per agent |
| Infra metrics | **Render dashboard** (built-in) | CPU, memory, response times, request throughput, deploy logs |
| Uptime | **cron-job.org** (free external) | Scheduled pings every 5 min, execution history, failure notifications — NOT a full APM; does not show what failed inside the app |

cron-job.org's role is keep-alive pings (prevents Render free tier cold starts) + alerting if the service actually dies. All deeper "what failed and why" comes from LangSmith + PostgreSQL.

**The `trace` JSONB column in PostgreSQL** is a copy of the LangGraph state at the end of the run — used by the Streamlit UI to show the trace without requiring a LangSmith login.

---

## 11. Eval Report Plan (12 Test Cases)

| Case | Scenario | Expected |
|------|----------|----------|
| TC001 | Wrong doc type uploaded | FAIL: specific message naming uploaded vs required type |
| TC002 | Unreadable pharmacy bill | FAIL: ask to re-upload that specific doc, not reject |
| TC003 | Documents for different patients | FAIL: name both patients found |
| TC004 | Clean consultation | APPROVED: ₹1,350 (10% co-pay on ₹1,500) |
| TC005 | Diabetes within 90-day waiting period | REJECTED: state eligibility date |
| TC006 | Dental — root canal + teeth whitening | PARTIAL: ₹8,000 approved, whitening rejected with reason |
| TC007 | MRI without pre-auth | REJECTED: explain pre-auth process |
| TC008 | Claim exceeds ₹5,000 per-claim limit | REJECTED: state limit and claimed amount |
| TC009 | 4th same-day claim | MANUAL_REVIEW: list all fraud signals |
| TC010 | Network hospital | APPROVED: ₹3,240 (20% discount first, then 10% co-pay) |
| TC011 | Component failure mid-run | APPROVED with lower confidence + failure noted |
| TC012 | Bariatric / obesity treatment | REJECTED: excluded condition |

---

## 12. Day-by-Day Timeline (5 Days)

**Day 1 — Scaffold ✅ Complete (Jun 16)**

Infrastructure:
- `render.yaml` — 2 web services + PostgreSQL, CI/CD via git push to main
- `.env.dev` (gitignored) — local dev values including Render external DB URL
- `.env.example` (committed) — keys only, no values, in sync with `.env.dev`
- `.gitignore` — ignores `.env`, `.env.dev`, `.vscode/`, `.claude/`, `__pycache__/`
- Git repo initialized, connected to GitHub, deployed on Render
- cron-job.org configured to ping both services every 5 min

Monorepo structure:
- `backend/` — FastAPI service with `backend/requirements.in` + `backend/requirements.txt`
- `frontend/` — Streamlit service with `frontend/requirements.in` + `frontend/requirements.txt`
- Shared `.venv` at project root; VS Code debug configs in `.vscode/launch.json`

Backend (`backend/src/`):
- `main.py` — FastAPI app, CORS, lifespan hook, `/api/health` with live DB connectivity check
- `config.py` — pydantic-settings, loads `.env.dev` in dev, Render env vars in prod

Frontend (`frontend/`):
- `app.py` — Streamlit app, warms API on load, shows version + environment + DB status

Verified working:
- `GET /api/health` returns `{"status": "ok", "db": {"connected": true}}`
- Streamlit loads and shows system status from health endpoint
- PostgreSQL connected (Render free tier)

---

**Day 2 — Foundation + Pipeline Nodes (Complete)**

Done:
- SQLAlchemy DB models (`Claim`, `ClaimDocument`) + Alembic migrations (applied to Render PostgreSQL)
- Pydantic schemas (`ClaimSubmitRequest`, `ClaimResponse`, `DocumentValidationError`, `DocumentInput`)
- `ClaimState` LangGraph TypedDict
- Policy loader (`@lru_cache`, reads `policy_terms.json` at startup)
- File storage: raw files saved to `backend/uploads/claims/{claim_id}/`, served via `StaticFiles`
- Controller/service separation
- Streamlit: Submit Claim tab, Test Cases tab (smoke tests with real mock images), Claims History tab
- Mock document image generator (`generate_test_docs.py`) + 24 images for TC001–TC012
- pytest: 9 tests for validation, 7 tests for extraction

**Day 2 pipeline built but needs rework (see Day 3):**
- Blur gate runs first ✅ (keep)
- Extraction runs second ✅ (keep, but add doc type classification to Gemini prompt)
- Validation runs third — **currently trusts client label; must use Gemini-classified type instead**
- Patient name check ✅ (keep as-is)
- Pipeline terminates after patient name check with `decision="PENDING"` — Day 3 adds policy + fraud + decision

TC001, TC002, TC003 pass in test-mode. Need to verify with real Gemini smoke tests.

---

**Day 3 — Rework Pipeline + Agents 3–5 + DB Save (Jun 18)**

Morning — Fix pipeline order:
- Update Gemini prompt in `extraction.py` to also classify doc type → `classified_type` field on `ExtractedDocument`
- Update `validate_documents` to use `classified_type` from extracted docs (not client label)
- Add `ClaimState` fields for policy/fraud/decision results
- Wire pipeline: `blur_gate → extract → validate → patient_check → policy_check → fraud_check → make_decision → save_to_db → END`

Afternoon — New agents:
- **Agent 3: Policy Check** — all 13 checks, pure Python, no LLM:
  - Member exists, policy active, claim within 30-day submission window
  - Initial waiting period (30d from join), condition-specific waiting period (diabetes 90d, etc.)
  - Exclusion check (bariatric, obesity, cosmetic, alternative medicine)
  - Pre-auth required: MRI/CT/PET > ₹10,000 (TC007)
  - Per-claim limit: claimed > ₹5,000 → REJECTED for non-dental (TC008)
  - Annual OPD limit: ytd_claims_amount + approved > ₹50,000
  - Dental line-item filter: covered vs excluded procedures (TC006)
  - Network hospital discount applied before copay (TC010)
  - Copay applied after discount
- **Agent 4: Fraud Detection** — same-day claims from `claims_history` input + DB count; ≥3 on same day → `MANUAL_REVIEW` (TC009)
- **Agent 5: Decision + Make Decision** — synthesise all results, compute confidence score, produce final decision
- **save_to_db node** — write `Claim` + `ClaimDocument` rows after pipeline completes
- Tests for all new agents

Test cases passing by end of day: **TC001–TC010, TC012**

---

**Day 4 — TC011 + Streamlit polish + Full E2E (Jun 19)**

Morning:
- TC011 (component failure simulation via `simulate_component_failure` flag)
- All 12 test cases passing end-to-end
- Verify confidence score formula against TC004 (>0.85), TC011 (lower), TC012 (>0.90)

Afternoon:
- Streamlit UI polish: trace viewer, document preview, decision badge
- Verify full smoke test flow on deployed Render URL
- Git commit with clean history

Test cases passing by end of day: **all 12 (TC001–TC012)**

---

**Day 5 — Docs + Eval Report + Demo Video (Jun 20)**

Morning:
- Run all 12 test cases through deployed system, capture outputs
- Write `docs/eval_report.md` — decision + full trace for each case, explain any mismatches
- Write `docs/architecture.md`
- Write `docs/contracts.md` — input/output/errors per agent

Afternoon:
- Record demo video (8–12 min): wrong-doc error → full approval trace → one proud decision + one regret
- Final commit, clean up repo, verify deployed URLs
- Submit

---

## 13. Deliverables Checklist

- [x] Working system with deployed URL (Render)
- [x] GitHub repo with clean commit history
- [x] Tests: pytest for every agent (extraction, adjudication, document validation)
- [ ] Architecture document (`docs/architecture.md`)
- [ ] Component contracts (`docs/contracts.md`) — input/output/errors for each agent
- [ ] Eval report (`docs/eval_report.md`) — all 12 test cases with decision + trace
- [ ] Demo video (8–12 min): wrong-doc error, full approval trace, one proud decision + one regret

---

## 14. Confidence Score System

There are three distinct layers of confidence in the system.

### Layer 1 — OpenCV Blur Variance (local readability gate)
Before any API call, a blur check runs on each image:
```python
gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
variance = cv2.Laplacian(gray, cv2.CV_64F).var()
# variance < 80 → UNREADABLE (threshold tunable per doc type)
```
This is objective, deterministic, costs nothing, and protects Gemini quota from garbage image inputs.
PDFs skip this check — Gemini accepts them natively and reports unreadable pages within its extraction response.

### Layer 2 — Gemini Extraction Confidence (self-reported per document)
The extraction schema includes a `confidence: float` field that Gemini fills based on its own assessment — legibility, stamp obscurement, partial pages, handwriting. Stored per document in `claim_documents.extraction` JSONB and visible in the UI trace.

### Layer 3 — Decision Confidence Score (self-reported by adjudication Gemini)
The adjudication schema includes a `confidence_score: float` field. Gemini sets this based on its own certainty about the policy evaluation — ambiguous diagnoses, partial data, fraud signals.

Gemini is instructed to follow this formula:
```
Start at 0.9
Deduct: 0.15 per failed_component, 0.10 if manual_review flagged, 0.03 per warning
APPROVED/PARTIAL/REJECTED: clamp to [0.70, 1.0]
MANUAL_REVIEW: clamp to [0.50, 0.80]
```

**Python confidence gate (post-adjudication):**

| Gemini confidence | Action |
|---|---|
| ≥ 0.75 | Honor Gemini's decision |
| 0.50 – 0.74 | Override APPROVED/PARTIAL → MANUAL_REVIEW |
| < 0.50 | Override APPROVED/PARTIAL → REJECTED |

REJECTED and MANUAL_REVIEW from Gemini are always honored — the gate only overrides optimistic decisions with insufficient confidence.

**Fixed confidence values for failure paths:**

| Scenario | Confidence | Set by |
|---|---|---|
| TC011 simulated failure | 0.60 | Python (hardcoded for TC011) |
| Adjudication Gemini failure | 0.50 | Python (`_graceful_pass`) |
| Extraction Gemini failure | 0.30 | Python (extraction node) |

---

## 15. AI / OCR Infrastructure — Install Summary

Actual `requirements.txt` (committed to repo):
```
# API
fastapi
uvicorn[standard]

# UI
streamlit
httpx

# Database
sqlalchemy
alembic
psycopg2-binary

# AI / ML
google-generativeai
langchain-google-genai
langgraph
langsmith

# Image processing
opencv-python-headless
pillow

# Config & utilities
pydantic
pydantic-settings
python-dotenv
```

Note: `langchain-google-genai` is used for all Gemini calls via LangChain's `with_structured_output` — this keeps LangSmith tracing seamless across all pipeline nodes.

```
# .env
GOOGLE_API_KEY=<from aistudio.google.com — no credit card required>
LANGSMITH_API_KEY=<from smith.langchain.com — free tier>
```

No system binaries. No binary installers. No paid accounts.
Gemini accepts PDFs natively — no poppler, no pdf2image.

**Free tier limits (Gemini 2.5 Flash, Google AI Studio):**
- 250 requests / day
- 10 requests / minute
- 250,000 tokens / minute
- A high-res medical image ≈ 250–1,000 tokens → well within limits for 12 test cases + demo

---

## 16. Resolved Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Document upload format | **base64 in JSON body** — single endpoint, curl-testable |
| 2 | Frontend | **Streamlit** — Python-native, fast to build, sufficient for demo |
| 3 | TC009 claims history | **Accept as optional `claims_history` input field** — matches test case JSON, no DB seeding needed |
| 4 | LangSmith acceptable? | **Yes** — free tier, key in `.env.example`, no vendor lock-in |
| 5 | Docker needed? | **No** — Render native Python buildpack handles everything |
| 6 | Keep-alive strategy | **cron-job.org** (external, free) — pings `/api/health` every 5 min; also alerts on real downtime |
