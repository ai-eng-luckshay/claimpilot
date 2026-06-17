import base64
import json

import streamlit as st

from api import submit_claim
from components.response import render_response
from config import TEST_CASES_PATH, TEST_DOCS_DIR

# TC004-TC012 docs have no explicit file_name — derive from actual_type
_TYPE_TO_FILENAME = {
    "PRESCRIPTION": "prescription.jpg",
    "HOSPITAL_BILL": "hospital_bill.jpg",
    "LAB_REPORT": "lab_report.jpg",
    "PHARMACY_BILL": "pharmacy_bill.jpg",
    "DENTAL_REPORT": "dental_report.jpg",
    "DISCHARGE_SUMMARY": "discharge_summary.jpg",
    "DIAGNOSTIC_REPORT": "diagnostic_report.jpg",
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


def _build_smoke_payload(tc: dict) -> tuple[dict | None, list[str]]:
    inp = tc["input"]
    tc_id = tc["case_id"]
    warnings: list[str] = []

    docs = []
    for doc in inp.get("documents", []):
        # TC001-TC003 have explicit file_name; TC004-TC012 derive from actual_type
        fname = doc.get("file_name") or _TYPE_TO_FILENAME.get(doc.get("actual_type", ""), "")
        if not fname:
            warnings.append(f"Cannot determine filename for a doc in {tc_id} — skipping.")
            continue

        img_path = TEST_DOCS_DIR / tc_id / fname
        if not img_path.exists():
            warnings.append(f"Missing mock image: test_docs/{tc_id}/{fname}")
            continue

        file_bytes = img_path.read_bytes()
        suffix = img_path.suffix.lower()
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
        "Smoke-tests the full pipeline with real mock images. "
        "Each test case loads its images from `frontend/data/test_docs/` and sends them "
        "through Gemini OCR - no pre-extracted content."
    )

    test_cases = _load_test_cases()
    if not test_cases:
        st.error("test_cases.json not found at `frontend/data/test_cases.json`.")
        return

    options = {f"{tc['case_id']} - {tc['case_name']}": tc for tc in test_cases}
    selected_label = st.selectbox("Select test case", list(options.keys()))
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
    st.write("**Mock images to be sent through OCR pipeline:**")
    img_cols = st.columns(max(len(documents), 1))
    all_images_present = True
    for i, doc in enumerate(documents):
        fname = doc.get("file_name") or _TYPE_TO_FILENAME.get(doc.get("actual_type", ""), "")
        img_path = TEST_DOCS_DIR / tc_id / fname
        col = img_cols[i % len(img_cols)]
        col.caption(f"`{doc.get('actual_type', '?')}` — {fname}")
        if fname and img_path.exists() and img_path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            col.image(str(img_path), width='stretch')
        elif fname and img_path.exists():
            col.code(fname)
        else:
            col.error(f"Missing: {fname or '(unknown filename)'}")
            all_images_present = False

    if not all_images_present:
        st.warning(
            "Some mock images are missing. "
            "Run `python frontend/data/generate_test_docs.py` to generate them."
        )

    if st.button("▶ Run Smoke Test", type="primary", key="run_test", disabled=not all_images_present):
        payload, warnings = _build_smoke_payload(tc)
        for w in warnings:
            st.warning(w)
        if payload is None:
            st.error("No documents could be loaded - cannot run test.")
            return

        with st.spinner(f"Running {tc['case_id']} through Gemini OCR pipeline..."):
            status, response = submit_claim(payload)

        st.divider()
        st.write(f"**Response** (HTTP {status})")
        if status == 500:
            st.error(f"Server error: {response.get('detail', response)}")
        else:
            render_response(response)
            st.divider()
            _render_test_result(tc, response)
