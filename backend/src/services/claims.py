import uuid
from typing import Union

from fastapi import HTTPException

from backend.src.config.logger_config import error_logger, application_logger
from backend.src.pipeline.graph import pipeline, ClaimState
from backend.src.schemas.claim import ClaimSubmitRequest, ClaimResponse, DocumentValidationError
from backend.src.services.file_storage import save_document, get_file_url


def process_claim(request: ClaimSubmitRequest) -> Union[ClaimResponse, DocumentValidationError]:

    claim_id = str(uuid.uuid4())
    application_logger.info(
        "process_claim: START claim_id=%s member_id=%s category=%s docs=%d",
        claim_id, request.member_id, request.claim_category, len(request.documents),
    )

    saved_files = _persist_documents(claim_id, request)

    initial_state = ClaimState(
        request=request.model_dump(mode="json"),
        claim_id=claim_id,
        saved_files=saved_files,
        failed_components=[],
        trace={},
    )

    try:
        error_logger.info("process_claim: invoking pipeline for claim_id=%s", claim_id)
        final_state = pipeline.invoke(initial_state)
        error_logger.info(
            "process_claim: pipeline complete claim_id=%s failed_components=%s",
            claim_id, final_state.get("failed_components", []),
        )
    except HTTPException:
        raise
    except Exception as e:
        error_logger.error("process_claim: pipeline raised exception claim_id=%s — %s", claim_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {e}")

    # If the DB write failed after all retries, block the response entirely.
    # Returning a decision to the caller with no DB record creates an irreconcilable
    # inconsistency — the customer believes the claim is decided, the company has nothing.
    if "save_to_db" in final_state.get("failed_components", []):
        error_logger.error(
            "process_claim: blocking response — save_to_db failed claim_id=%s", claim_id
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Your claim was processed but could not be saved due to a database error. "
                "No decision has been recorded. Please resubmit your claim."
            ),
        )

    response = _map_state_to_response(claim_id, saved_files, final_state)
    application_logger.info(
        "process_claim: END claim_id=%s response_type=%s",
        claim_id, type(response).__name__,
    )
    return response


def _persist_documents(claim_id: str, request: ClaimSubmitRequest) -> list[dict]:
    """Save each document's raw bytes to disk. Returns a list of file records."""
    records: list[dict] = []
    for i, doc in enumerate(request.documents):
        doc_type = doc.effective_type() or "UNKNOWN"
        if doc.file_data:
            try:
                rel_path = save_document(claim_id, i, doc.file_name, doc.file_data)
                url = get_file_url(rel_path)
                error_logger.debug(
                    "_persist_documents: saved %s → %s", doc.file_name, rel_path
                )
            except Exception as e:
                error_logger.error(
                    "_persist_documents: failed to save %s — %s", doc.file_name, e
                )
                rel_path, url = None, None
        else:
            error_logger.debug("_persist_documents: no file_data for %s (test mode)", doc.file_name)
            rel_path, url = None, None

        records.append({
            "file_name": doc.file_name,
            "doc_type": doc_type,
            "file_path": rel_path,
            "url": url,
            "mime_type": doc.mime_type,
        })
    return records


def _map_state_to_response(
    claim_id: str,
    saved_files: list[dict],
    final_state: dict,
) -> Union[ClaimResponse, DocumentValidationError]:
    # Blur gate failed — unreadable image (TC002)
    if not final_state.get("blur_check_passed", True):
        err = final_state.get("blur_error", {})
        return DocumentValidationError(
            error_type=err.get("error_type", "DOCUMENT_UNREADABLE"),
            message=err.get("message", "Document is too blurry to read."),
            unreadable_file=err.get("unreadable_file"),
        )

    # Document type validation failed — wrong/missing docs (TC001)
    if final_state.get("validation_passed") is False:
        err = final_state.get("validation_error", {})
        return DocumentValidationError(
            error_type=err.get("error_type", "DOCUMENT_VALIDATION_FAILED"),
            message=err.get("message", "Document validation failed."),
            what_was_uploaded=err.get("what_was_uploaded"),
            what_is_required=err.get("what_is_required"),
        )

    # Full pipeline decision
    decision = final_state.get("decision") or "PENDING"

    # Enrich saved_files with Gemini-classified doc type (extraction runs after file save)
    classified_by_name = {
        doc.get("file_name", ""): doc.get("classified_type", "UNKNOWN")
        for doc in final_state.get("extracted_documents", [])
    }
    viewable_docs = [
        {**f, "doc_type": classified_by_name.get(f.get("file_name", ""), f.get("doc_type", "UNKNOWN"))}
        for f in saved_files
        if f.get("url")
    ]

    return ClaimResponse(
        claim_id=claim_id,
        decision=decision,
        approved_amount=final_state.get("approved_amount"),
        confidence_score=final_state.get("confidence_score"),
        reason=final_state.get("decision_reason"),
        rejection_reasons=final_state.get("rejection_reasons", []),
        trace=final_state.get("trace", {}),
        failed_components=final_state.get("failed_components", []),
        documents=viewable_docs,
    )


def get_claim_by_id(claim_id: str, db) -> ClaimResponse:
    from backend.src.models.claim import Claim
    error_logger.info("get_claim_by_id: claim_id=%s", claim_id)
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        error_logger.warning("get_claim_by_id: not found claim_id=%s", claim_id)
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")
    return _db_claim_to_response(claim)


def list_member_claims(member_id: str | None, db) -> list[dict]:
    from backend.src.models.claim import Claim
    error_logger.info("list_member_claims: member_id=%s", member_id)
    query = db.query(Claim)
    if member_id:
        query = query.filter(Claim.member_id == member_id)
    claims = query.order_by(Claim.submitted_at.desc()).limit(100).all()
    error_logger.info("list_member_claims: returning %d claim(s)", len(claims))
    return [_db_claim_to_dict(c) for c in claims]


def _db_claim_to_response(claim) -> ClaimResponse:
    from backend.src.services.file_storage import get_file_url
    docs = [
        {
            "file_name": d.file_name,
            "doc_type": d.document_type,
            "url": get_file_url(d.file_path) if d.file_path else None,
            "mime_type": None,
        }
        for d in claim.documents
    ]
    return ClaimResponse(
        claim_id=str(claim.id),
        decision=claim.decision,
        approved_amount=float(claim.approved_amount) if claim.approved_amount else None,
        confidence_score=claim.confidence_score,
        reason=claim.decision_reason,
        rejection_reasons=claim.rejection_reasons or [],
        trace=claim.trace or {},
        failed_components=claim.failed_components or [],
        documents=docs,
    )


def _db_claim_to_dict(claim) -> dict:
    from backend.src.services.file_storage import get_file_url
    docs = [
        {
            "file_name": d.file_name,
            "doc_type": d.document_type,
            "url": get_file_url(d.file_path) if d.file_path else None,
        }
        for d in claim.documents
    ]
    return {
        "claim_id": str(claim.id),
        "member_id": claim.member_id,
        "claim_category": claim.claim_category,
        "treatment_date": str(claim.treatment_date) if claim.treatment_date else None,
        "claimed_amount": float(claim.claimed_amount) if claim.claimed_amount else None,
        "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
        "decision": claim.decision,
        "approved_amount": float(claim.approved_amount) if claim.approved_amount else None,
        "confidence_score": claim.confidence_score,
        "reason": claim.decision_reason,
        "rejection_reasons": claim.rejection_reasons or [],
        "failed_components": claim.failed_components or [],
        "trace": claim.trace or {},
        "documents": docs,
    }
