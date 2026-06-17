"""Tests for adjudicate_claim node — TC011, mocked approve/reject/manual_review."""
from typing import Any
from unittest.mock import patch

import pytest

from backend.src.agents.adjudicate import adjudicate_claim, _ClaimDecision
from backend.src.pipeline.state import ClaimState
from backend.tests.conftest import make_state

_STUB_POLICY_CONTEXT: dict = {
    "member": None,
    "coverage": {},
    "claim_category": "CONSULTATION",
    "claim_category_config": None,
    "waiting_periods": {},
    "exclusions": {},
    "pre_authorization": {},
    "network_hospitals": [],
    "fraud_thresholds": {},
}


@pytest.fixture(autouse=True)
def _patch_policy_context():
    with patch(
        "backend.src.agents.adjudicate.get_policy_context",
        return_value=_STUB_POLICY_CONTEXT,
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(request_override: dict | None = None, extracted_docs: list | None = None) -> ClaimState:
    base = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2025-06-01",
        "claimed_amount": 1500,
        "hospital_name": "City Clinic",
        "ytd_claims_amount": 0,
        "claims_history": [],
    }
    if request_override:
        base.update(request_override)
    state = make_state(base)
    state["extracted_documents"] = extracted_docs or []
    return state


def _decision(**overrides: Any) -> _ClaimDecision:
    defaults: dict[str, Any] = dict(
        decision="APPROVED",
        approved_amount=1350.0,
        rejection_reasons=[],
        rejection_messages=[],
        decision_reason="All policy checks passed.",
        confidence_score=0.90,
        warnings=[],
        fraud_signals=[],
        manual_review=False,
        eligibility_date=None,
        dental_approved_items=[],
        dental_rejected_items=[],
        eligible_base=1500.0,
        is_network_hospital=False,
        network_discount_percent=0.0,
        network_discount_amount=0.0,
        after_discount=1500.0,
        copay_percent=10.0,
        copay_amount=150.0,
    )
    defaults.update(overrides)
    return _ClaimDecision(**defaults)


# ---------------------------------------------------------------------------
# TC011 — simulate_component_failure (pure Python, no LLM)
# ---------------------------------------------------------------------------

def test_tc011_simulate_failure_skips_gemini():
    """TC011: flag set → Python short-circuit, no LLM call, APPROVED with low confidence."""
    state = _state({"simulate_component_failure": True})
    result = adjudicate_claim(state)

    assert result["decision"] == "APPROVED"
    assert result["approved_amount"] == pytest.approx(1500.0)
    assert result["confidence_score"] == pytest.approx(0.60)
    assert "policy_check" in result["failed_components"]


def test_tc011_trace_shows_skipped():
    """TC011: trace must record adjudicate.skipped=True."""
    state = _state({"simulate_component_failure": True})
    result = adjudicate_claim(state)
    assert result["trace"]["adjudicate"]["skipped"] is True
    assert result["trace"]["adjudicate"]["reason"] == "simulate_component_failure"


# ---------------------------------------------------------------------------
# Graceful degradation — LLM failure
# ---------------------------------------------------------------------------

def test_graceful_pass_on_llm_exception():
    """LLM throws → adjudicate in failed_components, APPROVED at confidence 0.50."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.side_effect = Exception("Gemini timeout")
        result = adjudicate_claim(state)

    assert result["decision"] == "APPROVED"
    assert result["confidence_score"] == pytest.approx(0.50)
    assert "adjudicate" in result["failed_components"]


def test_graceful_pass_on_policy_load_failure():
    """Policy file unreadable → adjudicate in failed_components, APPROVED at 0.50."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_policy_context",
               side_effect=FileNotFoundError("policy_terms.json missing")):
        result = adjudicate_claim(state)

    assert result["decision"] == "APPROVED"
    assert result["confidence_score"] == pytest.approx(0.50)
    assert "adjudicate" in result["failed_components"]


# ---------------------------------------------------------------------------
# APPROVED decision
# ---------------------------------------------------------------------------

def test_approved_returns_all_required_state_keys():
    """Successful APPROVED at high confidence passes through unchanged."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision()
        result = adjudicate_claim(state)

    assert result["decision"] == "APPROVED"
    assert result["approved_amount"] == pytest.approx(1350.0)
    assert result["confidence_score"] == pytest.approx(0.90)
    assert result["decision_reason"] == "All policy checks passed."
    assert "adjudicate" in result["trace"]


# ---------------------------------------------------------------------------
# Confidence gate
# ---------------------------------------------------------------------------

def test_approved_low_confidence_overrides_to_manual_review():
    """APPROVED with confidence 0.50–0.74 → overridden to MANUAL_REVIEW."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision(confidence_score=0.65)
        result = adjudicate_claim(state)

    assert result["decision"] == "MANUAL_REVIEW"
    assert result["approved_amount"] is None
    assert "0.65" in result["decision_reason"] or "65%" in result["decision_reason"]
    assert result["trace"]["adjudicate"]["gemini_decision"] == "APPROVED"


