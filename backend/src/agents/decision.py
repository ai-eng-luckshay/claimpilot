"""save_to_db LangGraph node — persists the final claim decision to PostgreSQL."""

import time
import uuid as uuid_module
from datetime import date

from backend.src.config.logger_config import error_logger
from backend.src.pipeline.state import ClaimState
from backend.src.models.database import SessionLocal
from backend.src.models.claim import Claim, ClaimDocument

_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 2]  # seconds between attempt 1→2, 2→3


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

    last_error: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
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
                    "save_to_db: committed claim_id=%s decision=%s attempt=%d",
                    claim_id_str, state.get("decision"), attempt,
                )
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

            # Committed successfully
            return {
                "failed_components": failed_components,
                "trace": {**trace, "save_to_db": {"success": True, "claim_id": claim_id_str}},
            }

        except Exception as e:
            last_error = e
            error_logger.error(
                "save_to_db: attempt %d/%d failed claim_id=%s — %s",
                attempt, _MAX_RETRIES, claim_id_str, e,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAYS[attempt - 1])

    # All retries exhausted — mark failure so the response layer can block the caller.
    error_logger.error(
        "save_to_db: all %d attempts failed claim_id=%s — %s",
        _MAX_RETRIES, claim_id_str, last_error, exc_info=True,
    )
    _dead_letter(claim_id_str, state, str(last_error))
    failed_components.append("save_to_db")
    return {
        "failed_components": failed_components,
        "trace": {**trace, "save_to_db": {"success": False, "attempts": _MAX_RETRIES, "error": str(last_error)}},
    }


def _dead_letter(claim_id: str, state: ClaimState, error: str) -> None:
    """
    TODO: Dead letter queue — production implementation needed.

    When save_to_db exhausts all retries, the fully-adjudicated claim state is
    published here so it can be replayed once the DB recovers, without requiring
    the customer to resubmit.

    Production options:
      - AWS SQS / GCP Pub/Sub: publish claim_id + full state as a message;
        a background worker retries the DB write on consume.
      - Redis stream: XADD claims:dlq * claim_id <id> state <json>
      - Local fallback file (current stub): writes to uploads/dlq/ as JSON;
        acceptable for a single-instance deployment, not for multi-instance.

    Until this is wired in, the caller receives HTTP 503 and must resubmit.
    The claim_id is preserved so if the customer resubmits, their reference is new.
    """
    import json
    from pathlib import Path

    dlq_dir = Path(__file__).parent.parent.parent.parent / "uploads" / "dlq"
    try:
        dlq_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "claim_id": claim_id,
            "error": error,
            "decision": state.get("decision"),
            "member_id": state.get("request", {}).get("member_id"),
            "failed_components": list(state.get("failed_components", [])),
        }
        (dlq_dir / f"{claim_id}.json").write_text(json.dumps(payload, indent=2))
        error_logger.warning("_dead_letter: wrote claim_id=%s to local DLQ at %s", claim_id, dlq_dir)
    except Exception as e:
        error_logger.error("_dead_letter: failed to write DLQ entry claim_id=%s — %s", claim_id, e)
