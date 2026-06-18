# ClaimPilot — System Architecture

## 1. Overview

ClaimPilot is a production-grade automated health insurance claims processing system. It accepts a claim submission (member details, treatment category, claimed amount, one or more medical documents), runs it through a six-node LangGraph pipeline, and returns a decision — `APPROVED`, `PARTIAL`, `REJECTED`, or `MANUAL_REVIEW` — with a confidence score, approved amount, and a full decision trace.

The system is designed around three constraints from the assignment:

1. **Every decision must be explainable.** Any claim must be reconstructible from its trace alone — which nodes ran, what each extracted, what policy checks applied, and why the final decision was reached.
2. **No single component failure may crash the system.** LLM failures, parse errors, and DB outages are handled at the node level, not the caller level.
3. **Document problems must stop the pipeline early with actionable errors.** Wrong documents or unreadable images halt immediately before any LLM quota is consumed.

---

## 2. Component Map

```
┌─────────────────────────────────────────────────────────────────┐
│  User (browser)                                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP
┌────────────────────────▼────────────────────────────────────────┐
│  Frontend — Streamlit (frontend/app.py)                         │
│  • Claim submission form                                        │
│  • Decision + trace viewer                                      │
│  • Claims history table                                         │
└────────────────────────┬────────────────────────────────────────┘
                         │ POST /api/claims   GET /api/claims
┌────────────────────────▼────────────────────────────────────────┐
│  API Layer — FastAPI (backend/src/main.py)                      │
│  • /api/claims    ClaimsController  → process_claim()           │
│  • /api/claims/{id}                → get_claim_by_id()          │
│  • /health                         → health check               │
└────────────────────────┬────────────────────────────────────────┘
                         │ await pipeline.ainvoke(ClaimState)
┌────────────────────────▼────────────────────────────────────────┐
│  Pipeline — LangGraph (backend/src/pipeline/)                   │
│                                                                 │
│   [blur_gate] ──────────────────────────────────────────────┐   │
│        │ pass                                               │   │
│   [extract_documents] ──────────────────────────────────┐   │   │
│        │ pass + consistent        failed  │              │   │   │
│        │              ┌───────────────────┘              │   │   │
│   [validate_docs]  [reject_mismatch]              save_db│   │   │
│        │ pass              │                             │   │   │
│   [adjudicate_claim]       │                             │   │   │
│        └──────────────────►[save_to_db]◄────────────────┘   │   │
│                                 │                            │   │
│                                [END]                         │   │
│                         ← early exits (blur/doc invalid) ───►┘   │
└────────────────────────┬────────────────────────────────────────┘
          │              │              │              │
    ┌─────▼─────┐  ┌─────▼─────┐ ┌────▼────┐  ┌─────▼──────┐
    │  OpenCV   │  │  Gemini   │ │ Policy  │  │ PostgreSQL │
    │ (blur)    │  │  Vision   │ │  JSON   │  │ SQLAlchemy │
    └───────────┘  └─────┬─────┘ └─────────┘  └────────────┘
                         │
                   ┌─────▼──────┐
                   │ LangSmith  │
                   │  tracing   │
                   └────────────┘
```

---

## 3. Components

### 3.1 Frontend (`frontend/app.py`)

A Streamlit application with two views:

