# Design Decisions

Four architectural decisions made during ClaimPilot's design, with the reasoning behind each choice.

---

## 1. LangGraph vs n8n — Why LangGraph for the core pipeline

### What was considered

Both LangGraph and n8n can orchestrate multi-step workflows. n8n is a popular low-code automation tool already used at Plum for WhatsApp and email workflows. The question was whether to use it as the claims processing core.

### Why LangGraph was chosen

**Unit testing is a hard requirement.**
The assignment explicitly states every significant component must have tests. LangGraph nodes are plain Python functions — they take a typed state dict and return a dict of updates. Any node can be imported, called with a mock state, and its output asserted in pytest. n8n nodes are visual UI elements with no native unit testing support. Testing n8n logic requires running the full n8n instance and triggering webhook flows — there is no way to test an individual node in isolation.

**Typed contracts between agents.**
LangGraph carries a `ClaimState` TypedDict through the pipeline. Every agent reads from and writes to this shared, typed state. If an agent writes a field that doesn't exist in the state, the type checker catches it at development time. n8n passes untyped JSON between nodes — field names are stringly-typed, schema mismatches only surface at runtime, and there is no way to define or enforce a contract between nodes.

**Observability that matches the domain.**
LangGraph integrates natively with LangSmith, giving per-node traces: what state went in, what came out, how long each agent took, where confidence dropped. The `trace` JSONB column in PostgreSQL stores a copy of this for the UI. n8n has basic execution logs but no concept of per-field confidence, structured agent output, or a typed trace that downstream systems can read.

**Business logic belongs in Python, not JavaScript code nodes.**
The claims processing rules — co-pay calculations, waiting period date arithmetic, per-claim limit checks, network hospital discount ordering — are non-trivial logic. In LangGraph these are Python functions with full access to the standard library, Pydantic models, and type hints. In n8n, this logic would live in JavaScript code nodes or require external HTTP calls to a Python service, which defeats the purpose of using n8n as the processor.

**Conditional routing is first-class.**
LangGraph's conditional edges are typed routing functions: a Python function inspects the state and returns the name of the next node. Early exits for patient name mismatch, document validation failure, and blur gate — as well as the TC011 graceful degradation path — are all clean conditional edges. n8n's IF nodes work for simple true/false branches but are not designed for the kind of stateful, multi-signal routing that claims processing requires.

### Where n8n is the right tool

n8n is used as the **channel layer only** — receiving WhatsApp messages via Twilio, collecting document attachments, calling `POST /api/claims`, and sending the decision back to the member. This is exactly what n8n excels at: webhook ingestion, HTTP calls, and message routing. It has no claims logic and does not need to.

### Summary

| Concern | LangGraph | n8n |
|---------|-----------|-----|
| Unit testable | Yes — plain Python functions | No — visual nodes, no test runner |
| Typed state contracts | Yes — TypedDict + Pydantic | No — untyped JSON |
| LangSmith observability | Native | Not available |
| Business logic in Python | Yes | JavaScript code nodes or HTTP calls |
| Conditional routing | Typed routing functions | IF nodes (limited) |
| Right role in this system | Core pipeline | Channel layer (WhatsApp/email) |

---

## 2. Infrastructure as Code (render.yaml) vs Manual Dashboard Setup — Why IaC

### What was considered

Render supports two ways to set up infrastructure: clicking through the dashboard to create services manually, or committing a `render.yaml` file to the repo which Render reads on first connect to provision everything automatically.

### Why render.yaml was chosen

**Reproducibility.**
The entire infrastructure — two web services and a PostgreSQL database with all environment variable bindings — is defined in one file. Anyone who forks the repo and connects it to Render gets an identical environment. There is nothing to remember, no sequence of dashboard steps to follow, no opportunity for a misconfigured setting to cause a silent production bug.

**Version control.**
Infrastructure changes are tracked in git alongside the code changes that require them. When a new environment variable is added (e.g. `LANGSMITH_API_KEY`), the commit that adds it to `render.yaml` and `.env.example` is the same commit that adds the code that uses it. The git history answers "when did we add the DB?" and "what changed in the deployment config between these two versions?" without needing Render dashboard access.

