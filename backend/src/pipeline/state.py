from typing import TypedDict, Any


class ClaimState(TypedDict, total=False):
    # Input (serialized ClaimSubmitRequest)
    request: dict

    # Claim identity — generated upfront so files can be saved before pipeline runs
    claim_id: str

    # Saved file records: [{file_name, doc_type, file_path, url}]
    saved_files: list[dict]

    # Blur gate (OpenCV, images only)
    blur_check_passed: bool
    blur_error: dict | None

    # Gemini call 1: OCR + Classification (single call for all docs)
    extracted_documents: list[dict]
    extraction_complete: bool
    extraction_failed: bool  # True when LLM call failed — routes directly to save_to_db as MANUAL_REVIEW

    # Document type validation (runs after extraction)
    validation_passed: bool
    validation_error: dict | None

    # Patient name cross-check (returned by extraction agent, Gemini-evaluated)
    patient_name_consistent: bool
    patient_name_mismatch_details: str | None

    # Gemini call 2: Adjudication (policy + fraud + decision in one call)
    decision: str | None
    approved_amount: float | None
    confidence_score: float | None
    decision_reason: str | None
    rejection_reasons: list[str]

    # Graceful degradation tracking
    failed_components: list[str]

    # Full pipeline trace (accumulated per node)
    trace: dict[str, Any]
