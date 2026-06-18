"""Agent 1: OCR + Classification — single LangChain/Gemini call for all documents."""
from typing import Literal, cast

from pydantic import BaseModel, Field

from backend.src.agents.prompts.extraction import EXTRACTION_PROMPT
from backend.src.config.logger_config import error_logger, application_logger
from backend.src.pipeline.state import ClaimState
from backend.src.schemas.documents import ExtractedDocument, LineItem
from backend.src.services.llm import get_llm_service

# ---------------------------------------------------------------------------
# Structured output schema — Gemini must return this exact shape
# ---------------------------------------------------------------------------

class _LineItem(BaseModel):
    description: str
    amount: float = 0.0


class _DocumentExtraction(BaseModel):
    classified_type: Literal[
        "PRESCRIPTION", "HOSPITAL_BILL", "LAB_REPORT",
        "PHARMACY_BILL", "DENTAL_REPORT", "DISCHARGE_SUMMARY", "UNKNOWN",
    ]
    patient_name: str | None = None
    doctor_name: str | None = None
    doctor_registration: str | None = None
    date: str | None = None
    diagnosis: str | None = None
    medicines: list[str] | None = None
    hospital_name: str | None = None
    line_items: list[_LineItem] | None = None
    total: float | None = None
    test_name: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class _AllDocumentsExtraction(BaseModel):
    documents: list[_DocumentExtraction]
    patient_name_consistent: bool = True
    patient_name_mismatch_details: str | None = None


# ---------------------------------------------------------------------------
# LLM call (provider-agnostic via LLMService)
# ---------------------------------------------------------------------------

async def _call_llm(documents: list[dict]) -> _AllDocumentsExtraction:
    """Single async LLM call for all documents."""
    content_blocks: list[dict] = []
    for i, doc in enumerate(documents):
        content_blocks.append({
            "type": "text",
            "text": f"\n--- Document {i + 1}: {doc.get('file_name', f'document_{i + 1}')} ---",
        })
        mime = doc.get("mime_type", "image/jpeg")
        b64 = doc["file_data"]
        if mime == "application/pdf":
            content_blocks.append({"type": "file", "base64": b64, "mime_type": mime})
        else:
            content_blocks.append({"type": "image", "base64": b64, "mime_type": mime})

    error_logger.info("_call_llm: invoking LLM for %d document(s)", len(documents))
    try:
        result = cast(
            _AllDocumentsExtraction,
            await get_llm_service("extraction").structured_call(
                EXTRACTION_PROMPT,
                _AllDocumentsExtraction,
                content_blocks=content_blocks,
            ),
        )
    except Exception as e:
        error_logger.error("_call_llm: LLM invocation failed — %s", e)
        raise RuntimeError("Document extraction LLM call failed") from e

    error_logger.info(
        "_call_llm: received %d extraction(s) name_consistent=%s",
        len(result.documents), result.patient_name_consistent,
    )
    return result


# ---------------------------------------------------------------------------
# Helper: map typed extraction → ExtractedDocument
# ---------------------------------------------------------------------------

def _to_extracted_doc(ext: _DocumentExtraction, file_name: str) -> ExtractedDocument:
    line_items = None
    if ext.line_items:
        line_items = [LineItem(description=li.description, amount=li.amount) for li in ext.line_items]

    quality_flags = list(ext.quality_flags)
    if ext.confidence < 0.8 and "DOCUMENT_UNREADABLE" not in quality_flags:
        quality_flags.append("DOCUMENT_UNREADABLE")

    return ExtractedDocument(
        classified_type=ext.classified_type,
        file_name=file_name,
        patient_name=ext.patient_name,
        doctor_name=ext.doctor_name,
        doctor_registration=ext.doctor_registration,
        date=ext.date,
        diagnosis=ext.diagnosis,
        medicines=ext.medicines,
        hospital_name=ext.hospital_name,
        line_items=line_items,
        total=ext.total,
        test_name=ext.test_name,
        quality_flags=quality_flags,
        overall_confidence=ext.confidence,
    )


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

async def extract_documents(state: ClaimState) -> dict:
    """
    LangGraph node: single Gemini call for all documents.
    Classifies each document, extracts all fields, and cross-checks patient names.
    Graceful degradation: LLM failure → UNKNOWN stubs, pipeline continues.
    """
    request = state.get("request", {})
    documents = request.get("documents", [])
    failed_components: list[str] = list(state.get("failed_components", []))
    extracted: list[dict] = []
    trace_entries: list[dict] = []
    patient_name_consistent = True
    patient_name_mismatch_details: str | None = None

    application_logger.info(
        "extract_documents: starting extraction for %d document(s)", len(documents)
    )
    try:
        result = await _call_llm(documents)
        patient_name_consistent = result.patient_name_consistent
        patient_name_mismatch_details = result.patient_name_mismatch_details

        extractions = result.documents
        while len(extractions) < len(documents):
            extractions.append(_DocumentExtraction(classified_type="UNKNOWN", confidence=0.0))
        extractions = extractions[: len(documents)]

        for doc, ext in zip(documents, extractions):
            fname = doc.get("file_name", "")
            ed = _to_extracted_doc(ext, fname)
            extracted.append(ed.model_dump())
            error_logger.info(
                "extract_documents: %s → type=%s confidence=%.2f flags=%s",
                fname, ed.classified_type, ed.overall_confidence, ed.quality_flags,
            )
            trace_entries.append({
                "file": fname,
                "classified_type": ed.classified_type,
                "patient_name": ed.patient_name,
                "confidence": ed.overall_confidence,
                "quality_flags": ed.quality_flags,
            })

        if not patient_name_consistent:
            error_logger.warning(
                "extract_documents: patient name mismatch — %s", patient_name_mismatch_details
            )

    except Exception as e:
        error_logger.error("extract_documents: extraction failed — %s", e, exc_info=True)
        failed_components.append("extraction_agent")
        for doc in documents:
            fname = doc.get("file_name", "")
            trace_entries.append({"file": fname, "classified_type": "UNKNOWN", "error": str(e)})

        # Route directly to save_to_db as MANUAL_REVIEW — no point calling adjudication
        # when Gemini already failed once; running it again on unreadable data adds no value.
        return {
            "extracted_documents": [],
            "extraction_complete": False,
            "extraction_failed": True,
            "patient_name_consistent": True,
            "patient_name_mismatch_details": None,
            "decision": "MANUAL_REVIEW",
            "approved_amount": None,
            "confidence_score": 0.30,
            "decision_reason": (
                "Document extraction failed — Gemini could not process the submitted documents. "
                "Claim routed to manual review."
            ),
            "rejection_reasons": [],
            "failed_components": failed_components,
            "trace": {
                **state.get("trace", {}),
                "extraction": {
                    "agent": "extraction",
                    "single_gemini_call": True,
                    "document_count": len(documents),
                    "error": str(e),
                    "documents": trace_entries,
                },
            },
        }

    return {
        "extracted_documents": extracted,
        "extraction_complete": True,
        "extraction_failed": False,
        "patient_name_consistent": patient_name_consistent,
        "patient_name_mismatch_details": patient_name_mismatch_details,
        "failed_components": failed_components,
        "trace": {
            **state.get("trace", {}),
            "extraction": {
                "agent": "extraction",
                "single_gemini_call": True,
                "document_count": len(documents),
                "patient_name_consistent": patient_name_consistent,
                "documents": trace_entries,
            },
        },
    }