**Disaster recovery.**
If the Render project is deleted or the account changes, recreating the full infrastructure is a `git push`. Without `render.yaml`, rebuilding requires reconstructing every setting from memory or documentation — and documentation of manual steps always drifts.

**No configuration drift.**
The most common infrastructure failure mode is when what is running in production silently diverges from what is documented. An environment variable is added through the dashboard during an incident, the docs are never updated, and six months later no one knows what it does or whether it is still needed. With `render.yaml`, the dashboard is not the source of truth — the file is.

**No extra tooling.**
`render.yaml` is native to Render. It requires no additional infrastructure tools, no Terraform state management, no cloud provider SDK. For a project this size, it provides all the benefits of IaC with none of the operational overhead.

### What manual setup would cost

A manually configured Render setup cannot be reviewed in a pull request. It cannot be diffed. It cannot be rolled back. It cannot be reproduced by a new team member without screen-sharing with someone who has dashboard access. For a demo project that may be re-evaluated or reproduced, this is an unacceptable single point of failure.

---

## 3. Policy Stored in DB vs JSON File at Startup — Why JSON at Startup

### What was considered

The policy terms (coverage limits, waiting periods, exclusions, co-pay percentages, network hospitals, document requirements) could be stored in a `policies` table in PostgreSQL and queried at runtime, or loaded from `backend/data/policy_terms.json` once at startup and cached in memory.

### Why JSON at startup was chosen

**Single policy, single company.**
This system processes claims for one policy: `PLUM_GHI_2024` for TechCorp Solutions. There is no multi-tenancy requirement. A database table that contains exactly one row provides no benefit over a file.

**Policy changes should trigger a redeploy.**
When policy terms change — a new waiting period, a new excluded condition, a change to the co-pay percentage — the system behaviour changes. Any change that alters how claims are decided warrants a code review, a test run, and a deployment. If policy is in the DB and can be changed live without a redeploy, a misconfigured policy record could silently approve claims that should be rejected or reject claims that should be approved, with no deployment event to trace back to. Tying policy changes to the deployment process is a safety property, not a limitation.

**Zero runtime overhead.**
`load_policy()` uses `@lru_cache` — the JSON is read from disk once on the first request and the parsed `PolicyData` object lives in memory for the lifetime of the process. Every subsequent policy lookup is a Python attribute access. A DB-backed policy would require a network round-trip on startup and potentially on every request if the cache were invalidated.

**Already version-controlled.**
`backend/data/policy_terms.json` is committed to the repo. Changes to policy terms appear in git diffs, can be reviewed in PRs, and are tied to specific commits. A DB record has none of this — changes are invisible to the code review process.

**Simpler.**
A DB-backed policy requires: a `policies` table, an Alembic migration, a seeder script to populate it, a service function to query it, and logic to cache it to avoid per-request DB calls. The JSON file approach requires: a file read and `@lru_cache`. All of this complexity, for a single-row table that changes only on deployment.

### When a DB would be the right choice

For a real production system serving multiple corporate clients, each with a different policy:

- **Multi-tenancy**: TechCorp has 10% co-pay on consultations; FinanceCorp has 20%. The policy loaded must match the `policy_id` in the claim request.
- **Mid-year amendments**: A regulator mandates a new exclusion effective next month. The DB allows this change without a code deployment.
- **Audit trail**: "What were the exact policy terms in effect when claim CLM-0481 was processed in November 2024?" — requires either a DB record with effective dates, or storing a policy snapshot in the claim's `trace` column. ClaimPilot does the latter: the `trace` JSONB on the `claims` table stores which policy checks ran and what values they used, giving a per-claim audit trail without a live policies table.

### Summary

| Concern | JSON at startup | DB-backed |
|---------|----------------|-----------|
| Single policy, single company | Correct fit | Overkill |
| Policy change safety | Tied to deployment (safe) | Can change live (risky) |
| Runtime overhead | Zero (lru_cache) | Network round-trip |
| Version control | Git-tracked | Invisible to code review |
| Multi-tenant support | No | Yes |
| Right for this assignment | Yes | No |

