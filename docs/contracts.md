# Component Contracts

This document defines the interface of every significant component in ClaimPilot. For each component: what it reads, what it produces, what errors it raises, and what invariants hold. These contracts are precise enough that any single component can be reimplemented independently without reading its source code.

---

## 1. Shared State — `ClaimState`

`ClaimState` (`pipeline/state.py`) is a `TypedDict` with `total=False`. All keys are optional at any point in the pipeline. LangGraph merges each node's return dict into the shared state — nodes never mutate state directly; they return a partial dict.

The orchestrator initialises the following keys before the first node runs:

| Key | Type | Initial value |
|---|---|---|
| `request` | `dict` | Serialised `ClaimSubmitRequest` (`model_dump(mode="json")`) |
| `claim_id` | `str` | `str(uuid.uuid4())` |
| `saved_files` | `list[dict]` | File records from `_persist_documents()` |
| `failed_components` | `list[str]` | `[]` |
| `trace` | `dict` | `{}` |

Full state field reference:

| Key | Type | Set by |
|---|---|---|
| `request` | `dict` | orchestrator |
| `claim_id` | `str` | orchestrator |
| `saved_files` | `list[dict]` | orchestrator |
| `blur_check_passed` | `bool` | `blur_gate` |
| `blur_error` | `dict \| None` | `blur_gate` |
| `extracted_documents` | `list[dict]` | `extract_documents` |
| `extraction_complete` | `bool` | `extract_documents` |
| `extraction_failed` | `bool` | `extract_documents` |
| `validation_passed` | `bool` | `validate_documents` |
| `validation_error` | `dict \| None` | `validate_documents` |
| `patient_name_consistent` | `bool` | `extract_documents` |
| `patient_name_mismatch_details` | `str \| None` | `extract_documents` |
| `decision` | `str \| None` | `extract_documents` (failure path), `reject_patient_mismatch`, `adjudicate_claim` |
| `approved_amount` | `float \| None` | `extract_documents` (failure path), `reject_patient_mismatch`, `adjudicate_claim` |
| `confidence_score` | `float \| None` | `extract_documents` (failure path), `reject_patient_mismatch`, `adjudicate_claim` |
| `decision_reason` | `str \| None` | `extract_documents` (failure path), `reject_patient_mismatch`, `adjudicate_claim` |
| `rejection_reasons` | `list[str]` | `extract_documents` (failure path), `reject_patient_mismatch`, `adjudicate_claim` |
| `failed_components` | `list[str]` | Accumulated — any node can append; never reset mid-pipeline |
| `trace` | `dict[str, Any]` | Accumulated — each node merges its own key |

---

## 2. Schemas

### `ClaimSubmitRequest`

Request body for `POST /api/claims`. Validated by Pydantic before the pipeline runs.

| Field | Type | Required | Notes |
|---|---|---|---|
| `member_id` | `str` | yes | Must match a record in `policy_terms.json` for a non-MANUAL_REVIEW decision |
| `policy_id` | `str` | yes | Stored as-is; not validated against the policy file |
| `claim_category` | `str` | yes | Used to look up document requirements and coverage rules |
| `treatment_date` | `date` | yes | ISO 8601 (`YYYY-MM-DD`) |
| `claimed_amount` | `float` | yes | In INR |
| `documents` | `list[DocumentInput]` | yes | At least one element |
| `claims_history` | `list[ClaimsHistoryItem] \| None` | no | Passed to adjudication for fraud detection |
| `hospital_name` | `str \| None` | no | Used for network hospital discount check |
| `ytd_claims_amount` | `float \| None` | no | Year-to-date total paid; used for annual limit check |
| `simulate_component_failure` | `bool` | no | Default `False`. `True` skips Gemini adjudication and returns APPROVED at confidence 0.60 (TC011 path) |
| `source_channel` | `str` | no | Default `"WEB"`. Stored on the `Claim` row |

### `DocumentInput`

One element of `ClaimSubmitRequest.documents`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `file_name` | `str` | yes | Default `""` |
| `file_data` | `str \| None` | no | Base64-encoded file bytes. `None` in test mode |
| `mime_type` | `str \| None` | no | `"image/jpeg"`, `"image/png"`, or `"application/pdf"` |
| `document_type` | `str \| None` | no | User-declared label — not trusted by document validation |
| `file_id` | `str \| None` | no | Test mode only |
| `actual_type` | `str \| None` | no | Test mode: ground-truth document type |
| `content` | `dict \| None` | no | Test mode: pre-extracted content |
| `quality` | `str \| None` | no | Test mode: `"GOOD"` or `"UNREADABLE"` |
| `patient_name_on_doc` | `str \| None` | no | Test mode: for TC003 patient name mismatch scenario |

