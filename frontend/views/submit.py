import base64
from datetime import date

import streamlit as st

from api import submit_claim
from components.response import render_response
from config import CLAIM_CATEGORIES


def render_submit_tab() -> None:
    st.subheader("Submit a Claim")

    with st.form("claim_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        member_id = c1.text_input("Member ID", value="EMP001")
        policy_id = c2.text_input("Policy ID", value="PLUM_GHI_2024", disabled=True)

        c3, c4 = st.columns(2)
        category = c3.selectbox("Claim Category", CLAIM_CATEGORIES)
        treatment_date = c4.date_input("Treatment Date", value=date(2024, 11, 1))

        c5, c6 = st.columns(2)
        claimed_amount = c5.number_input(
            "Claimed Amount (₹)", min_value=0.0, value=1500.0, step=100.0
        )
        hospital_name = c6.text_input(
            "Hospital Name (optional)", placeholder="e.g. Apollo Hospitals"
        )

        st.divider()
        st.write("**Documents** - upload up to 3 files | document type is detected automatically by AI")

        docs = []
        for i in range(3):
            uploaded = st.file_uploader(
                f"Document {i + 1}",
                type=["jpg", "jpeg", "png", "pdf"],
                key=f"doc_{i}",
            )
            if uploaded:
                docs.append({
                    "file_name": uploaded.name,
                    "file_data": base64.b64encode(uploaded.read()).decode(),
                    "mime_type": uploaded.type or "application/octet-stream",
                })

        submitted = st.form_submit_button(
            "Submit Claim", type="primary", width="stretch"
        )

    if submitted:
        if not docs:
            st.warning("Please upload at least one document.")
            return

        payload = {
            "member_id": member_id,
            "policy_id": policy_id,
            "claim_category": category,
            "treatment_date": str(treatment_date),
            "claimed_amount": float(claimed_amount),
            "hospital_name": hospital_name or None,
            "documents": docs,
        }

        with st.spinner("Processing claim..."):
            status, response = submit_claim(payload)

        st.divider()
        if status == 500:
            st.error(f"Server error: {response.get('detail', response)}")
        else:
            render_response(response)
