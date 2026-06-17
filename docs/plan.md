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
- The WhatsApp/email conversation layer (that is n8n's job, can be added as a separate extension)
- Pre-authorization request flows (we detect missing pre-auth and reject, we don't initiate it)
- A dedicated OCR library (we use Gemini 2.5 Flash vision for extraction; OpenCV only for a local blur gate)

---

## 4. Tech Stack Decisions

### Core Pipeline
| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python 3.11+ | Standard for AI/ML work; assignment expects it |
| Agent Orchestration | **LangGraph** | True multi-agent graph with state; bonus points for multi-agentic architecture; built-in tracing |
| OCR + Extraction | **Gemini 2.5 Flash** (Google AI Studio) | Free tier (250 req/day, 10 RPM, 250K TPM); vision-native; accepts images and PDFs directly; one call = OCR + structured extraction + per-field confidence |
| Text / Reasoning | **Gemini 2.5 Flash-Lite** (Google AI Studio) | Free tier; used for decision explanation text and any soft reasoning; lighter and faster than Flash |
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
| Keep-alive | **UptimeRobot** | Free external pings every 5 min to prevent cold starts; also doubles as uptime alerting |
| Docker | **Not needed** | Render's native Python buildpack handles the full stack; no system binaries required |
| n8n (extension) | **n8n Cloud or self-hosted** | WhatsApp + email channel layer; calls FastAPI only, built after core |

### What We Rejected and Why
- **n8n as core processor** — cannot write unit tests against n8n nodes; no Pydantic contracts; poor observability
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
│   ├── __init__.py
│   ├── requirements.in             # unpinned deps (edit this)
│   ├── requirements.txt            # pinned deps (pip-compile output)
│   └── src/
│       ├── __init__.py
│       ├── config.py               # pydantic-settings, loads .env.dev
│       ├── main.py                 # FastAPI app, health check, CORS
│       ├── models/                 # SQLAlchemy DB models (Day 2)
│       ├── schemas/                # Pydantic request/response models (Day 2)
│       ├── agents/                 # LangGraph agents (Day 2-4)
│       ├── pipeline/               # LangGraph graph + state (Day 2)
│       └── services/               # policy loader, Gemini client (Day 2)
│
├── frontend/                       # Streamlit service
│   ├── __init__.py
│   ├── requirements.in
│   ├── requirements.txt
│   └── app.py                      # Streamlit UI
│
├── docs/
│   ├── plan.md                     # this file
│   ├── technical_notes.md          # Gemini logprobs pattern, code snippets
│   ├── architecture.md             # (Day 5)
│   ├── contracts.md                # (Day 5)
│   └── eval_report.md              # (Day 5)
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
                        │  ┌─────────┐  ┌──────────┐  │
                        │  │ Web UI  │  │  n8n     │  │
                        │  │Streamlit│  │(WA/Email)│  │
                        │  └────┬────┘  └────┬─────┘  │
                        └───────┼────────────┼─────────┘
                                │            │
                                └─────┬──────┘
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
                        │  │  gemini-2.0-flash-lite (primary) │    │
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
                        │  │  gemini-2.5-flash (primary)      │    │
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
  ├── any UNREADABLE → END (DOCUMENT_UNREADABLE error)
  └── all OK → extract_documents
        ↓
      validate_documents  (uses Gemini-classified types)
  ├── FAIL → END (DOCUMENT_VALIDATION_FAILED error)
  └── PASS → check_patient_names
        ├── FAIL → END (PATIENT_NAME_MISMATCH error)
        └── PASS → policy_check → fraud_check → make_decision → save_to_db → END
```

Early exits (blur, wrong doc type, patient mismatch) do NOT write to DB — no claim row created.

---

## 6. The Five Agents — Responsibilities

### Blur Gate (pre-node, OpenCV only)
**Runs first. Zero API calls. Pure local image check.**

- For every image file (JPEG/PNG): compute `cv2.Laplacian(gray, cv2.CV_64F).var()`
- If variance < 80 → `DOCUMENT_UNREADABLE` → stop immediately, tell member which file to re-upload
- PDFs skip this check — Gemini accepts PDFs natively and handles readability internally
- Purpose: avoid wasting Gemini quota on images Gemini can't read anyway (TC002)

---

### Agent 1: Extract + Classify Agent
**Gemini 2.5 Flash Vision. Runs first among AI agents.**

Single Gemini call per document that does two things at once:
1. **Classify** — what type of document is this? (`PRESCRIPTION / HOSPITAL_BILL / LAB_REPORT / PHARMACY_BILL / DENTAL_REPORT / DISCHARGE_SUMMARY / DIAGNOSTIC_REPORT`)
2. **Extract** — all relevant fields: `patient_name`, `doctor_name`, `date`, `diagnosis`, `total`, `line_items`, etc.

We do not trust the client's declared document type label. Gemini reads the image and determines what it actually is. This is the correct implementation of "catch wrong documents" — you can only detect a wrong document by reading it.

- Called with `response_logprobs=True` — field confidence from token log probabilities, not self-reported
- Gemini returns `null` for unreadable fields; confidence for that field = 0.0
- Accepts images and PDFs natively — no conversion step
- Graceful degradation: Gemini failure → adds `extraction_agent` to `failed_components`, continues with empty extraction

**Quality flags set:**
- `RUBBER_STAMP_OVER_TEXT` — field present but partially obscured
- `DOCUMENT_ALTERATION` — amounts crossed out and rewritten (surfaced to fraud agent)
- `MULTILINGUAL` — regional language fields detected, not extracted
- `PARTIAL_DOCUMENT` — required fields missing due to page cut-off

Output per document: `ExtractedDocument` with `classified_type`, typed fields, field-level confidence, quality flags.

---

### Agent 2: Document Validation Agent
**Pure logic. Runs after extraction. Uses Gemini-classified types — not client labels.**

Checks (in order):
1. Are the required document types present for this claim category? Compare Gemini-classified `classified_type` for each doc against `policy_terms.json → document_requirements[category].required`
2. If wrong/missing types → stop with specific error naming what was found vs what is required (TC001)

Output: `PASS` or `FAIL` with actionable error message.

---

### Patient Name Check (inline node, not a full agent)
Compares `patient_name` across all extracted documents. If any mismatch → stop with error naming which doc had which name (TC003).

---

---

### Agent 3: Policy Check Agent
**Pure logic — no LLM. Reads `policy_terms.json`.**

Checks (all must pass for APPROVED):
1. Member exists and policy is active
2. Treatment date within claim submission deadline (30 days)
3. Initial waiting period passed (30 days from join date)
4. Condition-specific waiting period passed (diabetes: 90 days, etc.)
5. Treatment not in exclusions list
6. Claim category is covered
7. Claimed amount ≤ per-claim limit (₹5,000)
8. Claimed amount ≤ remaining annual OPD limit
9. Category sub-limit not exceeded
10. Pre-authorization obtained if required (MRI > ₹10,000, CT Scan, etc.)
11. For dental: each line item checked against covered/excluded procedures
12. Network hospital? Apply discount before co-pay (order matters — TC010)
13. Compute approved amount: `(claimed - network_discount) - co_pay`

Output: `PolicyCheckResult` with each check as a named pass/fail + computed approved amount + rejection reasons list.

---

### Agent 4: Fraud Detection Agent
**Queries database for claims history.**

Checks:
1. Same-day claims count for this member (threshold: 2 per day → MANUAL_REVIEW at 3+)
2. Document alteration flags from extraction (crossed-out amounts, duplicate stamps)
3. High-value claim threshold (> ₹25,000 → MANUAL_REVIEW)
4. Monthly claims count (> 6 → flag)

Output: `FraudCheckResult` with fraud score (0.0–1.0) + list of triggered signals. Does not auto-reject — routes to MANUAL_REVIEW.

---

### Agent 5: Decision Agent
**Aggregates all prior agent outputs into a final decision.**

Logic:
- If Document Validation failed → return the specific error (no decision)
- If any Policy Check failed → REJECTED with all rejection reasons
- If fraud score > 0.80 → MANUAL_REVIEW with fraud signals
- If partial coverage (some line items excluded, some covered) → PARTIAL with itemized breakdown
- If all checks pass → APPROVED with final approved amount
- If any component failed mid-run (graceful degradation) → note it, reduce confidence, recommend manual review

Confidence score: computed using the deterministic penalty formula defined in Section 14, Layer 3. The Decision Agent receives all prior agent outputs and applies the formula once to produce the final score.

Output: `ClaimDecision` — the final API response.

---

## 7. Database Schema

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

## 8. API Contract

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

## 9. n8n Integration (Extension — built after core)

n8n acts as the **channel layer only**. It has no claims logic.

**WhatsApp flow (Twilio sandbox):**
1. Member messages the WhatsApp number
2. n8n AI Agent node collects: member ID, claim category, amount, treatment date
3. n8n asks for documents one by one (as image attachments)
4. Once all collected → n8n HTTP Request node calls `POST /api/claims`
5. n8n sends the decision back as a WhatsApp message

**Email flow (Gmail trigger):**
1. n8n Gmail trigger on new email to claims inbox
2. Extracts attachments + email body fields
3. Calls `POST /api/claims`
4. Replies to the email with the decision

n8n does not need to know about LangGraph, agents, or policy rules. It only speaks to the API.

---

## 10. Observability

Three layers, no extra tooling needed:

| Layer | Tool | What it covers |
|-------|------|----------------|
| AI pipeline | **LangSmith** | Per-claim trace: which agent ran, inputs/outputs, why confidence dropped, latency per agent |
| Infra metrics | **Render dashboard** (built-in) | CPU, memory, response times, request throughput, deploy logs |
| Uptime | **UptimeRobot** (free external) | Up/down status, avg response time graph, downtime incidents, alerts — NOT a full APM; does not show what failed inside the app |

UptimeRobot's role is keep-alive pings (prevents Render free tier cold starts) + alerting if the service actually dies. All deeper "what failed and why" comes from LangSmith + PostgreSQL.

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
- UptimeRobot configured to ping both services every 5 min

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
- n8n WhatsApp/email setup (stretch — only if time permits)
- Final commit, clean up repo, verify deployed URLs
- Submit

---

## 13. Deliverables Checklist

- [ ] Working system with deployed URL (Render)
- [ ] GitHub repo with clean commit history
- [ ] Architecture document (`docs/architecture.md`)
- [ ] Component contracts (`docs/contracts.md`) — input/output/errors for each agent
- [ ] Eval report (`docs/eval_report.md`) — all 12 test cases with decision + trace
- [ ] Demo video (8–12 min): wrong-doc error, full approval trace, one proud decision + one regret
- [ ] Tests: pytest for every agent (mocked LLM responses)

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
PDFs skip this check — Gemini accepts them natively and reports unreadable pages within its extraction response (low confidence fields or explicit null values).

### Layer 2 — Gemini 2.5 Flash Field Confidence (logprobs — objective)
We use `response_logprobs=True` in the Gemini call — this returns the model's actual token-level log probabilities, not a self-reported number. This is more reliable than asking Gemini to guess its own confidence.

```python
# confidence per token = math.exp(logprob)
# confidence per field = mean across all tokens in that field's value
```

Fields where Gemini returns `null` (not found) → `confidence = 0.0`.
All per-field confidences stored in `claim_documents.extraction` JSONB and visible in the UI trace.

See `docs/technical_notes.md` for the full Gemini call pattern with logprobs.

### Layer 3 — Decision Confidence Score (deterministic formula)

Measures: **"how complete and reliable is our analysis?"** — not likelihood of approval.
A clear rejection (TC012) should score > 0.90 because the policy rule matched cleanly.

```
start: 1.0

Document quality penalties (per document):
  avg OCR confidence < 0.40  →  -0.20
  avg OCR confidence < 0.70  →  -0.08

Field extraction penalties (per required field):
  field.confidence < 0.50    →  -0.03

Component failure penalties (TC011 — graceful degradation):
  each skipped/failed agent  →  -0.15

Fraud signal penalties:
  each triggered signal      →  -0.10

final = clamp(score, 0.0, 1.0)
```

**Sanity check against test cases:**

| Case | Scenario | Expected | Formula gives |
|------|----------|----------|---------------|
| TC004 | Clean docs, all agents run | > 0.85 | ~0.93 |
| TC011 | One agent fails | Lower than TC004 | ~0.78 |
| TC012 | Clear exclusion, clean docs | > 0.90 | ~0.93 |

The penalty table lives in one config dataclass — not scattered across agents.

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

Note: Agent nodes call `google-generativeai` SDK directly (not via LangChain wrapper) to preserve access to `response_logprobs=True`. `langchain-google-genai` is kept only for LangGraph's tracing hooks. See `docs/technical_notes.md`.

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
| 1 | Document upload format | **base64 in JSON body** — single endpoint, curl-testable, n8n-compatible |
| 2 | Frontend | **Streamlit** — Python-native, fast to build, sufficient for demo |
| 3 | TC009 claims history | **Accept as optional `claims_history` input field** — matches test case JSON, no DB seeding needed |
| 4 | LangSmith acceptable? | **Yes** — free tier, key in `.env.example`, no vendor lock-in |
| 5 | Docker needed? | **No** — Render native Python buildpack handles everything |
| 6 | Keep-alive strategy | **UptimeRobot** (external, free) — pings `/api/health` every 5 min; also alerts on real downtime |