`effective_type() -> str | None` returns `document_type or actual_type`.

### `ClaimsHistoryItem`

| Field | Type | Required |
|---|---|---|
| `claim_id` | `str` | yes |
| `date` | `str` | yes |
| `amount` | `float` | yes |
| `provider` | `str \| None` | no |

### `ClaimResponse`

Returned by `POST /api/claims` when a decision is reached, and by both GET endpoints.

| Field | Type | Notes |
|---|---|---|
| `claim_id` | `str \| None` | UUID of the persisted claim |
| `decision` | `str \| None` | `"APPROVED"`, `"PARTIAL"`, `"REJECTED"`, or `"MANUAL_REVIEW"` |
| `approved_amount` | `float \| None` | In INR; `None` for REJECTED / MANUAL_REVIEW |
| `confidence_score` | `float \| None` | 0.0–1.0; Gemini's raw score (confidence gate does not alter this value) |
| `reason` | `str \| None` | Human-readable decision explanation |
| `rejection_reasons` | `list[str]` | Empty list when not rejected |
| `trace` | `dict` | Full per-node state snapshot |
| `failed_components` | `list[str]` | Names of components that failed during this claim |
| `documents` | `list[dict]` | `[{file_name, doc_type, url, mime_type}]` — only entries with a stored URL included |

### `DocumentValidationError`

Returned by `POST /api/claims` instead of `ClaimResponse` when a document problem is caught before adjudication. No DB record is written in this case.

| Field | Type | Notes |
|---|---|---|
| `claim_id` | `None` | Always `None` |
| `decision` | `None` | Always `None` |
| `error_type` | `str` | `"DOCUMENT_UNREADABLE"` or `"DOCUMENT_VALIDATION_FAILED"` |
| `message` | `str` | Specific, actionable message for the member |
| `what_was_uploaded` | `list[str] \| None` | Gemini-classified types of uploaded docs; set for `DOCUMENT_VALIDATION_FAILED` |
| `what_is_required` | `list[str] \| None` | Required types for the claim category; set for `DOCUMENT_VALIDATION_FAILED` |
| `unreadable_file` | `str \| None` | Filename of the blurry image; set for `DOCUMENT_UNREADABLE` |

### `ExtractedDocument`

Each element of `state["extracted_documents"]` is `ExtractedDocument.model_dump()`.

| Field | Type | Notes |
|---|---|---|
| `classified_type` | `str` | One of: `PRESCRIPTION`, `HOSPITAL_BILL`, `LAB_REPORT`, `PHARMACY_BILL`, `DENTAL_REPORT`, `DISCHARGE_SUMMARY`, `UNKNOWN` |
| `file_name` | `str` | |
| `patient_name` | `str \| None` | |
| `doctor_name` | `str \| None` | |
| `doctor_registration` | `str \| None` | |
| `date` | `str \| None` | String as extracted from the document |
| `diagnosis` | `str \| None` | |
| `medicines` | `list[str] \| None` | |
| `hospital_name` | `str \| None` | |
| `line_items` | `list[{description: str, amount: float}] \| None` | |
| `total` | `float \| None` | |
| `test_name` | `str \| None` | |
| `quality_flags` | `list[str]` | Default `[]` |
| `overall_confidence` | `float` | Default `1.0`; range 0.0–1.0 |

---

## 3. API Endpoints

All routes are registered under `/api`. The API layer raises HTTP exceptions; pipeline nodes do not.

### `POST /api/claims`

**Purpose:** Submit a claim for processing.  
**Request body:** `ClaimSubmitRequest` (JSON)  
**Response (HTTP 200):** `ClaimResponse` or `DocumentValidationError`

Returns `DocumentValidationError` when:
- Any image has Laplacian variance < 80.0 → `error_type: "DOCUMENT_UNREADABLE"`
- Extracted document types do not satisfy policy requirements → `error_type: "DOCUMENT_VALIDATION_FAILED"`

Returns `ClaimResponse` for all other outcomes, including `MANUAL_REVIEW` and partial failures.

**Error responses:**

| Status | Condition |
|---|---|
| 503 | `save_to_db` failed after all retries — no DB record exists; client must resubmit |
| 500 | Unhandled exception in the pipeline |
| 422 | Request body fails Pydantic validation |

### `GET /api/claims/{claim_id}`

