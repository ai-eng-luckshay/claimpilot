from typing import Union

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.src.config import logger_config
from backend.src.models.database import get_async_db
from backend.src.schemas.claim import ClaimSubmitRequest, ClaimResponse, DocumentValidationError
from backend.src.services.claim_processor import process_claim
from backend.src.services.claim_repository import get_claim_by_id, list_member_claims

claims_router = APIRouter(tags=["Claims"])


@claims_router.post("", response_model=None)
async def submit_claim(request: ClaimSubmitRequest) -> Union[ClaimResponse, DocumentValidationError]:
    result = await process_claim(request)
    logger_config.log_response(result)
    return result


@claims_router.get("/{claim_id}", response_model=ClaimResponse)
async def get_claim(claim_id: str, db: AsyncSession = Depends(get_async_db)):
    result = await get_claim_by_id(claim_id, db)
    logger_config.log_response(result)
    return result


@claims_router.get("", response_model=list)
async def list_claims(
    member_id: str | None = Query(default=None, description="Filter by member ID"),
    db: AsyncSession = Depends(get_async_db),
):
    result = await list_member_claims(member_id, db)
    logger_config.log_response(result)
    return result
