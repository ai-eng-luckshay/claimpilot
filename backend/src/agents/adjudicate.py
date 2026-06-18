"""Adjudicator: single Gemini call for policy evaluation, fraud detection, and decision."""

import json
from typing import Literal, cast

from pydantic import BaseModel, Field

from backend.src.agents.prompts import ADJUDICATION_INSTRUCTIONS
from backend.src.config.logger_config import error_logger, application_logger
from backend.src.pipeline.state import ClaimState
from backend.src.services.llm import get_llm_service
from backend.src.services.policy import get_policy_context


class _DentalItem(BaseModel):
    description: str
    amount: float
    reason: str | None = None


class _ClaimDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED", "PARTIAL", "MANUAL_REVIEW"]
    approved_amount: float | None = None
    rejection_reasons: list[Literal[
        "MEMBER_NOT_FOUND",
        "PATIENT_NAME_MISMATCH",
        "INITIAL_WAITING_PERIOD",
        "EXCLUDED_CONDITION",
        "WAITING_PERIOD",
        "PRE_AUTH_MISSING",
        "PER_CLAIM_EXCEEDED",
        "ANNUAL_LIMIT_EXHAUSTED",
    ]] = Field(default_factory=list)
    rejection_messages: list[str] = Field(default_factory=list)
    decision_reason: str
    confidence_score: float
    warnings: list[str] = Field(default_factory=list)
    fraud_signals: list[str] = Field(default_factory=list)
    manual_review: bool = False
    eligibility_date: str | None = None
    dental_approved_items: list[_DentalItem] = Field(default_factory=list)
    dental_rejected_items: list[_DentalItem] = Field(default_factory=list)
    eligible_base: float = 0.0
    is_network_hospital: bool = False
    network_discount_percent: float = 0.0
    network_discount_amount: float = 0.0
    after_discount: float = 0.0
    copay_percent: float = 0.0
    copay_amount: float = 0.0


def _format_extracted_docs(extracted_docs: list[dict]) -> str:
    if not extracted_docs:
        return "No documents extracted."
    lines = []
    for i, doc in enumerate(extracted_docs, 1):
        lines.append(f"Document {i} ({doc.get('classified_type', 'UNKNOWN')}):")
        for key, label in [
            ("patient_name", "Patient"), ("diagnosis", "Diagnosis"),
            ("test_name", "Test"), ("hospital_name", "Hospital"),
        ]:
            if doc.get(key):
                lines.append(f"  {label}: {doc[key]}")
        if doc.get("medicines"):
            lines.append(f"  Medicines: {', '.join(doc['medicines'])}")
        if doc.get("line_items"):
            lines.append("  Line Items:")
            for li in doc["line_items"]:
                lines.append(f"    - {li.get('description', '?')}: ₹{li.get('amount', 0):,.2f}")
        if doc.get("total") is not None:
            lines.append(f"  Total: ₹{doc['total']:,.2f}")
        lines.append("")
    return "\n".join(lines)


def _format_claims_history(claims_history: list[dict]) -> str:
    if not claims_history:
        return "No prior claims history provided."
    return "\n".join(
        f"  {i + 1}. Date: {c.get('date', '?')}, "
        f"Provider: {c.get('provider', c.get('claim_id', '?'))}, "
        f"Amount: ₹{c.get('amount', '?')}"
        for i, c in enumerate(claims_history)
    )


