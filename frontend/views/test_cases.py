import base64
import json

import streamlit as st

from api import submit_claim
from components.response import render_response
from config import TEST_CASES_PATH, TEST_DOCS_DIR

# Four format modes — three atomic types plus a realistic mixed mode:
#   images       — all JPEGs (photographed physical documents)
#   scanned_pdfs — all scanned PDFs (image inside PDF, no selectable text)
#   text_pdfs    — all text PDFs (selectable text, digitally created)
#   mixed        — prescriptions & lab reports as text PDFs (digital),
#                  bills & pharmacy receipts as JPEGs (photographed)

_TYPE_TO_FILENAME: dict[str, dict[str, str]] = {
    "PRESCRIPTION":      {"images": "prescription.jpg",      "scanned_pdfs": "prescription.pdf",      "text_pdfs": "prescription_text.pdf",      "mixed": "prescription_text.pdf"},
    "HOSPITAL_BILL":     {"images": "hospital_bill.jpg",     "scanned_pdfs": "hospital_bill.pdf",     "text_pdfs": "hospital_bill_text.pdf",     "mixed": "hospital_bill.jpg"},
    "LAB_REPORT":        {"images": "lab_report.jpg",        "scanned_pdfs": "lab_report.pdf",        "text_pdfs": "lab_report_text.pdf",        "mixed": "lab_report_text.pdf"},
    "PHARMACY_BILL":     {"images": "pharmacy_bill.jpg",     "scanned_pdfs": "pharmacy_bill.pdf",     "text_pdfs": "pharmacy_bill_text.pdf",     "mixed": "pharmacy_bill.jpg"},
    "DENTAL_REPORT":     {"images": "dental_report.jpg",     "scanned_pdfs": "dental_report.pdf",     "text_pdfs": "dental_report_text.pdf",     "mixed": "dental_report.jpg"},
    "DISCHARGE_SUMMARY": {"images": "discharge_summary.jpg", "scanned_pdfs": "discharge_summary.pdf", "text_pdfs": "discharge_summary_text.pdf", "mixed": "discharge_summary_text.pdf"},
}

_FORMAT_LABELS = ["images", "scanned_pdfs", "text_pdfs", "mixed"]

_FORMAT_DISPLAY = {
    "images":       "🖼 Images",
    "scanned_pdfs": "📄 Scanned PDFs",
    "text_pdfs":    "📝 Text PDFs",
    "mixed":        "🔀 Mixed",
}


def _load_test_cases() -> list[dict]:
    try:
        with open(TEST_CASES_PATH) as f:
            return json.load(f)["test_cases"]
    except Exception:
        return []


def _render_test_result(tc: dict, response: dict) -> None:
    expected = tc.get("expected", {})
    expected_decision = expected.get("decision")
    actual_decision = response.get("decision")
    is_validation_error = "error_type" in response

    if expected_decision is None and is_validation_error:
        st.success("✅ PASS - system correctly stopped before making a decision")
    elif expected_decision and actual_decision == expected_decision:
        st.success(f"✅ PASS - decision matches: **{actual_decision}**")
        exp_amount = expected.get("approved_amount")
        act_amount = response.get("approved_amount")
        if exp_amount and act_amount is not None:
            if abs(float(act_amount) - float(exp_amount)) < 1:
                st.success(f"✅ PASS - approved amount matches: ₹{act_amount:,.0f}")
            else:
                st.error(
                    f"❌ FAIL - amount mismatch: "
                    f"got ₹{float(act_amount):,.0f}, expected ₹{exp_amount:,}"
                )
    else:
        st.error(
            f"❌ FAIL - got **{actual_decision or is_validation_error and 'validation error'}**, "
            f"expected **{expected_decision or 'validation error'}**"
        )


def _resolve_filename(doc: dict, fmt: str) -> str:
    """Return the filename to load for this document given the chosen format."""
    actual_type = doc.get("actual_type", "")
    mapping = _TYPE_TO_FILENAME.get(actual_type, {})
    target = mapping.get(fmt, mapping.get("images", ""))

    explicit = doc.get("file_name")
    if not explicit:
        return target

    # TC001-TC003 have explicit file_names — apply the same suffix logic
    stem = explicit.rsplit(".", 1)[0]
    if target.endswith("_text.pdf"):
        return stem + "_text.pdf"
    if target.endswith(".pdf"):
        return stem + ".pdf"
    return explicit  # images — use original filename