**Purpose:** Retrieve the full decision and trace for a stored claim.  
**Path parameter:** `claim_id` — UUID string  
**Response (HTTP 200):** `ClaimResponse`

**Error responses:**

| Status | Condition |
|---|---|
| 404 | No claim found with that `claim_id` |

### `GET /api/claims`

**Purpose:** List claims, optionally filtered by member.  
**Query parameter:** `member_id` — optional string. Omit to return all claims.  
**Response (HTTP 200):** `list[dict]`

Each dict contains: `claim_id`, `member_id`, `claim_category`, `treatment_date`, `claimed_amount`, `submitted_at` (ISO 8601), `decision`, `approved_amount`, `confidence_score`, `reason`, `rejection_reasons`, `failed_components`, `trace`, `documents: [{file_name, doc_type, url}]`.

Maximum **100** records returned, ordered by `submitted_at` descending.

---

## 4. Pipeline Orchestrator — `process_claim`

**File:** `backend/src/services/claim_processor.py`  
**Signature:** `async def process_claim(request: ClaimSubmitRequest) -> ClaimResponse | DocumentValidationError`

**Execution steps:**
1. Generates `claim_id = str(uuid.uuid4())`.
2. Persists uploaded file bytes to disk via `_persist_documents()`, run in `asyncio.to_thread` (blocking I/O off the event loop).
3. Builds initial `ClaimState` and calls `await pipeline.ainvoke(initial_state)`.
4. If `"save_to_db"` is in `final_state["failed_components"]`, raises HTTP 503 — no response is returned to the client.
5. Maps `final_state` to `ClaimResponse` or `DocumentValidationError` via `_map_state_to_response()`.

**`saved_files` record structure** (one entry per document):
```
{
    "file_name": str,
    "doc_type": str,       # effective_type() from DocumentInput
    "file_path": str | None,   # relative path under uploads/; None on save failure or test mode
    "url":       str | None,   # download URL; None if file_path is None
    "mime_type": str | None,
}
```

**Raises:**
- `HTTPException(503)` — `save_to_db` failed; no DB record exists
- `HTTPException(500)` — unhandled exception raised by the pipeline

---

## 5. Pipeline Routing

Three conditional routing functions decide which node runs next. Each reads only the keys listed.

| Router | Reads key(s) | Routes to |
|---|---|---|
| `_route_after_blur` | `blur_check_passed` | `False` → `END` (no DB write); missing or `True` → `extract_documents` |
| `_route_after_extraction` | `extraction_failed`, `patient_name_consistent` | `extraction_failed=True` → `save_to_db`; `patient_name_consistent=False` → `reject_patient_mismatch`; otherwise → `validate_documents` |
| `_route_after_validation` | `validation_passed` | `False` → `END` (no DB write); `True` → `adjudicate_claim` |

Fixed edges (unconditional):
- `reject_patient_mismatch` → `save_to_db`
- `adjudicate_claim` → `save_to_db`
- `save_to_db` → `END`

---

## 6. Node Contracts

Every node is a function `(state: ClaimState) -> dict`. Nodes never mutate `state` directly — they return a partial dict that LangGraph merges. Each node reads `state.get("trace", {})` and adds its own key before returning.

---

### Node 1 — `blur_gate`

**File:** `backend/src/agents/blur_gate.py`  
**Type:** sync (LangGraph wraps it via `asyncio.to_thread`)  
**Purpose:** Reject unreadable images before consuming any LLM quota.

**Reads from state:**

| Key | Notes |
|---|---|
| `request["documents"]` | List of `DocumentInput` dicts; each needs `file_name`, `mime_type`, `file_data` |
| `trace` | Accumulated; this node adds `trace["blur_gate"]` |

**Per-document processing rules (evaluated in submission order; first failure exits immediately):**

| Condition | Result | Outcome |
|---|---|---|
| `mime_type` does not start with `"image/"` | `SKIP` (reason: `"pdf"`) | Continue to next document |
| `file_data` is `None` or empty | `FAIL` (reason: `"no_data"`) | Return failure immediately |
| OpenCV raises during decode/analysis | `SKIP` (reason: `"opencv_error"`) | Continue to next document |
| Laplacian variance < **80.0** | `FAIL` | Return failure immediately |
| Laplacian variance ≥ 80.0 | `PASS` | Continue to next document |

**Returns on failure (first failing document):**

