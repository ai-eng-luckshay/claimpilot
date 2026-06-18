"""LangGraph pipeline — wires all agents together."""
from langgraph.graph import StateGraph, END

from backend.src.pipeline.state import ClaimState
from backend.src.agents.document_validation import blur_gate, validate_documents
from backend.src.agents.extraction import extract_documents, reject_patient_mismatch
from backend.src.agents.adjudicate import adjudicate_claim
from backend.src.agents.decision import save_to_db


def _route_after_blur(state: ClaimState) -> str:
    return END if not state.get("blur_check_passed", True) else "extract_documents"


def _route_after_extraction(state: ClaimState) -> str:
    if state.get("extraction_failed"):
        return "save_to_db"  # decision already set to MANUAL_REVIEW in extraction node
    if not state.get("patient_name_consistent", True):
        return "reject_patient_mismatch"
    return "validate_documents"


def _route_after_validation(state: ClaimState) -> str:
    return END if not state.get("validation_passed", False) else "adjudicate_claim"


def build_pipeline():
    workflow = StateGraph(ClaimState)

    workflow.add_node("blur_gate", blur_gate)
    workflow.add_node("extract_documents", extract_documents)
    workflow.add_node("validate_documents", validate_documents)
    workflow.add_node("reject_patient_mismatch", reject_patient_mismatch)
    workflow.add_node("adjudicate_claim", adjudicate_claim)
    workflow.add_node("save_to_db", save_to_db)

    workflow.set_entry_point("blur_gate")

    workflow.add_conditional_edges(
        "blur_gate",
        _route_after_blur,
        {END: END, "extract_documents": "extract_documents"},
    )
    workflow.add_conditional_edges(
        "extract_documents",
        _route_after_extraction,
        {
            "save_to_db": "save_to_db",
            "reject_patient_mismatch": "reject_patient_mismatch",
            "validate_documents": "validate_documents",
        },
    )
    workflow.add_edge("reject_patient_mismatch", "save_to_db")
    workflow.add_conditional_edges(
        "validate_documents",
        _route_after_validation,
        {END: END, "adjudicate_claim": "adjudicate_claim"},
    )
    workflow.add_edge("adjudicate_claim", "save_to_db")
    workflow.add_edge("save_to_db", END)

    return workflow.compile()


pipeline = build_pipeline()
