# ClaimPilot

Automated health insurance claims processing system built for Plum. Accepts a claim submission (member details + medical documents) and produces a decision — **APPROVED**, **PARTIAL**, **REJECTED**, or **MANUAL_REVIEW** — with a full explanation, approved amount, and confidence score.

## Architecture

Six-node LangGraph pipeline with two Gemini calls per claim:

| Node | Type | Responsibility |
|---|---|---|
| `blur_gate` | OpenCV (local) | Reject blurry or missing images before spending API quota |
| `extract_documents` | **GEMINI CALL 1** | Classify each doc type, extract all fields, cross-check patient names across docs |
| `reject_patient_mismatch` | Python | Fast REJECTED path when names differ across documents |
| `validate_documents` | Python (no LLM) | Verify correct document types are present for the claim category |
| `adjudicate_claim` | **GEMINI CALL 2** | Policy eligibility + fraud detection + financial calculation + final decision in one call |
| `save_to_db` | Python | Persist claim + trace to PostgreSQL |

### Confidence gate (Python, post-adjudication)

| Confidence | Action |
|---|---|
| ≥ 0.75 | Honor Gemini's decision |
| 0.50 – 0.74 | Override to MANUAL_REVIEW |
| < 0.50 | Override to REJECTED |

## Tech Stack

- **Orchestration:** LangGraph
- **LLM:** LangChain `ChatGoogleGenerativeAI` + Gemini (Google AI Studio free tier)
  - Both extraction and adjudication use the same cascade: `gemini-3.1-flash-lite` → `gemini-2.5-flash-lite` → `gemini-2.0-flash-lite` → `gemini-3.5-flash` → `gemini-3.0-flash` → `gemini-2.5-flash` → `gemini-2.0-flash`
  - Rate-limited models skipped globally for 24 hours, then reset
- **API:** FastAPI
- **Frontend:** Streamlit
- **Database:** PostgreSQL (SQLAlchemy + Alembic)
- **Hosting:** Render.com (CI/CD via git push to main)
- **Observability:** LangSmith

## Project Structure

```
.
├── backend/
│   ├── requirements.txt
│   ├── data/
│   │   └── policy_terms.json           # loaded at startup, cached via @lru_cache
│   └── src/
│       ├── main.py                     # FastAPI app, health check, CORS
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
│       │   ├── graph.py                # LangGraph wiring + conditional edges
│       │   └── state.py                # ClaimState TypedDict
│       ├── schemas/                    # Pydantic request/response models
│       ├── models/                     # SQLAlchemy DB models
│       └── services/
│           ├── llm.py                  # LLMService, cascade fallback, 24h reset
│           ├── policy.py               # policy loader + context builder
│           ├── claim_processor.py      # pipeline runner + response mapper
│           ├── claim_repository.py     # DB reads (get_claim, list_claims)
│           └── dead_letter.py          # DLQ stub (NoOpDLQ)
├── frontend/
│   └── app.py                          # Streamlit UI
├── backend/scripts/
│   └── clear_db.py                     # utility: wipe claims table (--confirm to run)
├── docs/
│   ├── plan.md
│   ├── design_decisions.md
│   ├── assumptions.md
│   └── failure_handling.md
├── .env.example
└── render.yaml
```

## Getting Started

### Prerequisites

- Python 3.11+
- [Google AI Studio](https://aistudio.google.com) API key (free, no credit card)
- [LangSmith](https://smith.langchain.com) API key (free tier)
- PostgreSQL — or use the Render external DB URL directly

### Setup

```bash
git clone <repo-url>
cd "Plum - ClaimPilot"

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r backend/requirements.txt
pip install -r frontend/requirements.txt

cp .env.example .env.dev
# Edit .env.dev — fill in GOOGLE_API_KEY, LANGSMITH_API_KEY, DATABASE_URL

alembic upgrade head
```

### Run

```bash
# Terminal 1 — Backend (http://localhost:8000)
uvicorn backend.src.main:app --reload

# Terminal 2 — Frontend (http://localhost:8501)
streamlit run frontend/app.py
```

**VS Code:** Run & Debug (`Ctrl+Shift+D`) → **Full Stack: API + UI**

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check + DB connectivity |
| `POST` | `/api/claims` | Submit a claim for processing |
| `GET` | `/api/claims/{claim_id}` | Get decision + full trace |
| `GET` | `/api/claims?member_id=X` | List member's claims |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_API_KEY` | Google AI Studio key |
| `LANGSMITH_API_KEY` | LangSmith tracing key |
| `LANGCHAIN_TRACING_V2` | Set to `true` |
| `LANGCHAIN_PROJECT` | LangSmith project name |
| `DATABASE_URL` | PostgreSQL connection string |
| `ENVIRONMENT` | `dev` or `prod` |
| `API_BASE_URL` | FastAPI base URL (for Streamlit) |

## Deployment

Every push to `main` auto-deploys both services on Render.

**First deploy:** Connect repo → New Blueprint → Render reads `render.yaml` → provisions both services + PostgreSQL. Then set `GOOGLE_API_KEY`, `LANGSMITH_API_KEY`, and `API_BASE_URL` in the Render dashboard.

## Running Tests

```bash
pytest backend/tests/ -v
```

## Utility Scripts

```bash
# Preview what clear_db.py would delete (dry run)
python -m backend.scripts.clear_db

# Actually delete all claims + documents
python -m backend.scripts.clear_db --confirm
```

## Docs

- [Project Plan](docs/plan.md)
- [Design Decisions](docs/design_decisions.md)
- [Assumptions](docs/assumptions.md)
