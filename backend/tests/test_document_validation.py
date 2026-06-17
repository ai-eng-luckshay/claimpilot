"""Tests for blur_gate and validate_documents — TC001, TC002."""
from typing import Any
from unittest.mock import patch

from backend.src.agents.document_validation import blur_gate, validate_documents
from backend.tests.conftest import make_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_with_extracted(claim_category: str, extracted: list[dict]) -> Any:
    """Build state that already has extracted_documents (post-extraction)."""
    state: Any = make_state({"claim_category": claim_category, "documents": []})
    state["extracted_documents"] = extracted
    return state


# ---------------------------------------------------------------------------
# TC001 — Wrong document types
# ---------------------------------------------------------------------------

def test_tc001_wrong_types_rejected():
    """Two prescriptions for CONSULTATION (needs PRESCRIPTION + HOSPITAL_BILL) → fails."""
    state = _state_with_extracted("CONSULTATION", [
        {"classified_type": "PRESCRIPTION", "file_name": "rx1.jpg"},
        {"classified_type": "PRESCRIPTION", "file_name": "rx2.jpg"},
    ])
    result = validate_documents(state)

    assert result["validation_passed"] is False
    err = result["validation_error"]
    assert err["error_type"] == "DOCUMENT_VALIDATION_FAILED"
    assert "HOSPITAL_BILL" in err["what_is_required"]
    assert "PRESCRIPTION" in err["what_was_uploaded"]


def test_tc001_message_names_missing_and_required():
    """Error message must name the missing type and what is required."""
    state = _state_with_extracted("CONSULTATION", [
        {"classified_type": "PRESCRIPTION", "file_name": "rx.jpg"},
    ])
    result = validate_documents(state)
    msg = result["validation_error"]["message"]
    assert "HOSPITAL_BILL" in msg
    assert len(msg) > 40


def test_tc001_correct_consultation_docs_pass():
    """PRESCRIPTION + HOSPITAL_BILL for CONSULTATION → passes."""
    state = _state_with_extracted("CONSULTATION", [
        {"classified_type": "PRESCRIPTION", "file_name": "rx.jpg"},
        {"classified_type": "HOSPITAL_BILL", "file_name": "bill.jpg"},
    ])
    result = validate_documents(state)
    assert result["validation_passed"] is True
    assert result["validation_error"] is None


def test_tc001_correct_pharmacy_docs_pass():
    """PRESCRIPTION + PHARMACY_BILL for PHARMACY → passes."""
    state = _state_with_extracted("PHARMACY", [
        {"classified_type": "PRESCRIPTION", "file_name": "rx.jpg"},
        {"classified_type": "PHARMACY_BILL", "file_name": "pharma_bill.jpg"},
    ])
    result = validate_documents(state)
    assert result["validation_passed"] is True


def test_tc001_dental_requires_hospital_bill_not_dental_report():
    """DENTAL claim requires HOSPITAL_BILL — a DENTAL_REPORT alone is not enough."""
    state = _state_with_extracted("DENTAL", [
        {"classified_type": "DENTAL_REPORT", "file_name": "dental_chart.jpg"},
    ])
    result = validate_documents(state)
    # Should fail — HOSPITAL_BILL is required for DENTAL
    assert result["validation_passed"] is False
    assert "HOSPITAL_BILL" in result["validation_error"]["what_is_required"]


def test_tc001_trace_populated_on_pass():
    """Trace must be set with result=PASS after successful validation."""
    state = _state_with_extracted("CONSULTATION", [
        {"classified_type": "PRESCRIPTION", "file_name": "rx.jpg"},
        {"classified_type": "HOSPITAL_BILL", "file_name": "bill.jpg"},
    ])
    result = validate_documents(state)
    assert "document_validation" in result["trace"]
    assert result["trace"]["document_validation"]["result"] == "PASS"


def test_tc001_trace_populated_on_fail():
    """Trace must be set with result=FAIL after failed validation."""
    state = _state_with_extracted("CONSULTATION", [
        {"classified_type": "LAB_REPORT", "file_name": "lab.jpg"},
    ])
    result = validate_documents(state)
    assert result["trace"]["document_validation"]["result"] == "FAIL"


# ---------------------------------------------------------------------------
# TC002 — Blur gate
# ---------------------------------------------------------------------------

def test_tc002_blurry_image_stops_flow():
    """Low Laplacian variance → blur_gate fails with DOCUMENT_UNREADABLE."""
    state = make_state({"documents": [
        {"file_name": "blurry.jpg", "mime_type": "image/jpeg", "file_data": "AABB"},
    ]})
    with patch("backend.src.agents.document_validation._blur_variance", return_value=10.0):
        result = blur_gate(state)

    assert result["blur_check_passed"] is False
    err = result["blur_error"]
    assert err["error_type"] == "DOCUMENT_UNREADABLE"
    assert "blurry.jpg" in err["message"]
    assert "re-upload" in err["message"].lower() or "upload" in err["message"].lower()


def test_tc002_no_file_data_stops_flow():
    """Image with no file_data → blur_gate fails (not silently skipped)."""
    state = make_state({"documents": [
        {"file_name": "missing.jpg", "mime_type": "image/jpeg"},
    ]})
    result = blur_gate(state)
    assert result["blur_check_passed"] is False
    assert result["blur_error"]["error_type"] == "DOCUMENT_UNREADABLE"
    assert "missing.jpg" in result["blur_error"]["message"]


def test_tc002_pdf_always_passes_blur():
    """PDFs skip blur check — Gemini handles PDF readability internally."""
    state = make_state({"documents": [
        {"file_name": "report.pdf", "mime_type": "application/pdf", "file_data": "AABB"},
    ]})
    result = blur_gate(state)
    assert result["blur_check_passed"] is True


def test_tc002_pdf_with_no_data_also_passes():
    """PDF with no file_data still passes blur_gate (Gemini handles PDFs)."""
    state = make_state({"documents": [
        {"file_name": "report.pdf", "mime_type": "application/pdf"},
    ]})
    result = blur_gate(state)
    assert result["blur_check_passed"] is True


def test_tc002_sharp_image_passes():
    """High Laplacian variance → blur_gate passes."""
    state = make_state({"documents": [
        {"file_name": "clear.jpg", "mime_type": "image/jpeg", "file_data": "AABB"},
    ]})
    with patch("backend.src.agents.document_validation._blur_variance", return_value=250.0):
        result = blur_gate(state)
    assert result["blur_check_passed"] is True


def test_tc002_blur_gate_stops_on_first_blurry_doc():
    """If first doc is blurry, second is never checked — fail-fast."""
    state = make_state({"documents": [
        {"file_name": "blurry.jpg", "mime_type": "image/jpeg", "file_data": "AABB"},
        {"file_name": "clear.jpg", "mime_type": "image/jpeg", "file_data": "CCDD"},
    ]})
    call_count = 0

    def _fake_variance(data: str) -> float:
        nonlocal call_count
        call_count += 1
        return 10.0  # always blurry

    with patch("backend.src.agents.document_validation._blur_variance", side_effect=_fake_variance):
        result = blur_gate(state)

    assert result["blur_check_passed"] is False
    assert call_count == 1  # only first doc checked
