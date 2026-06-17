# Technical Notes & Code Snippets

Reference material for the ClaimPilot implementation. Reflects the current codebase.

---

## LLM Integration — LangChain + Gemini

ClaimPilot calls Gemini via **LangChain's `ChatGoogleGenerativeAI`** wrapper with `with_structured_output()`, not the raw `google-generativeai` SDK. This is the pattern used in every agent node:

```python
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

class MySchema(BaseModel):
    field_one: str
    confidence: float

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key)
structured_llm = llm.with_structured_output(MySchema, method="json_schema")
result: MySchema = structured_llm.invoke([HumanMessage(content=[...])])
```

The LangGraph state carries the structured Pydantic results between agents. Gemini is the executor inside the two agent nodes that need LLM reasoning.

---

## Confidence Scores — Self-Reported via Structured Output

Confidence scores are **self-reported by Gemini** as a field inside the structured JSON response schema, not derived from token-level log probabilities.

Each extraction schema includes a `confidence: float` field. The adjudication schema includes a `confidence_score: float` field. Gemini fills these values based on its own assessment of certainty. The decision confidence formula in `adjudicate.py` reads this value directly.

### Why self-reported confidence is used here

`response_logprobs=True` is not exposed through `ChatGoogleGenerativeAI.with_structured_output()`. Using the raw SDK to obtain logprobs would require bypassing LangChain entirely and giving up the `with_structured_output` schema enforcement. For this assignment's scale (12 test cases), Gemini's self-reported confidence is sufficient: it reflects uncertainty about handwriting, partial documents, ambiguous conditions, and low-quality images in a format that is directly tied to the structured output fields.

---

## Model Cascades and Global Exhausted-Model Registry

Two model cascades are defined in `backend/src/services/llm.py`:

| Cascade key | Primary model | Fallback chain |
|-------------|--------------|----------------|
| `"extraction"` | `gemini-3.1-flash-lite` | `gemini-2.5-flash-lite` → `gemini-2.0-flash-lite` → `gemini-3.5-flash` → `gemini-3.0-flash` → `gemini-2.5-flash` → `gemini-2.0-flash` |
| `"adjudication"` | `gemini-3.1-flash-lite` | `gemini-2.5-flash-lite` → `gemini-2.0-flash-lite` → `gemini-3.5-flash` → `gemini-3.0-flash` → `gemini-2.5-flash` → `gemini-2.0-flash` |

**Global exhausted-model registry**: `GeminiService` maintains a class-level `_exhausted_models: dict[str, float]` keyed by model name, storing the timestamp when the model was first rate-limited. When a 429 is received, the model is added to this global set and skipped for all cascades — not just the one that hit the limit. At the start of each `structured_call`, models whose timestamp is older than 24 hours are removed and re-admitted.

```python
# On 429:
with GeminiService._lock:
    if model not in GeminiService._exhausted_models:
        GeminiService._exhausted_models[model] = time.time()

# At start of each call — expire recovered models:
recovered = [m for m, t in GeminiService._exhausted_models.items()
             if now - t >= GeminiService._RESET_AFTER_SECONDS]
for m in recovered:
    del GeminiService._exhausted_models[m]
```

---

## Gemini — PDF and Image Input

Gemini accepts both images and PDFs natively via LangChain's multimodal message format. No `pdf2image`, no `poppler`.

```python
from langchain_core.messages import HumanMessage
import base64

# Image
HumanMessage(content=[
    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}},
    {"type": "text", "text": "Extract all claim information from this document."},
])

# PDF — same pattern, different mime_type
HumanMessage(content=[
    {"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{b64_data}"}},
    {"type": "text", "text": "Extract all billing information from this hospital bill."},
])
```

---

## Gemini Roles in ClaimPilot

Two Gemini calls are made per claim (under normal conditions):

| Call | Agent | Model (primary) | Task |
|------|-------|----------------|------|
| GEMINI CALL 1 | `extract_documents` | `gemini-2.0-flash-lite` | OCR all documents in a single call; extract structured fields; cross-check patient names across documents |
| GEMINI CALL 2 | `adjudicate_claim` | `gemini-2.5-flash` | Policy eligibility check, fraud detection, financial calculation, and final decision — all in one call |

A mismatch detected at extraction routes to `reject_patient_mismatch → save_to_db → END` without consuming GEMINI CALL 2.

---

## Blur Gate — OpenCV Laplacian Variance

```python
import cv2, numpy as np

def _laplacian_variance(image_bytes: bytes) -> float:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    return cv2.Laplacian(img, cv2.CV_64F).var()

BLUR_THRESHOLD = 80  # variance below this → FAIL
```

- Image with `file_data` present and variance ≥ 80 → PASS (continue to extraction)
- Image with `file_data` present and variance < 80 → FAIL (stop pipeline, return `DOCUMENT_UNREADABLE`)
- Image with no `file_data` at all → FAIL (stop pipeline, return `DOCUMENT_UNREADABLE`)
- PDF → always PASS (blur detection skipped)
