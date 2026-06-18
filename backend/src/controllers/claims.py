from typing import Union

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.src.config import logger_config
from backend.src.models.database import get_db
from backend.src.schemas.claim import ClaimSubmitRequest, ClaimResponse, DocumentValidationError
from backend.src.services.claim_processor import process_claim
from backend.src.services.claim_repository import get_claim_by_id, list_member_claims

claims_router = APIRouter(tags=["Claims"])


@claims_router.post("", response_model=None)
def submit_claim(request: ClaimSubmitRequest) -> Union[ClaimResponse, DocumentValidationError]:
    result = process_claim(request)
    logger_config.log_response(result)
    return result


@claims_router.get("/{claim_id}", response_model=ClaimResponse)
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    result = get_claim_by_id(claim_id, db)
    logger_config.log_response(result)
    return result


@claims_router.get("", response_model=list)
def list_claims(
    member_id: str | None = Query(default=None, description="Filter by member ID"),
    db: Session = Depends(get_db),
):
    result = list_member_claims(member_id, db)
    logger_config.log_response(result)
    return result