---

## 4. EasyOCR + AI vs Gemini Vision — Why Gemini end-to-end

### What was considered

A common OCR pipeline for document extraction is two-stage: run a dedicated OCR library (EasyOCR, Tesseract, PaddleOCR) to extract raw text from the image, then pass that text to a language model (GPT-4, Claude, Gemini text-only) to parse and structure it. The alternative is Gemini 2.5 Flash Vision, which does both in a single multimodal call.

### Why Gemini end-to-end was chosen

**One step, not two.**
EasyOCR + AI is a pipeline of two models with a lossy intermediate representation between them. Gemini processes the image directly and produces structured output in a single call. Fewer steps means fewer failure modes, fewer API calls, lower latency, and a simpler codebase.

**Information loss at the OCR step.**
EasyOCR outputs raw text — a flat sequence of characters. In doing so it discards the visual structure: which amount on a hospital bill belongs to which line item description, whether a number is a total or a subtotal, whether a stamp is covering another piece of text. Gemini processes the visual layout directly and uses spatial relationships to correctly associate fields. This matters enormously for itemised bills where TC006 (dental partial approval) requires distinguishing "Root Canal Treatment ₹8,000" from "Teeth Whitening ₹4,000" on the same document.

**Handwriting.**
EasyOCR is primarily trained on printed text. It performs poorly on handwritten prescriptions, which are extremely common in Indian medical practice — the sample documents guide notes this explicitly. Gemini 2.5 Flash is a multimodal model trained on diverse visual content including handwriting, and handles partially handwritten, rubber-stamped, and mixed-language documents significantly better.

**No system binaries for PDFs.**
EasyOCR works on images only. To process a PDF, the standard approach is pdf2image + poppler (a system binary) to convert each page to an image first. Render's free tier does not support arbitrary system packages. Gemini accepts PDFs natively via `mime_type='application/pdf'` — no conversion, no system dependencies, no poppler.

**Token-level field confidence via logprobs.**
EasyOCR produces character-level confidence scores for the OCR step, but these do not translate to confidence on the structured fields that the policy check agent needs. Gemini with `response_logprobs=True` returns token-level log probabilities for every token in the structured JSON output, which we convert to per-field confidence scores. This is more meaningful: a field confidence of 0.3 on `total_amount` directly signals that the policy check agent should treat that value cautiously, and the decision confidence formula penalises accordingly.

**Structured output in one pass.**
With EasyOCR + AI, the LLM receives raw text and must infer structure. With Gemini, `response_schema` is set to the appropriate Pydantic model (PrescriptionContent, HospitalBillContent, etc.) and Gemini returns a validated JSON object directly. The extraction agent does not need a separate parsing step.

**Quality flags in one pass.**
Gemini can detect rubber stamps over text, multilingual fields, partial documents, and document alterations in the same call that extracts the structured data. With EasyOCR + AI, detecting these would require additional post-processing logic or a second model call.

**Free tier, no GPU required.**
EasyOCR's accuracy on complex documents degrades significantly without a GPU. Render's free tier is CPU-only. Gemini 2.5 Flash on Google AI Studio is free (250 requests/day, 10 RPM, 250K TPM) and runs inference on Google's infrastructure — no GPU provisioning required.

### The one advantage EasyOCR has

EasyOCR runs entirely locally — no API call, no network latency, no rate limits, no API key. For a high-volume production system processing thousands of claims per minute, local OCR would be faster and cheaper than a per-call API. At the scale of this assignment (12 test cases, a demo), this advantage is not relevant.

### Summary

| Concern | EasyOCR + AI | Gemini Vision |
|---------|-------------|---------------|
| Steps to structured output | Two (OCR → LLM parse) | One |
| Visual layout preserved | No — flat text | Yes |
| Handwriting handling | Poor | Good |
| PDF support | Needs poppler (system binary) | Native |
| Field-level confidence | No clean mechanism | logprobs → per-field score |
| Structured output | LLM must infer from raw text | response_schema enforces it |
| Quality flag detection | Separate step | Same pass |
| GPU required | Yes for accuracy | No |
| Free tier | EasyOCR yes, LLM no | Yes (Google AI Studio) |
| Right for this assignment | No | Yes |

