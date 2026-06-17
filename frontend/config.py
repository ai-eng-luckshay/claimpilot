import os
from pathlib import Path

API_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
if not API_URL.startswith("http"):
    API_URL = f"https://{API_URL}"

IS_DEV = API_URL.startswith("http://localhost")

TEST_CASES_PATH = Path(__file__).parent / "data" / "test_cases.json"
TEST_DOCS_DIR = Path(__file__).parent / "data" / "test_docs"

CLAIM_CATEGORIES = [
    "CONSULTATION",
    "DIAGNOSTIC",
    "PHARMACY",
    "DENTAL",
    "VISION",
    "ALTERNATIVE_MEDICINE",
]

DECISION_STYLE = {
    "APPROVED":      {"bg": "#22c55e", "label": "APPROVED"},
    "PARTIAL":       {"bg": "#f97316", "label": "PARTIAL"},
    "REJECTED":      {"bg": "#ef4444", "label": "REJECTED"},
    "MANUAL_REVIEW": {"bg": "#eab308", "label": "MANUAL REVIEW"},
    "PENDING":       {"bg": "#6b7280", "label": "PENDING"},
}

DECISION_BADGE = {
    "APPROVED":      "🟢",
    "PARTIAL":       "🟠",
    "REJECTED":      "🔴",
    "MANUAL_REVIEW": "🟡",
    "PENDING":       "⚪",
}