| Key | Value |
|---|---|
| `blur_check_passed` | `False` |
| `blur_error` | `{"error_type": "DOCUMENT_UNREADABLE", "message": str, "unreadable_file": str}` |
| `trace` | `{..., "blur_gate": {"result": "FAIL", "checks": list[dict]}}` |

`message` format: `"The {doc_type_hint} you uploaded ({file_name}) is too blurry to read. Please take a clearer photo and re-upload that document."`

**Returns when all images pass or are skipped:**

| Key | Value |
|---|---|
| `blur_check_passed` | `True` |
| `blur_error` | `None` |
| `trace` | `{..., "blur_gate": {"result": "PASS", "checks": list[dict]}}` |

**`checks` entry structures:**
- Pass: `{"file": str, "result": "PASS", "variance": float}`
- Skip: `{"file": str, "result": "SKIP", "reason": str}`
- Fail (variance): `{"file": str, "result": "FAIL", "variance": float, "threshold": 80.0}`
- Fail (no data): `{"file": str, "result": "FAIL", "reason": str}`

**Side effects:** None.  
**Never raises:** Yes — OpenCV exceptions are caught per-file and cause that file to be skipped.

---

### Node 2 — `extract_documents`

**File:** `backend/src/agents/extraction.py`  
**Type:** async  
**Purpose:** Single Gemini Vision call that classifies all documents and cross-checks patient name consistency across them.

**Reads from state:**

| Key | Notes |
|---|---|
| `request["documents"]` | All documents passed as multimodal content blocks in a single LLM call |
| `failed_components` | Propagated; `"extraction_agent"` appended on failure |
| `trace` | Accumulated; this node adds `trace["extraction"]` |

**LLM call:** One call to `get_llm_service("extraction").structured_call()`. Output schema: `_AllDocumentsExtraction` with `documents: list[_DocumentExtraction]`, `patient_name_consistent: bool`, `patient_name_mismatch_details: str | None`. If Gemini returns fewer documents than submitted, missing slots are padded with `classified_type="UNKNOWN"`, `confidence=0.0`. Excess results are truncated to match submission count.

**Returns on success:**

| Key | Value |
|---|---|
| `extracted_documents` | `list[dict]` — one `ExtractedDocument.model_dump()` per document (see §2) |
| `extraction_complete` | `True` |
| `extraction_failed` | `False` |
| `patient_name_consistent` | `bool` from Gemini |
| `patient_name_mismatch_details` | `str \| None` from Gemini |
| `failed_components` | Unchanged |
| `trace["extraction"]` | `{"agent": "extraction", "single_gemini_call": True, "document_count": int, "patient_name_consistent": bool, "documents": list[dict]}` |

**Returns on LLM failure (any exception from `_call_llm`):**

| Key | Value |
|---|---|
| `extracted_documents` | `[]` |
| `extraction_complete` | `False` |
| `extraction_failed` | `True` |
| `patient_name_consistent` | `True` |
| `patient_name_mismatch_details` | `None` |
| `decision` | `"MANUAL_REVIEW"` |
| `approved_amount` | `None` |
| `confidence_score` | `0.30` |
| `decision_reason` | `"Document extraction failed — Gemini could not process the submitted documents. Claim routed to manual review."` |
| `rejection_reasons` | `[]` |
| `failed_components` | Original + `["extraction_agent"]` |
| `trace["extraction"]` | `{..., "error": str, "documents": list[dict with error]}` |

**Side effects:** None.  
**Never raises:** Yes — all LLM exceptions are caught and the failure path is taken.

---

### Node 3a — `reject_patient_mismatch`

**File:** `backend/src/agents/patient_name_check.py`  
**Type:** sync  
**Purpose:** Emit a deterministic REJECTED decision when Gemini detected cross-document patient name inconsistency during extraction.

**Reads from state:**

| Key | Notes |
|---|---|
| `patient_name_mismatch_details` | Used in `decision_reason`. Defaults to `"Patient names differ across documents."` if absent |
| `failed_components` | Propagated unchanged |
| `trace` | Accumulated; this node adds `trace["patient_name_check"]` |

**Returns (always the same shape):**

| Key | Value |
|---|---|
| `decision` | `"REJECTED"` |
| `approved_amount` | `None` |
| `confidence_score` | `1.0` |
| `decision_reason` | `"Patient name mismatch detected: {details}"` |
| `rejection_reasons` | `["PATIENT_NAME_MISMATCH"]` |
| `failed_components` | Unchanged |
| `trace["patient_name_check"]` | `{"result": "FAIL", "details": str}` |

**Side effects:** None.  
**Never raises:** Yes.

---