def test_approved_very_low_confidence_overrides_to_rejected():
    """APPROVED with confidence < 0.50 → overridden to REJECTED."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision(confidence_score=0.40)
        result = adjudicate_claim(state)

    assert result["decision"] == "REJECTED"
    assert result["approved_amount"] is None
    assert result["trace"]["adjudicate"]["gemini_decision"] == "APPROVED"


def test_rejected_high_confidence_not_upgraded():
    """REJECTED is always honored — confidence gate does not upgrade conservative decisions."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision(
            decision="REJECTED",
            approved_amount=None,
            rejection_reasons=["WAITING_PERIOD"],
            decision_reason="Waiting period not elapsed.",
            confidence_score=0.95,
            eligible_base=0.0,
            after_discount=0.0,
            copay_amount=0.0,
        )
        result = adjudicate_claim(state)

    assert result["decision"] == "REJECTED"
    assert result["trace"]["adjudicate"]["confidence_override"] is None


def test_manual_review_low_confidence_not_changed():
    """MANUAL_REVIEW is always honored regardless of confidence score."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision(
            decision="MANUAL_REVIEW",
            approved_amount=None,
            manual_review=True,
            confidence_score=0.30,
            eligible_base=0.0,
            after_discount=0.0,
            copay_amount=0.0,
            decision_reason="Flagged for review.",
        )
        result = adjudicate_claim(state)

    assert result["decision"] == "MANUAL_REVIEW"
    assert result["trace"]["adjudicate"]["confidence_override"] is None


def test_approved_trace_has_calculation_block():
    """Trace calculation block must include claimed_amount, copay, final_approved."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision()
        result = adjudicate_claim(state)

    calc = result["trace"]["adjudicate"]["calculation"]
    assert calc["claimed_amount"] == pytest.approx(1500.0)
    assert calc["copay_percent"] == pytest.approx(10.0)
    assert calc["final_approved"] == pytest.approx(1350.0)


# ---------------------------------------------------------------------------
# REJECTED decision
# ---------------------------------------------------------------------------

def test_rejected_includes_rejection_reasons():
    """REJECTED must propagate rejection_reasons list."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision(
            decision="REJECTED",
            approved_amount=None,
            rejection_reasons=["WAITING_PERIOD"],
            decision_reason="Diabetes 90-day waiting period not elapsed.",
            confidence_score=0.88,
            eligible_base=0.0,
            after_discount=0.0,
            copay_amount=0.0,
        )
        result = adjudicate_claim(state)

    assert result["decision"] == "REJECTED"
    assert result["approved_amount"] is None
    assert "WAITING_PERIOD" in result["rejection_reasons"]


def test_rejected_eligibility_date_surfaced():
    """REJECTED with eligibility_date → date visible in trace."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision(
            decision="REJECTED",
            approved_amount=None,
            rejection_reasons=["INITIAL_WAITING_PERIOD"],
            decision_reason="30-day initial waiting period.",
            eligibility_date="2025-05-01",
            confidence_score=0.92,
            eligible_base=0.0,
            after_discount=0.0,
            copay_amount=0.0,
        )
        result = adjudicate_claim(state)

    assert result["trace"]["adjudicate"]["eligibility_date"] == "2025-05-01"


# ---------------------------------------------------------------------------
# MANUAL_REVIEW decision
# ---------------------------------------------------------------------------

def test_manual_review_has_null_approved_amount():
    """MANUAL_REVIEW must have approved_amount=None."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision(
            decision="MANUAL_REVIEW",
            approved_amount=None,
            manual_review=True,
            fraud_signals=["3 same-day claims detected"],
            decision_reason="Fraud pattern — routes to manual review.",
            confidence_score=0.60,
            eligible_base=0.0,
            after_discount=0.0,
            copay_amount=0.0,
        )
        result = adjudicate_claim(state)

    assert result["decision"] == "MANUAL_REVIEW"
    assert result["approved_amount"] is None


def test_manual_review_fraud_signals_in_trace():
    """Fraud signals must appear in the adjudicate trace."""
    state = _state()
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision(
            decision="MANUAL_REVIEW",
            approved_amount=None,
            manual_review=True,
            fraud_signals=["same-day duplicate claim"],
            decision_reason="Flagged for review.",
            confidence_score=0.65,
            eligible_base=0.0,
            after_discount=0.0,
            copay_amount=0.0,
        )
        result = adjudicate_claim(state)

    assert result["trace"]["adjudicate"]["fraud_signals"] == ["same-day duplicate claim"]


# ---------------------------------------------------------------------------
# PARTIAL (dental) decision
# ---------------------------------------------------------------------------

def test_partial_dental_approved_and_rejected_items():
    """PARTIAL dental claim must surface approved and rejected dental items in trace."""
    from backend.src.agents.adjudicate import _DentalItem
    state = _state({"claim_category": "DENTAL"})
    approved_item = _DentalItem(description="Root Canal", amount=8000.0)
    rejected_item = _DentalItem(description="Teeth Whitening", amount=2000.0,
                                reason="Cosmetic — excluded")
    with patch("backend.src.agents.adjudicate.get_llm_service") as mock_svc:
        mock_svc.return_value.structured_call.return_value = _decision(
            decision="PARTIAL",
            approved_amount=7200.0,
            dental_approved_items=[approved_item],
            dental_rejected_items=[rejected_item],
            eligible_base=8000.0,
            after_discount=8000.0,
            copay_amount=800.0,
            decision_reason="Root Canal approved. Teeth Whitening excluded (cosmetic).",
            confidence_score=0.88,
        )
        result = adjudicate_claim(state)

    assert result["decision"] == "PARTIAL"
    approved = result["trace"]["adjudicate"]["dental_approved"]
    rejected = result["trace"]["adjudicate"]["dental_rejected"]
    assert approved[0]["description"] == "Root Canal"
    assert rejected[0]["description"] == "Teeth Whitening"