def adjudicate_claim(state: ClaimState) -> dict:
    """LangGraph node: single Gemini call handles policy, fraud, and final decision."""
    request = state.get("request", {})
    extracted_docs = state.get("extracted_documents", [])
    failed_components = list(state.get("failed_components", []))
    trace = dict(state.get("trace", {}))

    claimed_amount = float(request.get("claimed_amount") or 0)
    member_id = request.get("member_id", "")
    claim_category = (request.get("claim_category") or "").upper()

    # ------------------------------------------------------------------
    # Simulated component failure (TC011) — Python guard only
    # ------------------------------------------------------------------
    if request.get("simulate_component_failure"):
        error_logger.warning("adjudicate_claim: simulate_component_failure — skipping Gemini")
        failed_components.append("policy_check")
        return {
            "decision": "APPROVED",
            "approved_amount": claimed_amount,
            "confidence_score": 0.60,
            "decision_reason": (
                "Policy check skipped due to a component failure — manual review recommended."
            ),
            "rejection_reasons": [],
            "failed_components": failed_components,
            "trace": {**trace, "adjudicate": {"skipped": True, "reason": "simulate_component_failure"}},
        }

    # ------------------------------------------------------------------
    # Load filtered policy context
    # ------------------------------------------------------------------
    try:
        policy_context = get_policy_context(member_id, claim_category)
    except Exception as e:
        error_logger.error("adjudicate_claim: policy load failed — %s", e)
        failed_components.append("adjudicate")
        return _graceful_pass(trace, failed_components, claimed_amount, str(e))

    # ------------------------------------------------------------------
    # Build prompt — f-string avoids .format() choking on JSON braces
    # ------------------------------------------------------------------
    prompt = (
        f"{ADJUDICATION_INSTRUCTIONS}\n\n"
        f"## Policy Context\n{json.dumps(policy_context, indent=2)}\n\n"
        f"## Claim Details\n"
        f"- Member ID: {member_id}\n"
        f"- Treatment Date: {request.get('treatment_date', '')}\n"
        f"- Claim Category: {claim_category}\n"
        f"- Claimed Amount: ₹{claimed_amount:,.2f}\n"
        f"- Hospital Name: {request.get('hospital_name') or '(not specified)'}\n"
        f"- Year-to-Date Claims Amount: ₹{float(request.get('ytd_claims_amount') or 0):,.2f}\n"
        f"- Failed Pipeline Components So Far: {failed_components or 'none'}\n\n"
        f"## Claims History (for fraud detection)\n"
        f"{_format_claims_history(request.get('claims_history') or [])}\n\n"
        f"## Extracted Medical Documents\n"
        f"{_format_extracted_docs(extracted_docs)}"
    )

    # ------------------------------------------------------------------
    # LLM call (provider-agnostic)
    # ------------------------------------------------------------------
    try:
        # structured_call returns a pydantic BaseModel; cast to our specific model for typing
        result = cast(_ClaimDecision, get_llm_service().structured_call(prompt, _ClaimDecision))
    except Exception as e:
        error_logger.error("adjudicate_claim: Gemini call failed — %s", e)
        failed_components.append("adjudicate")
        return _graceful_pass(trace, failed_components, claimed_amount, str(e))

    # ------------------------------------------------------------------
    # Confidence gate — override optimistic decisions when Gemini is unsure
    # REJECTED / MANUAL_REVIEW are always honored regardless of confidence.
    # ------------------------------------------------------------------
    final_decision = result.decision
    final_approved_amount = result.approved_amount
    confidence_override_reason: str | None = None

    if result.decision in ("APPROVED", "PARTIAL"):
        if result.confidence_score < 0.50:
            final_decision = "REJECTED"
            final_approved_amount = None
            confidence_override_reason = (
                f"Confidence too low ({result.confidence_score:.0%}) to approve — auto-rejected."
            )
        elif result.confidence_score < 0.75:
            final_decision = "MANUAL_REVIEW"
            final_approved_amount = None
            confidence_override_reason = (
                f"Confidence below threshold ({result.confidence_score:.0%}) — routed to manual review."
            )

    if confidence_override_reason:
        error_logger.warning(
            "adjudicate_claim: confidence override decision=%s→%s confidence=%.2f",
            result.decision, final_decision, result.confidence_score,
        )

    application_logger.info(
        "adjudicate_claim: decision=%s approved=%s confidence=%.2f reasons=%s",
        final_decision, final_approved_amount, result.confidence_score, result.rejection_reasons,
    )

    return {
        "decision": final_decision,
        "approved_amount": final_approved_amount,
        "confidence_score": result.confidence_score,
        "decision_reason": confidence_override_reason or result.decision_reason,
        "rejection_reasons": list(result.rejection_reasons),
        "failed_components": failed_components,
        "trace": {
            **trace,
            "adjudicate": {
                "decision": final_decision,
                "gemini_decision": result.decision if confidence_override_reason else None,
                "confidence_override": confidence_override_reason,
                "approved_amount": final_approved_amount,
                "confidence_score": result.confidence_score,
                "rejection_reasons": list(result.rejection_reasons),
                "fraud_signals": result.fraud_signals,
                "eligibility_date": result.eligibility_date,
                "warnings": result.warnings,
                "calculation": {
                    "claimed_amount": claimed_amount,
                    "eligible_base": result.eligible_base,
                    "is_network_hospital": result.is_network_hospital,
                    "network_discount_percent": result.network_discount_percent,
                    "network_discount_amount": result.network_discount_amount,
                    "after_discount": result.after_discount,
                    "copay_percent": result.copay_percent,
                    "copay_amount": result.copay_amount,
                    "final_approved": result.approved_amount or 0.0,
                },
                "dental_approved": [i.model_dump() for i in result.dental_approved_items],
                "dental_rejected": [i.model_dump() for i in result.dental_rejected_items],
            },
        },
    }


def _graceful_pass(
    trace: dict, failed_components: list[str], claimed_amount: float, reason: str
) -> dict:
    return {
        "decision": "MANUAL_REVIEW",
        "approved_amount": None,
        "confidence_score": 0.50,
        "decision_reason": f"Adjudication unavailable ({reason}) — routed to manual review.",
        "rejection_reasons": [],
        "failed_components": failed_components,
        "trace": {**trace, "adjudicate": {"skipped": True, "reason": reason}},
    }