def _build_smoke_payload(tc: dict, fmt: str = "images") -> tuple[dict | None, list[str]]:
    inp = tc["input"]
    tc_id = tc["case_id"]
    warnings: list[str] = []

    docs = []
    for doc in inp.get("documents", []):
        fname = _resolve_filename(doc, fmt)
        if not fname:
            warnings.append(f"Cannot determine filename for a doc in {tc_id} — skipping.")
            continue

        file_path = TEST_DOCS_DIR / tc_id / fname
        if not file_path.exists():
            warnings.append(f"Missing file: test_docs/{tc_id}/{fname} — run generate_test_docs.py")
            continue

        file_bytes = file_path.read_bytes()
        suffix = file_path.suffix.lower()
        mime = "application/pdf" if suffix == ".pdf" else "image/jpeg"

        docs.append({
            "file_name": fname,
            "file_data": base64.b64encode(file_bytes).decode(),
            "mime_type": mime,
        })

    if not docs:
        return None, warnings

    payload: dict = {
        "member_id": inp["member_id"],
        "policy_id": inp["policy_id"],
        "claim_category": inp["claim_category"],
        "treatment_date": inp["treatment_date"],
        "claimed_amount": inp["claimed_amount"],
        "documents": docs,
    }
    for opt in ("hospital_name", "claims_history", "simulate_component_failure", "ytd_claims_amount"):
        if inp.get(opt) is not None:
            payload[opt] = inp[opt]

    return payload, warnings


def render_test_cases_tab() -> None:
    st.subheader("Test Cases")
    st.caption(
        "Smoke-tests the full pipeline with real mock documents. "
        "Each test case loads files from `frontend/data/test_docs/` and sends them "
        "through Gemini — no pre-extracted content."
    )

    test_cases = _load_test_cases()
    if not test_cases:
        st.error("test_cases.json not found at `frontend/data/test_cases.json`.")
        return

    col_sel, col_fmt = st.columns([3, 1])
    options = {f"{tc['case_id']} - {tc['case_name']}": tc for tc in test_cases}
    selected_label = col_sel.selectbox("Select test case", list(options.keys()))
    fmt = col_fmt.radio(
        "Document format",
        _FORMAT_LABELS,
        format_func=lambda x: _FORMAT_DISPLAY[x],
        help=(
            "**🖼 Images** — JPEG photos of documents (blur gate active)\n\n"
            "**📄 Scanned PDFs** — image wrapped inside PDF (no selectable text)\n\n"
            "**📝 Text PDFs** — digitally created PDF with selectable text\n\n"
            "**🔀 Mixed** — prescriptions & lab reports as text PDFs, bills as JPEGs"
        ),
    )
    tc = options[selected_label]

    left, right = st.columns([2, 1])
    left.info(f"**{tc['case_id']}:** {tc['description']}")

    expected = tc.get("expected", {})
    if expected.get("decision"):
        right.metric("Expected Decision", expected["decision"])
    if expected.get("approved_amount"):
        right.metric("Expected Amount", f"₹{expected['approved_amount']:,}")
    if expected.get("system_must"):
        with right.expander("System must..."):
            for must in expected["system_must"]:
                st.write(f"* {must}")

    documents = tc["input"].get("documents", [])
    tc_id = tc["case_id"]
    st.write("**Documents to be sent through OCR pipeline:**")
    doc_cols = st.columns(max(len(documents), 1))
    all_present = True
    for i, doc in enumerate(documents):
        fname = _resolve_filename(doc, fmt)
        file_path = TEST_DOCS_DIR / tc_id / fname
        col = doc_cols[i % len(doc_cols)]
        col.caption(f"`{doc.get('actual_type', '?')}` — {fname}")
        if fname and file_path.exists():
            if file_path.suffix.lower() in (".jpg", ".jpeg", ".png"):
                col.image(str(file_path), width="stretch")
            else:
                col.info(f"📄 PDF ready: `{fname}`")
        else:
            col.error(f"Missing: {fname or '(unknown filename)'}")
            all_present = False

    if not all_present:
        st.warning(
            "Some files are missing. "
            "Run `python frontend/data/generate_test_docs.py` to generate them."
        )

    if st.button("▶ Run Smoke Test", type="primary", key="run_test", disabled=not all_present):
        payload, warnings = _build_smoke_payload(tc, fmt)
        for w in warnings:
            st.warning(w)
        if payload is None:
            st.error("No documents could be loaded — cannot run test.")
            return

        with st.spinner(f"Running {tc['case_id']} through Gemini pipeline ({fmt} mode)..."):
            status, response = submit_claim(payload)

        st.divider()
        st.write(f"**Response** (HTTP {status})")
        if status == 500:
            st.error(f"Server error: {response.get('detail', response)}")
        else:
            render_response(response)
            st.divider()
            _render_test_result(tc, response)
