"""ClaimPilot - Streamlit frontend entry point."""
import streamlit as st

from api import call_health
from config import API_URL
from views.history import render_claims_history_tab
from views.submit import render_submit_tab
from views.test_cases import render_test_cases_tab

st.set_page_config(
    page_title="ClaimPilot",
    page_icon="🏥",
    layout="wide",
)


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## 🏥 ClaimPilot")
        st.caption("AI-powered health insurance claims | Plum")
        st.divider()

        health = call_health()
        if health:
            db_ok = health.get("db", {}).get("connected", False)
            st.success("API online")
            c1, c2 = st.columns(2)
            c1.metric("Version", health.get("version", "-"))
            c2.metric("Env", health.get("environment", "-"))
            st.markdown(
                "🟢 Database connected" if db_ok else "🔴 Database disconnected"
            )
        else:
            st.error("API offline")

        st.divider()
        st.caption(f"`{API_URL}`")


def main() -> None:
    _render_sidebar()
    tab1, tab2, tab3 = st.tabs(["📋 Submit Claim", "🧪 Test Cases", "📂 Claims History"])
    with tab1:
        render_submit_tab()
    with tab2:
        render_test_cases_tab()
    with tab3:
        render_claims_history_tab()


if __name__ == "__main__":
    main()
