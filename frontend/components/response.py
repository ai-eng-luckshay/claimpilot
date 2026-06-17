import streamlit as st
from config import DECISION_STYLE


def render_documents(documents: list[dict]) -> None:
    if not documents:
        return
    st.write("**Uploaded Documents**")
    cols = st.columns(min(len(documents), 3))
    for i, doc in enumerate(documents):
        col = cols[i % 3]
        url = doc.get("url")
        name = doc.get("file_name", f"Document {i+1}")
        doc_type = doc.get("doc_type", "")
        mime = doc.get("mime_type", "")

        col.caption(f"`{doc_type}` - {name}")
        if url:
            if mime and mime.startswith("image/"):
                col.image(url, width="stretch")
            else:
                col.markdown(f"[📄 View / Download]({url})")
        else:
            col.caption("_(test-mode doc - no file uploaded)_")


def render_response(response: dict) -> None:
    # Validation / document error
    if "error_type" in response:
        error_type = response.get("error_type", "")
        st.error(f"**{error_type.replace('_', ' ')}**")
        st.warning(response.get("message", "Validation failed."))

        if error_type == "DOCUMENT_UNREADABLE":
            fname = response.get("unreadable_file")
            if fname:
                st.info(f"Re-upload a clearer photo of: **{fname}**")

        elif error_type == "DOCUMENT_VALIDATION_FAILED":
            cols = st.columns(2)
            if response.get("what_was_uploaded"):
                cols[0].write("**AI detected in your upload:**")
                for t in response["what_was_uploaded"]:
                    cols[0].code(t)
            if response.get("what_is_required"):
                cols[1].write("**Required for this claim type:**")
                for t in response["what_is_required"]:
                    cols[1].code(t)
        return

    # Claim decision
    decision = response.get("decision", "PENDING")
    style = DECISION_STYLE.get(decision, DECISION_STYLE["PENDING"])

    st.markdown(
        f'<div style="background:{style["bg"]};color:white;padding:14px 28px;'
        f'border-radius:10px;font-size:26px;font-weight:700;display:inline-block;'
        f'margin-bottom:16px">{style["label"]}</div>',
        unsafe_allow_html=True,
    )

    m1, m2, m3 = st.columns(3)
    if response.get("approved_amount") is not None:
        m1.metric("Approved Amount", f"₹{float(response['approved_amount']):,.0f}")
    if response.get("confidence_score") is not None:
        m2.metric("Confidence", f"{float(response['confidence_score']):.0%}")
    if response.get("claim_id"):
        m3.metric("Claim ID", response["claim_id"][:8] + "...")

    if response.get("reason"):
        st.info(response["reason"])

    if response.get("rejection_reasons"):
        st.error("**Rejection reasons:** " + " | ".join(response["rejection_reasons"]))

    if response.get("failed_components"):
        st.warning(
            "⚠️ **Components skipped (graceful degradation):** "
            + ", ".join(response["failed_components"])
        )

    render_documents(response.get("documents", []))

    with st.expander("Full pipeline trace"):
        st.json(response.get("trace", {}))
