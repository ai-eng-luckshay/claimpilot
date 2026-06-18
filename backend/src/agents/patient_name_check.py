"""Node 3a — patient_name_check: fast REJECTED path when patient names differ across documents."""

from backend.src.config.logger_config import error_logger
from backend.src.pipeline.state import ClaimState


def reject_patient_mismatch(state: ClaimState) -> dict:
    """LangGraph node: fast REJECTED path when Gemini detects cross-document name mismatch."""
    details = state.get("patient_name_mismatch_details") or "Patient names differ across documents."
    error_logger.warning("reject_patient_mismatch: %s", details)
    return {
        "decision": "REJECTED",
        "approved_amount": None,
        "confidence_score": 1.0,
        "decision_reason": f"Patient name mismatch detected: {details}",
        "rejection_reasons": ["PATIENT_NAME_MISMATCH"],
        "failed_components": list(state.get("failed_components", [])),
        "trace": {
            **state.get("trace", {}),
            "patient_name_check": {"result": "FAIL", "details": details},
        },
    }
