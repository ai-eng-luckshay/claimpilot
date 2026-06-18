"""Claim repository — database reads and response mapping for stored claims."""

from fastapi import HTTPException

from backend.src.config.logger_config import error_logger
from backend.src.schemas.claim import ClaimResponse
from backend.src.services.file_storage import get_file_url


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
