"""Node 3 — validate_documents: checks correct document types are present for the claim category."""

from backend.src.config.logger_config import error_logger
from backend.src.pipeline.state import ClaimState
from backend.src.services.policy import load_policy


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
