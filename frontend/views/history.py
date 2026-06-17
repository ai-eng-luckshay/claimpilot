import pandas as pd
import streamlit as st

from api import fetch_claims
from components.response import render_response
from config import DECISION_BADGE


def render_claims_history_tab() -> None:
    st.subheader("Claims History")

    col1, col2 = st.columns([3, 1])
    member_id = col1.text_input(
        "Member ID",
        value="",
        placeholder="e.g. EMP001 - leave blank to fetch all",
        key="hist_member_id",
    )
    fetch = col2.button("Fetch Claims", type="primary", width="stretch")

    if not fetch:
        st.caption("Enter a member ID and click Fetch to load claims.")
        return

    with st.spinner("Loading claims..."):
        status, claims = fetch_claims(member_id.strip() or None)

    if status != 200:
        st.error(f"API error {status}: {claims}")
        return

    if not claims:
        st.info(
            f"No claims found{' for member ' + member_id if member_id else ''}. "
            "Claims appear here after they are submitted and saved."
        )
        return

    st.caption(f"{len(claims)} claim(s) found")

    rows = []
    for c in claims:
        badge = DECISION_BADGE.get(c.get("decision", ""), "⚪")
        rows.append({
            "Claim ID": (c.get("claim_id") or "")[:8] + "...",
            "Member": c.get("member_id", "-"),
            "Category": c.get("claim_category", "-"),
            "Treatment Date": c.get("treatment_date", "-"),
            "Claimed (₹)": f"₹{float(c['claimed_amount']):,.0f}" if c.get("claimed_amount") else "-",
            "Decision": f"{badge} {c.get('decision', '-')}",
            "Approved (₹)": f"₹{float(c['approved_amount']):,.0f}" if c.get("approved_amount") else "-",
            "Confidence": f"{float(c['confidence_score']):.0%}" if c.get("confidence_score") else "-",
            "Submitted": (c.get("submitted_at") or "")[:16].replace("T", " "),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True)

    st.divider()
    st.write("**Claim Details**")

    for c in claims:
        cid = c.get("claim_id", "unknown")
        decision = c.get("decision", "PENDING")
        badge = DECISION_BADGE.get(decision, "⚪")
        label = (
            f"{badge} {decision}  |  {c.get('claim_category', '')}  |  "
            f"{c.get('member_id', '')}  |  {(cid or '')[:8]}..."
        )

        with st.expander(label):
            d1, d2, d3 = st.columns(3)
            d1.metric("Decision", decision)
            if c.get("approved_amount") is not None:
                d2.metric("Approved", f"₹{float(c['approved_amount']):,.0f}")
            if c.get("confidence_score") is not None:
                d3.metric("Confidence", f"{float(c['confidence_score']):.0%}")

            if c.get("reason"):
                st.info(c["reason"])

            if c.get("rejection_reasons"):
                st.error("**Rejection reasons:** " + " | ".join(c["rejection_reasons"]))

            if c.get("failed_components"):
                st.warning(
                    "⚠️ **Components skipped:** " + ", ".join(c["failed_components"])
                )

            docs = c.get("documents", [])
            if docs:
                st.write("**Documents**")
                img_cols = st.columns(min(len(docs), 3))
                for i, doc in enumerate(docs):
                    col = img_cols[i % 3]
                    col.caption(f"`{doc.get('doc_type', '')}` - {doc.get('file_name', '')}")
                    url = doc.get("url")
                    if url:
                        mime = doc.get("mime_type", "") or ""
                        if mime.startswith("image/") or url.lower().endswith(
                            (".jpg", ".jpeg", ".png")
                        ):
                            col.image(url, width="stretch")
                        else:
                            col.markdown(f"[📄 View / Download]({url})")

            with st.expander("Full trace"):
                st.json(c.get("trace", {}))
