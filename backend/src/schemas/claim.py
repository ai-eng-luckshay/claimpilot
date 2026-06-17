from datetime import date
from typing import Any
from pydantic import BaseModel


class DocumentInput(BaseModel):
    file_name: str = ""
    file_data: str | None = None  # base64-encoded bytes
    mime_type: str | None = None  # image/jpeg, image/png, application/pdf
    document_type: str | None = None  # user-provided label

    # Test-mode helpers (not required in production)
    file_id: str | None = None
    actual_type: str | None = None  # test mode: the actual document type
    content: dict | None = None  # test mode: pre-extracted document content
    quality: str | None = None  # test mode: GOOD / UNREADABLE
    patient_name_on_doc: str | None = None  # test mode: for TC003 patient mismatch

    def effective_type(self) -> str | None:
        """Return the declared document type — user-provided or test-mode actual_type."""
        return self.document_type or self.actual_type


class ClaimsHistoryItem(BaseModel):
    claim_id: str
    date: str
    amount: float
    provider: str | None = None


class ClaimSubmitRequest(BaseModel):
    member_id: str
    policy_id: str
    claim_category: str
    treatment_date: date
    claimed_amount: float
    documents: list[DocumentInput]
    claims_history: list[ClaimsHistoryItem] | None = None
    hospital_name: str | None = None
    ytd_claims_amount: float | None = None
    simulate_component_failure: bool = False
    source_channel: str = "WEB"


class DocumentValidationError(BaseModel):
    claim_id: None = None
    decision: None = None
    error_type: str
    message: str
    what_was_uploaded: list[str] | None = None
    what_is_required: list[str] | None = None
    unreadable_file: str | None = None


class ClaimResponse(BaseModel):
    claim_id: str | None = None
    decision: str | None = None
    approved_amount: float | None = None
    confidence_score: float | None = None
    reason: str | None = None
    rejection_reasons: list[str] = []
    trace: dict[str, Any] = {}
    failed_components: list[str] = []
    documents: list[dict[str, Any]] = []  # [{file_name, doc_type, url}] for manual review