---

## 5. Single Gemini Call Adjudication — Why Policy + Fraud + Decision Is One Call

### What was considered

The original design had three separate LangGraph nodes after extraction: `policy_check` (Python), `fraud_check` (Python), and `make_decision` (Python that reads the first two and synthesises a decision). Alternatively, the entire adjudication could be delegated to a single Gemini call.

### Why a single Gemini call was chosen

**API quota is finite.**
Gemini AI Studio free tier allows 250 requests/day. The system makes one extraction call per submission. Adding a separate adjudication call doubles the quota cost per claim. A third call for explanation text would triple it. Collapsing all adjudication logic — policy eligibility, fraud detection, financial calculation, and the final decision — into a single call halves the per-claim cost.

**Gemini is better at ambiguity than Python.**
Python if-else logic applied a keyword match to detect exclusions and waiting period conditions. This is brittle: "herniation" is not "hernia", "obesity treatment" is not every mention of "obesity". Python string matching cannot reason about intent. Gemini can: it reads the clinical context, applies the exclusion rules semantically, and — critically — routes to MANUAL_REVIEW when it is uncertain rather than making a wrong call. A wrongly approved claim is a financial loss; a wrongly rejected claim harms the member. The ambiguity rule ("when in doubt, MANUAL_REVIEW") is expressible in a system prompt; it is not expressible in Python if-else logic.

**Fewer moving parts.**
Three Python nodes required shared state fields (`policy_check_result`, `fraud_check_result`) that existed only to carry intermediate results between nodes. Removing them simplifies `ClaimState`, reduces the surface area for bugs, and makes the pipeline easier to explain and test.

**The one thing Python still owns.**
The `simulate_component_failure` flag (TC011) is a Python guard in `adjudicate_claim` that bypasses Gemini entirely. This is intentional: testing graceful degradation of the adjudication component requires a way to force a failure without an actual API error.

### What was given up

Python's financial math is deterministic and auditable. Gemini's co-pay and discount calculations are correct but not provably so — if Gemini makes an arithmetic error, the trace will show the wrong number with no obvious signal. Mitigation: the trace stores all intermediate values (eligible_base, network_discount_percent, after_discount, copay_amount, final_approved) so any discrepancy is visible in the audit trail.

---

## 6. Patient Name Check in Extraction Agent — Why Not a Separate Node

### What was considered

Three options for cross-document patient name validation:
1. **Python node after extraction** — compare `patient_name` strings with case-insensitive equality
2. **Separate Gemini call** — ask the LLM whether names across documents belong to the same person
3. **Inside the extraction call** — add the check to the extraction prompt, get the result as part of the same response

### Why option 3 (extraction prompt) was chosen

**Zero extra API cost.**
The extraction agent already receives and reads all documents in a single call. The patient name comparison is a natural extension of that reading — Gemini already knows every `patient_name` it extracted. Adding `patient_name_consistent` and `patient_name_mismatch_details` to the extraction output schema costs no additional tokens beyond a few extra output fields.

**Gemini handles name variations correctly.**
Python string equality would reject a valid claim where the prescription says "R. Kumar" and the hospital bill says "Rajesh Kumar". These are the same person, written in two different formats. Gemini understands this; Python does not. The extraction prompt instructs Gemini to only flag names that clearly belong to different individuals — initials, titles, and minor spelling differences are not mismatches.

**Early exit saves the adjudication call.**
A mismatch detected at extraction routes to `reject_patient_mismatch` → `save_to_db` → END, bypassing the adjudication Gemini call entirely. A mismatch detected inside adjudication would still have consumed a Gemini call.

### Why validate_documents stayed as Python

Document type requirements (CONSULTATION needs PRESCRIPTION + HOSPITAL_BILL) are a deterministic list-membership check from `policy_terms.json`. There is no ambiguity to reason about — either the classified type is in the required list or it is not. Python is cheaper, instantaneous, and 100% reliable for this check. Moving it into Gemini would add no value and consume quota.
