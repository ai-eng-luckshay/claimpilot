"""Blur gate + Document Validation — two separate LangGraph nodes."""
import base64

import cv2
import numpy as np

from backend.src.config.logger_config import error_logger
from backend.src.pipeline.state import ClaimState
from backend.src.services.policy import load_policy

BLUR_THRESHOLD = 80.0


# ---------------------------------------------------------------------------
# Blur gate (runs before Gemini — saves API quota on unreadable images)
# ---------------------------------------------------------------------------

def _blur_variance(image_b64: str) -> float:
    """Return Laplacian variance of a base64-encoded image. Low = blurry."""
    image_bytes = base64.b64decode(image_b64)
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def blur_gate(state: ClaimState) -> dict:
    """
    LangGraph node: OpenCV blur check on every image file.
    PDFs are skipped — Gemini handles PDF readability internally.
    Any image with Laplacian variance < 80 → stop immediately, return error.
    No Gemini quota consumed for unreadable images.
    """
    request = state.get("request", {})
    documents = request.get("documents", [])
    trace_checks: list[dict] = []

    error_logger.info("blur_gate: checking %d document(s)", len(documents))

    for i, doc in enumerate(documents):
        file_name = doc.get("file_name", f"document_{i + 1}")
        mime_type = doc.get("mime_type", "")
        file_data = doc.get("file_data")

        # PDFs: skip blur check
        if not mime_type.startswith("image/"):
            error_logger.debug("blur_gate: SKIP %s (pdf)", file_name)
            trace_checks.append({"file": file_name, "result": "SKIP", "reason": "pdf"})
            continue

        if not file_data:
            error_logger.warning("blur_gate: FAIL %s (no file data)", file_name)
            trace_checks.append({"file": file_name, "result": "FAIL", "reason": "no_data"})
            return {
                "blur_check_passed": False,
                "blur_error": {
                    "error_type": "DOCUMENT_UNREADABLE",
                    "message": (
                        f"No image data was received for {file_name}. "
                        "Please re-upload the document."
                    ),
                    "unreadable_file": file_name,
                },
                "trace": {
                    **state.get("trace", {}),
                    "blur_gate": {"result": "FAIL", "checks": trace_checks},
                },
            }

        try:
            variance = _blur_variance(file_data)
        except Exception as e:
            error_logger.warning("blur_gate: OpenCV error on %s — %s", file_name, e)
            trace_checks.append({"file": file_name, "result": "SKIP", "reason": "opencv_error"})
            continue

        if variance < BLUR_THRESHOLD:
            doc_type_hint = doc.get("document_type") or "document"
            friendly = doc_type_hint.lower().replace("_", " ")
            msg = (
                f"The {friendly} you uploaded ({file_name}) is too blurry to read. "
                "Please take a clearer photo and re-upload that document."
            )
            error_logger.warning(
                "blur_gate: FAIL %s — variance=%.2f below threshold=%.2f",
                file_name, variance, BLUR_THRESHOLD,
            )
            trace_checks.append({
                "file": file_name,
                "result": "FAIL",
                "variance": round(variance, 2),
                "threshold": BLUR_THRESHOLD,
            })
            return {
                "blur_check_passed": False,
                "blur_error": {
                    "error_type": "DOCUMENT_UNREADABLE",
                    "message": msg,
                    "unreadable_file": file_name,
                },
                "trace": {
                    **state.get("trace", {}),
                    "blur_gate": {"result": "FAIL", "checks": trace_checks},
                },
            }

        error_logger.debug("blur_gate: PASS %s — variance=%.2f", file_name, variance)
        trace_checks.append({
            "file": file_name,
            "result": "PASS",
            "variance": round(variance, 2),
        })

    error_logger.info("blur_gate: all documents passed")
    return {
        "blur_check_passed": True,
        "blur_error": None,
        "trace": {
            **state.get("trace", {}),
            "blur_gate": {"result": "PASS", "checks": trace_checks},
        },
    }


# ---------------------------------------------------------------------------
# Document validation (runs after Gemini extraction — uses classified types)
# ---------------------------------------------------------------------------

def validate_documents(state: ClaimState) -> dict:
    """
    LangGraph node: verify that the right document types are present for the claim category.
    Uses Gemini-classified types from extracted_documents — NOT the client-declared label.
    This is the correct way to detect 'you uploaded a prescription where a bill is required'.
    """
    request = state.get("request", {})
    extracted = state.get("extracted_documents", [])
    claim_category = request.get("claim_category", "")

    error_logger.info(
        "validate_documents: category=%s, %d extracted doc(s)", claim_category, len(extracted)
    )

    policy = load_policy()
    doc_reqs = policy.get_document_requirements(claim_category)
    required_types: list[str] = doc_reqs.get("required", [])

    # Use what Gemini actually classified, not what the client sent
    classified_types = [doc.get("classified_type", "UNKNOWN") for doc in extracted]

    error_logger.debug(
        "validate_documents: required=%s classified=%s", required_types, classified_types
    )

    missing_types = [r for r in required_types if r not in classified_types]

    trace_entry = {
        "agent": "validate_documents",
        "claim_category": claim_category,
        "required_types": required_types,
        "classified_types": classified_types,
    }

    if missing_types:
        error_logger.warning(
            "validate_documents: FAIL — missing=%s wrong=%s",
            missing_types,
            [t for t in classified_types if t not in required_types and t != "UNKNOWN"],
        )
        # Were wrong doc types supplied (e.g. two prescriptions instead of one + bill)?
        wrong_types = [t for t in classified_types if t not in required_types and t != "UNKNOWN"]
        if wrong_types:
            msg = (
                f"You uploaded: {', '.join(classified_types)}. "
                f"A {claim_category} claim requires: {', '.join(required_types)}. "
                f"Missing: {', '.join(missing_types)}. "
                "Please upload the missing document and resubmit."
            )
        else:
            msg = (
                f"You uploaded: {', '.join(classified_types) or 'no recognisable documents'}. "
                f"A {claim_category} claim requires: {', '.join(required_types)}. "
                f"Missing: {', '.join(missing_types)}. "
                "Please upload the missing document and resubmit."
            )

        trace_entry["result"] = "FAIL"
        trace_entry["missing_types"] = missing_types
        return {
            "validation_passed": False,
            "validation_error": {
                "error_type": "DOCUMENT_VALIDATION_FAILED",
                "message": msg,
                "what_was_uploaded": classified_types,
                "what_is_required": required_types,
            },
            "trace": {**state.get("trace", {}), "document_validation": trace_entry},
        }

    error_logger.info("validate_documents: PASS — all required types present")
    trace_entry["result"] = "PASS"
    return {
        "validation_passed": True,
        "validation_error": None,
        "trace": {**state.get("trace", {}), "document_validation": trace_entry},
    }
