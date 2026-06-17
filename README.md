# ClaimPilot

Automated health insurance claims processing system built for Plum. Accepts a claim submission (member details + medical documents) and produces a decision — **APPROVED**, **PARTIAL**, **REJECTED**, or **MANUAL_REVIEW** — with a full explanation, approved amount, and confidence score.

## Architecture

Five-agent LangGraph pipeline:

| Agent | Responsibility |
|---|---|
| Document Validation | Doc type checks, readability gate (OpenCV blur variance), patient name match |
| OCR / Extraction | Gemini 2.5 Flash Vision — structured field extraction with per-field confidence via logprobs |
| Policy Check | Waiting periods, exclusions, per-claim limits, co-pay, network discounts |
| Fraud Detection | Same-day claims, document alterations, high-value threshold, monthly claim count |
| Decision | Aggregates all checks, computes confidence score, produces final decision |

## Tech Stack

- **Orchestration:** LangGraph
- **OCR / AI:** Gemini 2.5 Flash (vision, free tier) · Gemini 2.5 Flash-Lite (text reasoning)
- **API:** FastAPI
- **Frontend:** Streamlit
- **Database:** PostgreSQL (SQLAlchemy + Alembic)
- **Hosting:** Render.com (CI/CD via git push to main)
- **Observability:** LangSmith

## Project Structure

```
.
├── backend/                  # FastAPI app + LangGraph pipeline
│   ├── requirements.in       # unpinned deps (edit this)
│   ├── requirements.txt      # pinned deps (pip-compile output)
│   └── src/
│       ├── main.py           # FastAPI app, health check, CORS
│       ├── config.py         # pydantic-settings
│       ├── agents/           # LangGraph agents (one file per agent)
│       ├── models/           # SQLAlchemy DB models
│       ├── schemas/          # Pydantic request/response models
│       ├── pipeline/         # LangGraph graph + ClaimState
│       └── services/         # policy loader, Gemini client
├── frontend/                 # Streamlit UI
│   ├── requirements.in
│   ├── requirements.txt
│   └── app.py
├── docs/                     # Architecture, plan, technical notes
├── .env.example              # keys only — copy to .env.dev and fill in
└── render.yaml               # Render deployment config
```

## Getting Started

### Prerequisites

- Python 3.11+
- [Google AI Studio](https://aistudio.google.com) API key (free, no credit card)
- [LangSmith](https://smith.langchain.com) API key (free tier)
- PostgreSQL — or use the Render external DB URL directly

### Setup

```bash
# Clone and enter the repo
git clone <repo-url>
cd "Plum - ClaimPilot"

# Create shared virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r backend/requirements.txt
pip install -r frontend/requirements.txt

# Configure environment
cp .env.example .env.dev
# Edit .env.dev — fill in GOOGLE_API_KEY, LANGSMITH_API_KEY, DATABASE_URL

# Run database migrations
alembic upgrade head
```

### Run

```bash
# Terminal 1 — Backend API (http://localhost:8000)
uvicorn backend.src.main:app --reload

# Terminal 2 — Frontend UI (http://localhost:8501)
streamlit run frontend/app.py
```

**VS Code:** Run & Debug (`Ctrl+Shift+D`) → select **Full Stack: API + UI** to start both.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check + DB connectivity |
| `POST` | `/api/claims` | Submit a claim for processing |
| `GET` | `/api/claims/{claim_id}` | Get decision + full trace |
| `GET` | `/api/claims?member_id=X` | List member's claims |

## Environment Variables

| Variable | Service | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | API | Google AI Studio key |
| `LANGSMITH_API_KEY` | API | LangSmith tracing key |
| `LANGCHAIN_TRACING_V2` | API | Set to `true` |
| `LANGCHAIN_PROJECT` | API | LangSmith project (default: `claimpilot`) |
| `DATABASE_URL` | API | PostgreSQL connection string |
| `ENVIRONMENT` | API | `dev` or `prod` |
| `API_BASE_URL` | UI | FastAPI base URL for Streamlit |

## Deployment

Every push to `main` auto-deploys both services on Render.

**First deploy:** Connect repo → New Blueprint → Render reads `render.yaml` → creates both services + PostgreSQL automatically. Then set `GOOGLE_API_KEY`, `LANGSMITH_API_KEY`, and `API_BASE_URL` in the Render dashboard.

| Service | URL |
|---------|-----|
| API | `https://claimpilot-api.onrender.com` |
| UI | `https://claimpilot-ui.onrender.com` |

## Running Tests

```bash
pytest backend/tests/ -v
```

## Docs

- [Project Plan](docs/plan.md) — decisions, agent responsibilities, timeline
- [Technical Notes](docs/technical_notes.md) — Gemini logprobs pattern, code snippets
- [Architecture](docs/architecture.md) *(Day 5)*
- [Component Contracts](docs/contracts.md) *(Day 5)*
- [Eval Report](docs/eval_report.md) — all 12 test cases with results *(Day 5)*