### Node 3b — `validate_documents`

**File:** `backend/src/agents/validate_documents.py`  
**Type:** sync  
**Purpose:** Verify that the document types Gemini classified satisfy the policy requirements for the claim category. Validates against Gemini-classified types — not the client-declared labels.

**Reads from state:**

| Key | Notes |
|---|---|
| `request["claim_category"]` | Used to look up `policy.document_requirements[category.upper()]` |
| `extracted_documents` | Uses `classified_type` field from each dict |
| `trace` | Accumulated; this node adds `trace["document_validation"]` |

**Reads from policy (via `load_policy()`):** `document_requirements[claim_category.upper()]` → `{"required": list[str], "optional": list[str]}`. Returns `{"required": [], "optional": []}` if category not found.

**Validation logic:**
- `classified_types = [doc["classified_type"] for doc in extracted_documents]`
- `missing_types = [r for r in required if r not in classified_types]`
- `"UNKNOWN"` documents never satisfy a required type.
- If `missing_types` is non-empty → validation fails.

**Returns on pass:**

| Key | Value |
|---|---|
| `validation_passed` | `True` |
| `validation_error` | `None` |
| `trace["document_validation"]` | `{"agent": "validate_documents", "claim_category": str, "required_types": list, "classified_types": list, "result": "PASS"}` |

**Returns on fail:**

| Key | Value |
|---|---|
| `validation_passed` | `False` |
| `validation_error` | `{"error_type": "DOCUMENT_VALIDATION_FAILED", "message": str, "what_was_uploaded": list[str], "what_is_required": list[str]}` |
| `trace["document_validation"]` | `{..., "result": "FAIL", "missing_types": list[str]}` |

`message` format: `"You uploaded: {classified_types joined}. A {claim_category} claim requires: {required_types joined}. Missing: {missing_types joined}. Please upload the missing document and resubmit."`

**Side effects:** None.  
**Raises:** Propagates any exception from `load_policy()` (`FileNotFoundError`, `json.JSONDecodeError`, or `OSError`). The orchestrator catches this as an unhandled pipeline exception and returns HTTP 500.

---

### Node 4 — `adjudicate_claim`

**File:** `backend/src/agents/adjudicate.py`  
**Type:** async  
**Purpose:** Single Gemini call that evaluates policy eligibility, detects fraud, computes financials, and produces a decision. A Python confidence gate post-processes the result.

**Reads from state:**

| Key | Notes |
|---|---|
| `request["member_id"]` | Policy context lookup and prompt |
| `request["claim_category"]` | Policy context lookup and prompt; uppercased before use |
| `request["claimed_amount"]` | Financial baseline; cast to `float` |
| `request["treatment_date"]` | Waiting period check |
| `request["hospital_name"]` | Network hospital discount check |
| `request["ytd_claims_amount"]` | Annual limit check; `None` treated as 0 |
| `request["claims_history"]` | Fraud detection input; `None` treated as `[]` |
| `request["simulate_component_failure"]` | `True` → skip LLM entirely (TC011 path) |
| `extracted_documents` | Formatted as text and injected into the adjudication prompt |
| `failed_components` | Propagated; may append `"policy_check"` or `"adjudicate"` |
| `trace` | Accumulated; this node adds `trace["adjudicate"]` |

**Simulated failure path (`simulate_component_failure=True`):**  
No LLM call. Returns immediately with `decision="APPROVED"`, `approved_amount=claimed_amount`, `confidence_score=0.60`, and appends `"policy_check"` to `failed_components`.

**LLM call:** One call to `get_llm_service("adjudication").structured_call()` with a text-only prompt containing: policy context JSON, claim details, claims history, and formatted extracted documents. Output schema: `_ClaimDecision`.

**Valid `rejection_reasons` values (from `_ClaimDecision` schema):**

| Code | Meaning |
|---|---|
| `MEMBER_NOT_FOUND` | `member_id` not in policy roster |
| `PATIENT_NAME_MISMATCH` | Names inconsistent (secondary check in adjudication) |
| `INITIAL_WAITING_PERIOD` | Member has not served initial waiting period |
| `EXCLUDED_CONDITION` | Condition or treatment is in policy exclusions |
| `WAITING_PERIOD` | Condition-specific waiting period not served |
| `PRE_AUTH_MISSING` | Pre-authorisation required but not provided |
| `PER_CLAIM_EXCEEDED` | Claim amount exceeds per-claim sub-limit |
| `ANNUAL_LIMIT_EXHAUSTED` | Annual coverage limit already consumed |