**Submit view** — collects member ID, treatment category, hospital name, claimed amount, treatment date, and document uploads. Also collects prior claims history and YTD approved amount to pass as fraud context (see [§7.4](#74-fraud-context-frontend-supplied-vs-db-queried)). Sends a `POST /api/claims` request with documents encoded as base64.

**Decision view** — displays the decision badge, approved amount, confidence score, rejection reasons, document list (with Gemini-classified types), and a collapsible full trace panel. The trace panel renders the raw JSON from the pipeline, which contains per-node structured output for LangSmith-style debugging.

The frontend does not contain business logic. It is a thin UI over the API.

---

### 3.2 API Layer (`backend/src/`)

**FastAPI** provides the REST interface. Two controllers:

- `ClaimsController` (`controllers/claims.py`) — `POST /api/claims` receives a `ClaimSubmitRequest`, calls `process_claim()`, and returns either a `ClaimResponse` or a `DocumentValidationError` (both are 200 responses; the shape differs by `error_type`).
- `HealthController` (`controllers/health.py`) — `GET /health` for Render uptime checks.

Request validation is handled by **Pydantic** (`schemas/claim.py`, `schemas/documents.py`). Documents arrive as base64-encoded strings with MIME type declarations. Invalid payloads are rejected before the pipeline is invoked.

**`process_claim()`** (`services/claim_processor.py`) is the async pipeline entry point:

1. Generate a `claim_id` (UUID4).
2. Persist raw document bytes to disk via `await asyncio.to_thread(_persist_documents, ...)` — file I/O runs in a thread pool so the event loop is not blocked.
3. Build the initial `ClaimState`.
4. `await pipeline.ainvoke(initial_state)` — LangGraph runs async nodes with `await`; sync nodes (`blur_gate`, `validate_documents`, `reject_patient_mismatch`) are automatically dispatched via `asyncio.to_thread()`.
5. If `save_to_db` is in `failed_components`, raise HTTP 503 (claim not delivered without a DB record).
6. Map final state to a response object via `_map_state_to_response()`.

---

### 3.3 Pipeline (`backend/src/pipeline/`)

The core processing logic runs as a **LangGraph `StateGraph`** (`pipeline/graph.py`). LangGraph was chosen over low-code alternatives (n8n, Make) because its nodes are plain Python functions — unit testable, typed, and natively traceable via LangSmith. The full rationale is in `docs/design_decisions.md §1`.

**`ClaimState`** (`pipeline/state.py`) is a `TypedDict` that flows through every node. Each node reads fields it needs and returns a dict of fields it updates — LangGraph merges updates into the shared state. No node receives mutable references to state.

**Routing** is handled by three conditional edge functions:

```
_route_after_blur(state)       → END  |  extract_documents
_route_after_extraction(state) → save_to_db  |  reject_patient_mismatch  |  validate_documents
_route_after_validation(state) → END  |  adjudicate_claim
```

All routing logic is in `graph.py` — no branching is hidden inside node bodies.

---

### 3.4 Node 1 — `blur_gate` (`agents/blur_gate.py`)

**Purpose:** Reject unreadable images before any LLM quota is consumed.

**Mechanism:** For each image document, computes the **Laplacian variance** of the grayscale image using OpenCV. The Laplacian is a second-derivative edge detector — a sharp image has many strong edges (high variance); a blurry image has few (low variance). Threshold: variance < 80 → unreadable.

PDFs are skipped. Gemini handles PDF readability internally via its own vision pipeline; OpenCV cannot parse PDF byte streams.

**Outputs on failure:** Sets `blur_check_passed = False`, `blur_error` (with the specific filename and a member-facing message), and routes to `END` — no DB write. The member is told exactly which file to re-upload.

**Outputs on pass:** Sets `blur_check_passed = True`. Each document gets a `{file, result, variance}` trace entry.

**OpenCV errors** (corrupted images, unsupported formats) are caught per-document — that document is skipped with `result: SKIP` and the pipeline continues. Blur gate only fails hard on confirmed blurry images, not on parsing errors.

---

### 3.5 Node 2 — `extract_documents` (`agents/extraction.py`)

**Purpose:** OCR, classify, and extract structured fields from all submitted documents in a single multimodal Gemini call.

**Input to Gemini:** All documents sent as a single `HumanMessage` with interleaved text separators and image/PDF content blocks. Images are sent as `{type: "image", base64, mime_type}`; PDFs as `{type: "file", base64, mime_type: "application/pdf"}`. Gemini accepts both natively.

**Structured output schema** (`_AllDocumentsExtraction`):
- `documents[]` — one `_DocumentExtraction` per input document, containing: `classified_type` (PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, DENTAL_REPORT, DISCHARGE_SUMMARY, or UNKNOWN), `patient_name`, `doctor_name`, `date`, `diagnosis`, `medicines[]`, `hospital_name`, `line_items[]`, `total`, `test_name`, `quality_flags[]`, `confidence`.
- `patient_name_consistent: bool` — Gemini evaluates whether all patient names across documents belong to the same person. Initials, titles, and minor spelling variations are not mismatches.
- `patient_name_mismatch_details: str | None` — explanation of any mismatch.

Gemini returns a validated JSON object directly via `with_structured_output(schema, method="json_schema")`. No secondary parsing step.

**Failure path:** Any exception from the LLM call sets `extraction_failed = True`, `decision = MANUAL_REVIEW`, `confidence = 0.30`, adds `"extraction_agent"` to `failed_components`, and routes directly to `save_to_db`. Downstream validation and adjudication are skipped — calling Gemini again after a failure would consume quota for a second failure.

**Why Gemini Vision over EasyOCR + LLM:** Gemini processes images directly, preserving spatial layout; EasyOCR produces flat text that discards which bill line item belongs to which description. Gemini handles handwritten prescriptions better than OCR trained on printed text. Gemini accepts PDFs natively; EasyOCR needs `pdf2image` + `poppler` (a system binary Render's free tier does not support). Gemini emits per-field `confidence` as part of the structured output; EasyOCR confidence is character-level and does not map to extracted fields. Full comparison in `design_decisions.md §4`.

---

### 3.6 Node 3a — `reject_patient_mismatch` (`agents/patient_name_check.py`)

**Purpose:** Record and persist the rejection for a patient name mismatch identified during extraction.

A dedicated node (rather than folding this check into `validate_documents`) because identity integrity and document completeness are distinct failure reasons. The graph topology — `extract_documents → reject_patient_mismatch → save_to_db` — makes the cause unambiguous in LangSmith traces without reading the rejection text. See `design_decisions.md §9`.

Sets `decision = REJECTED`, `rejection_reasons = ["PATIENT_NAME_MISMATCH"]`, `confidence_score = 1.0`. Routes to `save_to_db`.

---

### 3.7 Node 3b — `validate_documents` (`agents/validate_documents.py`)

**Purpose:** Verify that the submitted document types satisfy the policy's requirements for the claimed category.

**Mechanism:** Pure Python. Reads `policy_terms.json` (already in memory via `@lru_cache`) to get `document_requirements[claim_category]` — a list of required classified types. Compares the `classified_type` of each extracted document against that list.

This check requires no LLM. Document type requirements are a deterministic set-membership test — either the classified type is in the required list or it is not. Using Gemini here would add latency, consume quota, and introduce nondeterminism in a decision that is entirely mechanical.

**On failure:** Returns `validation_passed = False`, `validation_error` (with `what_was_uploaded` and `what_is_required` fields for member-facing error messages), and routes to `END` — no DB write. The error message names the exact document types found and the exact types required.

**On pass:** Returns `validation_passed = True` and routes to `adjudicate_claim`.

---

### 3.8 Node 4 — `adjudicate_claim` (`agents/adjudicate.py`)

**Purpose:** Apply policy rules, detect fraud signals, compute the financial outcome, and produce the final claim decision — in a single Gemini call.

**Why a single call:** The adjudication Gemini call receives the full policy context, extracted document content, member claim history, and YTD spend, and must reason across all of them simultaneously. Breaking this into separate Python policy-check and Gemini explanation nodes would require Python string matching for exclusion conditions — which fails for semantically equivalent phrasings ("herniation" vs "hernia"). Gemini reasons about clinical intent; Python if-else matches strings. A single call also halves API quota versus two separate calls. Full rationale in `design_decisions.md §5`.

**Input construction:**

1. `get_policy_context(member_id, claim_category)` (`services/policy.py`) returns a filtered slice of `policy_terms.json`: the relevant coverage category, sub-limits, co-pay rules, waiting periods, exclusions, network hospitals, and the member record. Sending only the relevant slice reduces prompt token count and focuses Gemini's attention.
2. Claim details: member ID, treatment date, category, claimed amount, hospital name, YTD spend, prior claims history (formatted as a numbered list for fraud detection).
3. Extracted document content: formatted as a readable document summary per file.

**Structured output schema** (`_ClaimDecision`): `decision`, `approved_amount`, `rejection_reasons[]` (enumerated), `rejection_messages[]`, `decision_reason`, `confidence_score`, `warnings[]`, `fraud_signals[]`, and full financial calculation breakdown (`eligible_base`, `is_network_hospital`, `network_discount_percent`, `after_discount`, `copay_percent`, `copay_amount`). Dental claims include `dental_approved_items[]` and `dental_rejected_items[]` with per-item reasons.

**Confidence gate (Python, post-Gemini):**

| `confidence_score` | `APPROVED` / `PARTIAL` result | `REJECTED` / `MANUAL_REVIEW` result |
|---|---|---|
| ≥ 0.75 | Honoured as-is | Honoured as-is |
| 0.50 – 0.74 | Overridden to `MANUAL_REVIEW` | Honoured as-is |
| < 0.50 | Overridden to `REJECTED` | Honoured as-is |

The confidence gate prevents Gemini from approving claims when it is uncertain. REJECTED and MANUAL_REVIEW decisions are always honoured regardless of confidence — low confidence never auto-approves.

**Failure paths:**

- `simulate_component_failure = true` in the request (TC011 test path): Gemini is skipped. Returns `APPROVED` at confidence 0.60 with a manual review note in `decision_reason`. This is the assignment's graceful degradation test.
- Policy file load failure: `_graceful_pass()` → `MANUAL_REVIEW`, confidence 0.50.
- Gemini call failure (all cascade models exhausted): `_graceful_pass()` → `MANUAL_REVIEW`, confidence 0.50.

---

### 3.9 Node 5 — `save_to_db` (`agents/save_to_db.py`)

**Purpose:** Write the claim record to PostgreSQL. The final gate before a decision is delivered to the caller.

**Retry logic:** Up to 3 attempts with 1-second and 2-second delays between attempts. Transient failures (network hiccup, connection timeout, brief DB unavailability) resolve on retry.

**On total failure:** Adds `"save_to_db"` to `failed_components`. `process_claim()` detects this and raises HTTP 503 — the claim decision is **not** returned to the caller. Returning a decision without a DB record would create an irreconcilable inconsistency: the member believes the claim is decided; the company has no record. HTTP 503 instructs the member to resubmit.

**On success:** The `claims` table row contains: `claim_id`, `member_id`, `claim_category`, `decision`, `approved_amount`, `confidence_score`, `decision_reason`, `rejection_reasons[]`, `failed_components[]`, and `trace` (JSONB — the full per-node state snapshot).

**Dead Letter Queue:** `NoOpDLQ.publish()` (`services/dead_letter.py`) is called when a claim fails to save. Currently a stub that logs to the error logger. In production this would publish the failed claim payload to a message queue (SQS, Pub/Sub) for manual recovery.

---

### 3.10 LLM Service (`services/llm.py`)

**Interface:** `LLMService` ABC with a single async method:

```python
async def structured_call(
    prompt: str,
    output_schema: Type[BaseModel],
    *,
    content_blocks: list[dict] | None = None,
) -> BaseModel
```

All agents `await` this method. The concrete provider (`GeminiService`) is resolved via `get_llm_service(use_case)`. Adding a new provider (OpenAI, Anthropic) requires implementing `LLMService` and registering it in `_PROVIDERS`.

**`GeminiService`** uses LangChain's `ChatGoogleGenerativeAI` with `await llm.ainvoke(messages)` — the network call to Gemini is fully async, releasing the event loop to serve other requests during the 2–10 second API round-trip. `with_structured_output(schema, method="json_schema")` enforces schema compliance — the model must return a conforming JSON object; no post-hoc parsing.

**Model cascade:** Two cascade lists, one per use case:

| Use case | Primary | Fallbacks |
|---|---|---|
| Extraction | gemini-3.1-flash-lite | gemini-2.5-flash-lite → ... → gemini-2.0-flash |
| Adjudication | gemini-3.1-flash-lite | gemini-2.5-flash-lite → ... → gemini-2.0-flash |

On HTTP 429 (rate limit / quota exhausted), the exhausted model is added to a **class-level dict** with a timestamp. No lock is needed — asyncio is single-threaded and there is no `await` between the membership check and the dict write, so no concurrent coroutine can interleave. Subsequent cascade attempts skip exhausted models automatically. Models are re-admitted after 24 hours (aligning with Gemini's daily quota reset). Non-429 errors propagate immediately without retrying.

---

### 3.11 Policy Service (`services/policy.py`)

Policy terms (`backend/data/policy_terms.json`) are loaded once at startup by `load_policy()` and held in memory via `@lru_cache`. The cached object is a parsed `PolicyData` Pydantic model.

`get_policy_context(member_id, claim_category)` returns a filtered dict: the relevant coverage category data, the member record, and the top-level fraud thresholds. This is the only slice of policy data sent to Gemini — sending the full policy file in every prompt would waste tokens on coverage categories irrelevant to the claim.

Policy is intentionally stored in a file rather than a database. The single-policy, single-company scope makes a DB table containing one row an over-engineering. Policy changes are infrequent, should trigger a redeploy and test run, and must be version-controlled — all three properties are satisfied by a committed JSON file that cannot be edited without going through git. See `design_decisions.md §3`.

---

### 3.12 Database (`PostgreSQL + asyncpg + SQLAlchemy async + Alembic`)

Two tables: `claims` and `claim_documents`. `claims` holds the pipeline decision and the full `trace` JSONB column. `claim_documents` holds per-document metadata (file path, classified type, MIME type).

**Async layer** (`models/database.py`): a single `create_async_engine` using the `asyncpg` driver (`postgresql+asyncpg://...`). `AsyncSessionLocal` is an `async_sessionmaker` bound to this engine. `get_async_db()` is a FastAPI `AsyncGenerator` dependency — it opens and closes an `AsyncSession` per request via `async with`. There is no sync engine in app code.

`claim_repository.py` provides two async read operations: `get_claim_by_id()` and `list_member_claims()`. Both use `select(Claim).options(selectinload(Claim.documents))` — `selectinload` eagerly loads the `documents` relationship in a second query, which is required in async SQLAlchemy because lazy loading is not supported without an active sync context. The pipeline never queries the DB during processing — only `save_to_db` writes. This keeps the pipeline stateless and unit-testable without a DB session fixture.

Migrations are managed by **Alembic** (`backend/migrations/`). `migrations/env.py` uses `create_async_engine` + `await connection.run_sync(_do_run_migrations)` — Alembic's internal migration runner is sync, but the connection is async; `run_sync` bridges the two. Schema changes are tracked in `backend/migrations/versions/`.

---

### 3.13 Observability

**LangSmith:** The LangGraph pipeline emits per-node traces automatically when `LANGCHAIN_API_KEY` and `LANGCHAIN_PROJECT` environment variables are set. Each node's input state and output updates are recorded. LangSmith provides the canonical reconstruction path for any claim.

**Structured logging:** Two loggers — `application_logger` (INFO, normal flow events) and `error_logger` (WARNING / ERROR, failures and overrides). Every significant state transition is logged with `claim_id`, `member_id`, and the relevant state fields. Log format is JSON-compatible for aggregation.

**`trace` JSONB column:** Every claim in the DB has a per-node trace snapshot. This is the offline equivalent of LangSmith — it stores which nodes ran, what each returned, what the confidence gate did, and the full financial calculation breakdown. The Streamlit trace panel renders this directly.

---

## 4. Request Lifecycle (Full Happy Path)

```
POST /api/claims
  │
  ├─ Pydantic validation (ClaimSubmitRequest)
  ├─ await asyncio.to_thread(_persist_documents) — save raw bytes to disk (non-blocking)
  ├─ Build ClaimState {request, claim_id, saved_files, failed_components=[], trace={}}
  │
  ▼ await pipeline.ainvoke()
  │
  ├─ blur_gate
  │   └─ OpenCV Laplacian variance check on each image
  │   └─ PDF → SKIP  |  variance ≥ 80 → PASS  |  variance < 80 → FAIL → END (no DB)
  │
  ├─ extract_documents
  │   └─ Single Gemini Vision call: all docs as multimodal content blocks
  │   └─ Returns: classified_type[], extracted fields[], patient_name_consistent
  │   └─ Failure → MANUAL_REVIEW, confidence=0.30 → save_to_db
  │
  ├─ [patient_name_consistent=False] → reject_patient_mismatch → save_to_db
  │
  ├─ validate_documents
  │   └─ Python: classified_types vs policy document_requirements[category]
  │   └─ Mismatch → DOCUMENT_VALIDATION_FAILED → END (no DB)
  │
  ├─ adjudicate_claim
  │   └─ get_policy_context() → filtered policy slice
  │   └─ Single Gemini call: policy + fraud + financial calc + decision
  │   └─ Confidence gate: < 0.50 → REJECTED  |  0.50–0.74 → MANUAL_REVIEW  |  ≥ 0.75 → honour
  │   └─ Failure → _graceful_pass → MANUAL_REVIEW, confidence=0.50
  │
  └─ save_to_db
      └─ 3 retries (1s, 2s delays)
      └─ Success → write claims + claim_documents rows
      └─ Failure → DLQ.publish(), add "save_to_db" to failed_components
  │
  ▼ process_claim()
  ├─ "save_to_db" in failed_components → HTTP 503 (blocked — no decision without DB record)
  └─ _map_state_to_response() → ClaimResponse or DocumentValidationError
```

---

## 5. What Was Considered and Rejected

### Orchestration: n8n / low-code tools

Rejected in favour of LangGraph. LangGraph nodes are plain Python functions — importable, independently testable with `pytest`, and statically typed via `ClaimState`. n8n nodes are visual UI elements with no native unit testing support, untyped JSON between nodes, and no LangSmith integration. The assignment requires tests for every significant component; n8n cannot satisfy this. See `design_decisions.md §1`.

### Document extraction: EasyOCR + text LLM (two-stage pipeline)

Rejected in favour of Gemini Vision (single-stage). EasyOCR discards spatial layout, produces flat text that cannot distinguish which line-item description belongs to which amount on an itemised bill, performs poorly on handwriting, and requires `poppler` for PDFs (a system binary Render's free tier does not support). Gemini handles all of this natively in a single call. See `design_decisions.md §4`.

### Multi-call adjudication (separate policy check, fraud check, decision nodes)

Rejected in favour of a single Gemini call. Three separate calls would triple the per-claim quota cost. Python string matching for exclusion conditions is brittle — "herniation" and "hernia" are the same exclusion; Python cannot reason about this without an LLM. Fewer nodes means a simpler state schema. See `design_decisions.md §5`.

### Policy in PostgreSQL (deferred, not rejected)

JSON at startup is the correct choice for this assignment's scope: one policy, one company, no mid-year amendments. A DB table containing one row adds a migration, a seeder, a query, and a cache layer with no benefit at this scale. Tying policy changes to a redeploy is a safety property — it prevents silent production changes with no deployment event to trace.

The right long-term design is DB-backed. When Plum onboards multiple corporate clients (each with a different policy), or needs mid-year regulatory amendments without a redeploy, `policy_terms.json` cannot serve that use case. The extension path is: a `policies` table keyed by `policy_id`, queried at startup per-tenant and cached with a short TTL, with effective-date columns for point-in-time reconstruction. `load_policy()` and `get_policy_context()` in `services/policy.py` are already the isolation point — the rest of the pipeline reads policy only through those two functions and would require no changes. See `design_decisions.md §3`.

### Patient name check as a Python node after extraction

Rejected in favour of checking inside the extraction call. Adding a `patient_name_consistent` field to the extraction output schema costs zero additional API calls — Gemini has already read all documents. Python string equality would reject valid submissions where a prescription says "R. Kumar" and a bill says "Rajesh Kumar". Gemini correctly identifies these as the same person. See `design_decisions.md §6`.

### Database locking (pessimistic or optimistic)

Not implemented in the current design. The pipeline never reads from the DB during processing — fraud context (YTD claims, claims history) is supplied by the frontend, so there is no DB read to lock. Claims are insert-only. The race condition (two simultaneous claims for the same member both passing the annual limit check) cannot be triggered in the current design. Locking becomes necessary when `_fetch_member_claims_context()` is wired to query the DB instead of trusting the frontend payload. See `design_decisions.md §8`.

---

## 6. Failure Handling Summary

Every failure is contained at the node that experiences it. The pipeline always terminates with a decision.

| Failure | Node | Behaviour |
|---|---|---|
| Image too blurry (variance < 80) | blur_gate | Hard stop. DOCUMENT_UNREADABLE + filename. No DB write. |
| No image data received | blur_gate | Hard stop. DOCUMENT_UNREADABLE. No DB write. |
| OpenCV error on one image | blur_gate | That image skipped. Pipeline continues. |
| Gemini call fails (extraction) | extract_documents | MANUAL_REVIEW, confidence=0.30. Routes to save_to_db directly. |
| Wrong document types | validate_documents | Hard stop. DOCUMENT_VALIDATION_FAILED with what_was_uploaded / what_is_required. No DB write. |
| simulate_component_failure flag | adjudicate_claim | APPROVED, confidence=0.60, manual review note. (TC011 test path.) |
| Policy file load fails | adjudicate_claim | _graceful_pass → MANUAL_REVIEW, confidence=0.50. |
| Gemini call fails (adjudication) | adjudicate_claim | _graceful_pass → MANUAL_REVIEW, confidence=0.50. |
| Gemini confidence < 0.50 on APPROVED/PARTIAL | adjudicate_claim | Confidence gate overrides to REJECTED. |
| Gemini confidence 0.50–0.74 on APPROVED/PARTIAL | adjudicate_claim | Confidence gate overrides to MANUAL_REVIEW. |
| DB write fails (all 3 retries exhausted) | save_to_db | DLQ stub logs. process_claim() returns HTTP 503. No decision delivered. |

The invariant: **a claim decision is never delivered to the caller without a corresponding DB record.** If `save_to_db` fails, the response is blocked and the member is asked to resubmit.

---

## 7. Limitations of the Current Design

### 7.1 Synchronous request-response model

The pipeline runs fully async — `await pipeline.ainvoke()` releases the event loop during every Gemini API call and every PostgreSQL write, so other requests are served concurrently during I/O. The event loop is never blocked.

The remaining constraint is the request-response model itself: the HTTP connection stays open for the full pipeline duration (typically 5–15 seconds depending on Gemini latency). The member's browser or the Streamlit frontend waits for that entire window. Under high concurrency, open connections accumulate even though the event loop is idle during I/O.

**Mitigation path:** Move to an async task queue model. The API accepts the submission, enqueues a pipeline task, and returns HTTP 202 with a `claim_id`. The client polls `GET /api/claims/{id}` for the decision. This decouples connection lifetime from LLM latency and allows the worker pool to scale independently of the API tier.

### 7.2 No request concurrency handling

All LangGraph state is in-process. There is no per-member serialisation. Two simultaneous claims for the same member will both pass the annual limit check if both read a stale YTD value from the frontend payload. See §5 above (DB locking) and `design_decisions.md §7 and §8`.

**Mitigation path:** Wire `_fetch_member_claims_context()` to query the DB and add pessimistic locking (`SELECT ... FOR UPDATE`) or `SERIALIZABLE` isolation on the member's claims rows.

### 7.3 Local file storage

Document files are saved to Render's local disk. Render disks are ephemeral — a service redeploy wipes them. Files saved to disk are not accessible across service replicas.

**Mitigation path:** Replace `file_storage.py` with an object store (GCS, S3). The `url` field in `claim_documents` already assumes a URL — switching storage backends requires only changing `save_document()` and `get_file_url()`.

### 7.4 Fraud context frontend-supplied vs DB-queried

`ytd_claims_amount` and `claims_history` are embedded in the submission payload by the Streamlit frontend. A caller could manipulate these values to make a repeat claim appear to be a first-time submission. In production, these values must be authoritative and must come from the DB.

**Mitigation path:** `_fetch_member_claims_context()` in `claim_processor.py` is the designated extension point. It is currently a stub returning an empty list. Wiring it to query `claim_repository.py` and overriding the frontend-supplied values before building `ClaimState` is a one-function change.

### 7.5 Dead Letter Queue is a stub

`NoOpDLQ.publish()` logs the failed claim payload and does nothing else. A production system needs a durable message queue so that claims that fail DB write can be recovered and retried without losing the LLM extraction and adjudication results.

### 7.6 Single policy, single tenant

`load_policy()` and `get_policy_context()` are designed for one policy file (`PLUM_GHI_2024`). This is intentional for the assignment scope. The production path is a `policies` table in PostgreSQL, keyed by `policy_id`, with effective-date columns for point-in-time reconstruction. The isolation is already in place — the entire pipeline reads policy exclusively through `load_policy()` and `get_policy_context()` in `services/policy.py`. Switching from file to DB requires changing those two functions only; no pipeline node changes.

---

## 8. Scaling to 10x Load

Current scale: 75,000 claims/year ≈ 8 claims/hour. 10x: 750,000/year ≈ 85 claims/hour. That is not a throughput problem — it is an architectural pattern problem. At 10x, the synchronous, single-threaded request model becomes the bottleneck.

### Phase 1 — Task queue decoupling (handles up to ~50x current load)

The pipeline already runs fully async — all LLM calls and DB writes are non-blocking, and concurrent requests are served during I/O. The remaining bottleneck at scale is the synchronous request-response model: each HTTP connection stays open for the full pipeline duration.

The next step is a task queue (Celery + Redis or GCP Cloud Tasks). The API accepts the submission, enqueues a task, and returns HTTP 202 with a `claim_id`. The client polls `GET /api/claims/{id}` for the decision. Workers run the existing async pipeline — no changes to nodes or LLM calls are required. Worker processes can be horizontally scaled independently of the API tier. Each worker holds its own `@lru_cache` policy object — no shared state.

### Phase 2 — LLM throughput (handles Gemini rate limits at scale)

The model cascade in `GeminiService` already handles free-tier rate limits by falling back to lower-priority models. At production scale, this becomes a paid-tier quota management problem:

- Replace the Google AI Studio free tier with Vertex AI (per-project quota, no 250 RPM global cap).
- The `GeminiService` cascade is already abstracted behind `LLMService` — switching to a Vertex AI client requires a new `_invoke()` implementation only.
- For extremely high throughput, split extraction and adjudication into separate worker pools with separate quota allocations.

### Phase 3 — Database (handles write throughput)

The current PostgreSQL instance is a single Render-managed DB. At 10x, write throughput from concurrent claim insertions becomes a constraint.

- Add a **read replica** for `list_member_claims()` and `get_claim_by_id()` queries (currently on the primary).
- Add **connection pooling** (PgBouncer) to prevent connection exhaustion under concurrent worker load.
- Partition the `claims` table by `member_id` hash or by `created_at` range for query performance.

### Phase 4 — File storage

Replace local disk with object storage (GCS / S3) as described in §7.3. Object storage is inherently scalable and accessible across replicas.

### What does NOT need to change at 10x

- The LangGraph pipeline nodes themselves — they are stateless Python functions. They scale horizontally with the worker pool.
- The policy service — `@lru_cache` per process, zero DB calls. Each worker caches its own copy.
- The confidence gate and routing logic — pure Python, nanosecond latency.
- The structured output schema — Gemini enforces it; no parser changes required.

### 10x Architecture Summary

```
API tier (FastAPI, multiple replicas)
    │ HTTP 202 + claim_id
    ▼
Task queue (Redis / Cloud Tasks)
    │
    ▼
Worker pool (horizontally scaled)
    ├─ LangGraph pipeline (stateless per claim)
    ├─ Vertex AI Gemini (paid quota, per-project)
    └─ PostgreSQL (write primary + read replica + PgBouncer)

Client polls GET /api/claims/{claim_id} for decision.
```

The claim processing logic is unchanged. Only the deployment model (request-response → task queue), the LLM tier (free → paid Vertex AI), and the infrastructure topology change.
