"""Tests for extract_documents (LLM mocked) and reject_patient_mismatch node.

TC003 (patient name mismatch) is now detected by the extraction Gemini call,
surfaced via patient_name_consistent=False, and handled by reject_patient_mismatch node.
"""
from typing import Literal, cast
from unittest.mock import patch

import pytest

from backend.src.agents.extraction import (
    _AllDocumentsExtraction,
    _DocumentExtraction,
    extract_documents,
    reject_patient_mismatch,
)
from backend.src.pipeline.state import ClaimState
from backend.tests.conftest import make_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_result(
    extractions: list[_DocumentExtraction],
    patient_name_consistent: bool = True,
    patient_name_mismatch_details: str | None = None,
) -> _AllDocumentsExtraction:
    return _AllDocumentsExtraction(
        documents=extractions,
        patient_name_consistent=patient_name_consistent,
        patient_name_mismatch_details=patient_name_mismatch_details,
    )


def _doc(
    classified_type: Literal[
        "PRESCRIPTION", "HOSPITAL_BILL", "LAB_REPORT", "PHARMACY_BILL",
        "DENTAL_REPORT", "DISCHARGE_SUMMARY", "UNKNOWN",
    ] = "PRESCRIPTION",
    patient_name: str | None = "Rajesh Kumar",
    confidence: float = 0.9,
    **kwargs,
) -> _DocumentExtraction:
    return _DocumentExtraction(
        classified_type=classified_type,
        patient_name=patient_name,
        confidence=confidence,
        **kwargs,
    )


def _state_one_doc() -> ClaimState:
    return make_state({
        "claim_category": "CONSULTATION",
        "documents": [{"file_name": "rx.jpg", "mime_type": "image/jpeg", "file_data": "AABB"}],
    })


# ---------------------------------------------------------------------------
# extract_documents — LLM mocked
# ---------------------------------------------------------------------------

def test_extraction_sets_classified_type():
    """extract_documents maps LLM output to classified_type field."""
    state = _state_one_doc()
    mock_result = _fake_result([_doc("PRESCRIPTION", "Rajesh Kumar", 0.9)])
    with patch("backend.src.agents.extraction._call_llm", return_value=mock_result):
        result = extract_documents(state)

    assert result["extraction_complete"] is True
    docs = result["extracted_documents"]
    assert len(docs) == 1
    assert docs[0]["classified_type"] == "PRESCRIPTION"
    assert docs[0]["patient_name"] == "Rajesh Kumar"
    assert docs[0]["overall_confidence"] == pytest.approx(0.9)


def test_extraction_pads_missing_docs_as_unknown():
    """LLM returning fewer results than docs → pad with UNKNOWN at confidence 0."""
    state = make_state({
        "claim_category": "CONSULTATION",
        "documents": [
            {"file_name": "rx.jpg", "mime_type": "image/jpeg", "file_data": "AABB"},
            {"file_name": "bill.jpg", "mime_type": "image/jpeg", "file_data": "CCDD"},
        ],
    })
    mock_result = _fake_result([_doc("PRESCRIPTION", "Rajesh Kumar", 0.8)])
    with patch("backend.src.agents.extraction._call_llm", return_value=mock_result):
        result = extract_documents(state)

    docs = result["extracted_documents"]
    assert len(docs) == 2
    assert docs[1]["classified_type"] == "UNKNOWN"
    assert docs[1]["overall_confidence"] == pytest.approx(0.0)


def test_extraction_truncates_extra_llm_results():
    """LLM returning more results than docs → extra results are ignored."""
    state = _state_one_doc()
    mock_result = _fake_result([_doc("PRESCRIPTION"), _doc("HOSPITAL_BILL")])
    with patch("backend.src.agents.extraction._call_llm", return_value=mock_result):
        result = extract_documents(state)
    assert len(result["extracted_documents"]) == 1