**Confidence gate** (applied after LLM call; only APPROVED and PARTIAL decisions are subject to override):

| Gemini decision | Confidence | Final decision | `approved_amount` |
|---|---|---|---|
| `APPROVED` or `PARTIAL` | ≥ 0.75 | Honoured as-is | As returned by Gemini |
| `APPROVED` or `PARTIAL` | 0.50 ≤ x < 0.75 | `MANUAL_REVIEW` | `None` |
| `APPROVED` or `PARTIAL` | < 0.50 | `REJECTED` | `None` |
| `REJECTED` or `MANUAL_REVIEW` | Any | Always honoured | As returned by Gemini |

`confidence_score` in the returned state is always Gemini's raw score — the gate does not alter it.

**Returns on success:**

| Key | Value |
|---|---|
| `decision` | Final decision after confidence gate |
| `approved_amount` | `float \| None` |
| `confidence_score` | Gemini's raw score (0.0–1.0) |
| `decision_reason` | Override explanation if gate triggered; otherwise Gemini's `decision_reason` |
| `rejection_reasons` | `list[str]` from Gemini |
| `failed_components` | Propagated unchanged |
| `trace["adjudicate"]` | Full calculation breakdown (see below) |

**`trace["adjudicate"]` structure:**
```
{
    "decision": str,
    "gemini_decision": str | None,        # original Gemini decision; only set if gate overrode it
    "confidence_override": str | None,    # explanation string if gate overrode
    "approved_amount": float | None,
    "confidence_score": float,
    "rejection_reasons": list[str],
    "fraud_signals": list[str],
    "eligibility_date": str | None,
    "warnings": list[str],
    "calculation": {
        "claimed_amount": float,
        "eligible_base": float,
        "is_network_hospital": bool,
        "network_discount_percent": float,
        "network_discount_amount": float,
        "after_discount": float,
        "copay_percent": float,
        "copay_amount": float,
        "final_approved": float,
    },
    "dental_approved": list[{"description": str, "amount": float, "reason": str | None}],
    "dental_rejected": list[{"description": str, "amount": float, "reason": str | None}],
}
```

**Graceful pass** (on policy load failure OR LLM exception — both produce identical output):

| Key | Value |
|---|---|
| `decision` | `"MANUAL_REVIEW"` |
| `approved_amount` | `None` |
| `confidence_score` | `0.50` |
| `decision_reason` | `"Adjudication unavailable ({reason}) — routed to manual review."` |
| `rejection_reasons` | `[]` |
| `failed_components` | Original + `["adjudicate"]` |
| `trace["adjudicate"]` | `{"skipped": True, "reason": str}` |

**Side effects:** None.  
**Never raises:** Yes — all exceptions (policy load and LLM) are caught; graceful pass is taken.

---

### Node 5 — `save_to_db`

**File:** `backend/src/agents/save_to_db.py`  
**Type:** async  
**Purpose:** Persist the final `Claim` row and one `ClaimDocument` row per extracted document to PostgreSQL.

**Reads from state:**

| Key | Notes |
|---|---|
| `claim_id` | UUID string for `Claim.id` |
| `request["member_id"]` | |
| `request["policy_id"]` | |
| `request["claim_category"]` | |
| `request["treatment_date"]` | Parsed via `date.fromisoformat()`; falls back to `date.today()` on parse error |
| `request["claimed_amount"]` | |
| `request["source_channel"]` | Default `"WEB"` |
| `decision` | |
| `approved_amount` | |
| `confidence_score` | |
| `rejection_reasons` | |
| `decision_reason` | |
| `extracted_documents` | One `ClaimDocument` row created per element |
| `saved_files` | Used to map `file_name → file_path` for `ClaimDocument.file_path` |
| `failed_components` | Propagated; `"save_to_db"` appended on total failure |
| `trace` | Stored as JSONB in `Claim.trace`; this node adds `trace["save_to_db"]` |

**Retry policy:** 3 total attempts. Sleep **1 second** between attempt 1 and 2. Sleep **2 seconds** between attempt 2 and 3. No sleep after the final attempt.

**Returns on success (any of the 3 attempts):**

| Key | Value |
|---|---|
| `failed_components` | Unchanged |
| `trace["save_to_db"]` | `{"success": True, "claim_id": str}` |

**Returns after all 3 attempts fail:**

| Key | Value |
|---|---|
| `failed_components` | Original + `["save_to_db"]` |
| `trace["save_to_db"]` | `{"success": False, "attempts": 3, "error": str}` |

