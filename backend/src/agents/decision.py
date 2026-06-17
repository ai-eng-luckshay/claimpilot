"""save_to_db LangGraph node — persists the final claim decision to PostgreSQL."""

import uuid as uuid_module
from datetime import date

from backend.src.config.logger_config import error_logger
from backend.src.pipeline.state import ClaimState
from backend.src.models.database import SessionLocal
from backend.src.models.claim import Claim, ClaimDocument


def save_to_db(state: ClaimState) -> dict:
    """Persist Claim + ClaimDocument rows after the pipeline completes."""
    claim_id_str = state.get("claim_id", "")
    request = state.get("request", {})
    extracted_docs = state.get("extracted_documents", [])
    saved_files = state.get("saved_files", [])
    failed_components = list(state.get("failed_components", []))
    trace = dict(state.get("trace", {}))

    file_path_by_name = {f["file_name"]: f.get("file_path") for f in saved_files}

    try:
        treatment_date_val = date.fromisoformat(str(request.get("treatment_date")))
    except (ValueError, TypeError):
        treatment_date_val = date.today()

    try:
        db = SessionLocal()
        try:
            claim = Claim(
                id=uuid_module.UUID(claim_id_str),
                member_id=request.get("member_id", ""),
                policy_id=request.get("policy_id", ""),
                claim_category=request.get("claim_category", ""),
                treatment_date=treatment_date_val,
                claimed_amount=float(request.get("claimed_amount") or 0),
                decision=state.get("decision"),
                approved_amount=state.get("approved_amount"),
                confidence_score=state.get("confidence_score"),
                rejection_reasons=state.get("rejection_reasons", []),
                decision_reason=state.get("decision_reason"),
                trace=trace,
                failed_components=failed_components,
                source_channel=request.get("source_channel", "WEB"),
            )
            db.add(claim)

            for doc in extracted_docs:
                fname = doc.get("file_name", "")
                doc_extra = {
                    k: v for k, v in doc.items()
                    if k not in ("file_name", "classified_type", "quality_flags", "overall_confidence")
                }
                db.add(ClaimDocument(
                    claim_id=uuid_module.UUID(claim_id_str),
                    file_name=fname,
                    document_type=doc.get("classified_type", "UNKNOWN"),
                    file_path=file_path_by_name.get(fname),
                    extraction=doc_extra,
                    quality_flags=doc.get("quality_flags", []),
                    confidence=doc.get("overall_confidence"),
                ))

            db.commit()
            error_logger.info(
                "save_to_db: committed claim_id=%s decision=%s", claim_id_str, state.get("decision")
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    except Exception as e:
        error_logger.error("save_to_db: DB write failed claim_id=%s — %s", claim_id_str, e, exc_info=True)
        failed_components.append("save_to_db")
        return {
            "failed_components": failed_components,
            "trace": {**trace, "save_to_db": {"success": False, "error": str(e)}},
        }

    return {
        "failed_components": failed_components,
        "trace": {**trace, "save_to_db": {"success": True, "claim_id": claim_id_str}},
    }