def test_extraction_graceful_on_llm_error():
    """LLM failure → extraction_agent in failed_components, UNKNOWN stubs, name check assumed OK."""
    state = _state_one_doc()
    with patch("backend.src.agents.extraction._call_llm",
               side_effect=Exception("Network timeout")):
        result = extract_documents(state)

    assert result["extraction_complete"] is True
    assert "extraction_agent" in result["failed_components"]
    assert result["extracted_documents"][0]["classified_type"] == "UNKNOWN"
    assert result["patient_name_consistent"] is True  # safe default on failure


def test_extraction_trace_populated():
    """Trace must contain extraction entry with document_count and name_consistent."""
    state = _state_one_doc()
    mock_result = _fake_result([_doc()])
    with patch("backend.src.agents.extraction._call_llm", return_value=mock_result):
        result = extract_documents(state)
    assert result["trace"]["extraction"]["document_count"] == 1
    assert result["trace"]["extraction"]["patient_name_consistent"] is True


def test_extraction_preserves_all_fields():
    """All fields from _DocumentExtraction are mapped to ExtractedDocument."""
    state = _state_one_doc()
    ext = _doc(
        classified_type="HOSPITAL_BILL",
        patient_name="Priya Nair",
        hospital_name="Apollo Hospital",
        diagnosis="Fracture",
        confidence=0.85,
    )
    with patch("backend.src.agents.extraction._call_llm",
               return_value=_fake_result([ext])):
        result = extract_documents(state)
    doc = result["extracted_documents"][0]
    assert doc["hospital_name"] == "Apollo Hospital"
    assert doc["diagnosis"] == "Fracture"
    assert doc["patient_name"] == "Priya Nair"


# ---------------------------------------------------------------------------
# TC003 — Patient name mismatch detected by extraction Gemini
# ---------------------------------------------------------------------------

def test_tc003_name_mismatch_sets_flag():
    """Gemini returning patient_name_consistent=False → state flag is set."""
    state = make_state({
        "claim_category": "CONSULTATION",
        "documents": [
            {"file_name": "rx.jpg", "mime_type": "image/jpeg", "file_data": "AABB"},
            {"file_name": "bill.jpg", "mime_type": "image/jpeg", "file_data": "CCDD"},
        ],
    })
    mock_result = _fake_result(
        [_doc("PRESCRIPTION", "Rajesh Kumar"), _doc("HOSPITAL_BILL", "Arjun Mehta")],
        patient_name_consistent=False,
        patient_name_mismatch_details="rx.jpg: Rajesh Kumar; bill.jpg: Arjun Mehta",
    )
    with patch("backend.src.agents.extraction._call_llm", return_value=mock_result):
        result = extract_documents(state)

    assert result["patient_name_consistent"] is False
    assert "Rajesh Kumar" in result["patient_name_mismatch_details"]
    assert "Arjun Mehta" in result["patient_name_mismatch_details"]


def test_reject_patient_mismatch_node_returns_rejected():
    """reject_patient_mismatch node produces REJECTED with PATIENT_NAME_MISMATCH reason."""
    state = cast(ClaimState, {
        "request": {},
        "patient_name_mismatch_details": "rx.jpg: Rajesh Kumar; bill.jpg: Arjun Mehta",
        "failed_components": [],
        "trace": {},
    })
    result = reject_patient_mismatch(state)

    assert result["decision"] == "REJECTED"
    assert result["approved_amount"] is None
    assert "PATIENT_NAME_MISMATCH" in result["rejection_reasons"]
    assert "Rajesh Kumar" in result["decision_reason"]
    assert result["trace"]["patient_name_check"]["result"] == "FAIL"


def test_reject_patient_mismatch_preserves_existing_trace():
    """reject_patient_mismatch appends to existing trace, not overwrites it."""
    state = cast(ClaimState, {
        "request": {},
        "patient_name_mismatch_details": "names differ",
        "failed_components": [],
        "trace": {"extraction": {"document_count": 2}},
    })
    result = reject_patient_mismatch(state)
    assert "extraction" in result["trace"]
    assert "patient_name_check" in result["trace"]