**Side effects on total failure:** Calls `get_dlq().publish(claim_id, state, error_str)`. Currently `NoOpDLQ` — logs only.

**Invariant:** If `"save_to_db"` is in `final_state["failed_components"]`, the orchestrator raises HTTP 503 and no response is returned to the client.

**Never raises:** Yes — all DB exceptions are caught per attempt; total failure appends to `failed_components`.

---

## 7. Service Contracts

### LLMService

**File:** `backend/src/services/llm.py`

Abstract base class for all LLM calls. All agents must call through this interface.

**Abstract method:**
```python
async def structured_call(
    prompt: str,
    output_schema: Type[BaseModel],
    *,
    chat_history: list[dict] | None = None,
    content_blocks: list[dict] | None = None,
) -> BaseModel
```

| Parameter | Type | Notes |
|---|---|---|
| `prompt` | `str` | Instruction text. If `content_blocks` is provided, prepended as the first text block |
| `output_schema` | `Type[BaseModel]` | Pydantic model the response must conform to |
| `chat_history` | `list[dict] \| None` | Optional prior turns: `[{"role": "user"\|"assistant", "content": str}]` |
| `content_blocks` | `list[dict] \| None` | Multimodal content — formats below |

**`content_blocks` element formats:**
```python
{"type": "text",  "text": str}
{"type": "image", "base64": str, "mime_type": "image/jpeg" | "image/png"}
{"type": "file",  "base64": str, "mime_type": "application/pdf"}
```

**Returns:** A validated Pydantic instance of `output_schema`.

**Raises:**
- Re-raises any non-429 exception immediately (no cascade retry).
- `RuntimeError("All models in cascade '{key}' exhausted: {models}")` if all cascade models are rate-limited.

### `GeminiService` (concrete implementation)

**Factory:** `get_llm_service(use_case: str = "adjudication") -> LLMService`

| `use_case` | Cascade used |
|---|---|
| `"extraction"` | `EXTRACTION_CASCADE` |
| `"adjudication"` (default) | `ADJUDICATION_CASCADE` |
| Any other string | Falls back to `ADJUDICATION_CASCADE` |

Both cascades contain the same 7 models in the same order:

```
gemini-3.1-flash-lite  →  gemini-2.5-flash-lite  →  gemini-2.0-flash-lite
→  gemini-3.5-flash  →  gemini-3.0-flash  →  gemini-2.5-flash  →  gemini-2.0-flash
```

**Rate-limit behaviour:**
- An HTTP 429 is detected if the error message contains `"429"`, `"resource has been exhausted"`, `"quota exceeded"`, or `"rate limit"` (case-insensitive).
- On 429: the model is added to a class-level `_exhausted_models` dict keyed by model name with timestamp. That model is skipped in all subsequent cascade calls across the entire process lifetime.
- Exhausted models recover automatically after **24 hours**.
- Non-429 exceptions are re-raised immediately without advancing the cascade.

All calls use `temperature=0`. Structured output is enforced via `with_structured_output(schema, method="json_schema")`.

---

### PolicyService

**File:** `backend/src/services/policy.py`

#### `load_policy() -> PolicyData`

Reads `backend/data/policy_terms.json` and returns a `PolicyData` instance.

**Cache:** `@lru_cache(maxsize=1)` — file is read once per process. A policy change requires a process restart.

**Raises:** `FileNotFoundError`, `json.JSONDecodeError`, or `OSError` if the file cannot be read or parsed.

**`PolicyData` attributes:**

| Attribute | Type |
|---|---|
| `policy_id` | `str` |
| `members` | `dict[str, MemberRecord]` keyed by `member_id` |
| `coverage` | `dict` |
| `opd_categories` | `dict` |
| `waiting_periods` | `dict` |
| `exclusions` | `dict` |
| `pre_authorization` | `dict` |
| `network_hospitals` | `list[str]` |
| `submission_rules` | `dict` |
| `document_requirements` | `dict` |
| `fraud_thresholds` | `dict` |

**`PolicyData` methods:**

| Method | Signature | Returns |
|---|---|---|
| `get_member` | `(member_id: str) -> MemberRecord \| None` | `None` if not found |
| `get_category_config` | `(category: str) -> dict \| None` | Looks up `opd_categories[category.lower()]`; `None` if not found |
| `get_document_requirements` | `(category: str) -> dict` | Looks up `document_requirements[category.upper()]`; returns `{"required": [], "optional": []}` if not found |
| `is_network_hospital` | `(hospital_name: str \| None) -> bool` | Case-insensitive substring match against `network_hospitals` list; `False` if `hospital_name` is `None` |

**`MemberRecord` attributes:** `member_id: str`, `name: str`, `join_date: str`, `relationship: str`, `primary_member_id: str | None`, `dependents: list[str]`.

#### `get_policy_context(member_id: str, claim_category: str) -> dict`

Returns a filtered subset of policy data for the adjudication prompt.

**Returns:**
```python
{
    "member": {"member_id": str, "name": str, "join_date": str, "relationship": str} | None,
    "coverage": dict,
    "claim_category": str,              # uppercased
    "claim_category_config": dict | None,
    "waiting_periods": dict,
    "exclusions": dict,
    "pre_authorization": dict,
    "network_hospitals": list[str],
    "fraud_thresholds": dict,
}
```

`member` is `None` if `member_id` is not in the policy roster. `claim_category_config` is `None` if `claim_category.lower()` is not in `opd_categories`.

**Raises:** Same as `load_policy()`.

---

### ClaimRepository

**File:** `backend/src/services/claim_repository.py`

#### `get_claim_by_id(claim_id: str, db: AsyncSession) -> ClaimResponse`

Fetches a `Claim` row by UUID with its `ClaimDocument` children (eager-loaded via `selectinload`).

**Raises:** `HTTPException(404)` if no claim with that ID exists.

#### `list_member_claims(member_id: str | None, db: AsyncSession) -> list[dict]`

Returns up to **100** claim dicts ordered by `submitted_at` descending. Filtered by `member_id` if provided; returns all claims if `None`.

Each dict contains: `claim_id`, `member_id`, `claim_category`, `treatment_date`, `claimed_amount`, `submitted_at` (ISO 8601 string), `decision`, `approved_amount`, `confidence_score`, `reason`, `rejection_reasons`, `failed_components`, `trace`, `documents: [{"file_name": str, "doc_type": str, "url": str | None}]`.

**Never raises** (other than unexpected DB errors that propagate as HTTP 500).

---

### DeadLetterQueue

**File:** `backend/src/services/dead_letter.py`

#### Abstract contract

```python
class DeadLetterQueue(ABC):
    def publish(self, claim_id: str, state: ClaimState, error: str) -> None: ...
```

Called by `save_to_db` after all DB write retries are exhausted. Implementations must be non-blocking and must not raise.

#### `NoOpDLQ` (current implementation)

Logs the failed `claim_id` and error string to `error_logger`. Does not persist anywhere.

Production replacement: implement `SQSDeadLetterQueue` or `RedisStreamDLQ` inheriting `DeadLetterQueue` and register it in `get_dlq()`.

#### Factory

```python
get_dlq() -> DeadLetterQueue   # currently always returns NoOpDLQ()
```

---

## 8. Database Models

### `Claim` (table: `claims`)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | `UUID` | No | Primary key; `uuid.uuid4()` |
| `member_id` | `String` | No | Indexed |
| `policy_id` | `String` | No | |
| `claim_category` | `String` | No | |
| `treatment_date` | `Date` | No | |
| `claimed_amount` | `Numeric(10, 2)` | No | |
| `submitted_at` | `DateTime` | No | Default `datetime.utcnow` |
| `decision` | `String` | Yes | |
| `approved_amount` | `Numeric(10, 2)` | Yes | |
| `confidence_score` | `Float` | Yes | |
| `rejection_reasons` | `JSONB` | Yes | Default `[]` |
| `decision_reason` | `Text` | Yes | |
| `trace` | `JSONB` | Yes | Full per-node state snapshot |
| `failed_components` | `JSONB` | Yes | Default `[]` |
| `source_channel` | `String` | Yes | Default `"WEB"` |

Relationship: `documents → list[ClaimDocument]` (cascade all, delete-orphan).

### `ClaimDocument` (table: `claim_documents`)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | `UUID` | No | Primary key; `uuid.uuid4()` |
| `claim_id` | `UUID` (FK → `claims.id`) | No | Indexed |
| `file_name` | `String` | No | |
| `document_type` | `String` | Yes | Gemini-classified type |
| `file_path` | `String` | Yes | Relative path under `uploads/`; `None` for test-mode docs |
| `extraction` | `JSONB` | Yes | All extracted fields except `file_name`, `classified_type`, `quality_flags`, `overall_confidence` |
| `quality_flags` | `JSONB` | Yes | Default `[]` |
| `confidence` | `Float` | Yes | Per-document extraction confidence (0.0–1.0) |
