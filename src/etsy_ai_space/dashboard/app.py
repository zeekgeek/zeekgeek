"""Streamlit dashboard for Etsy AI Space swarm status."""

from __future__ import annotations

import json

from etsy_ai_space.db import StoreDatabase, default_db_path
from etsy_ai_space.pipeline.state_tracker import SwarmStateTracker, default_state_path

BADGE = {
    "healthy": "🟢 Active",
    "idle": "🟡 Idle",
    "warning": "🟡 Warning",
    "error": "🔴 Error",
}


def _status_badge(agent: dict) -> str:
    status = str(agent.get("status") or "Idle")
    health = str(agent.get("health") or "idle")
    if status.lower() == "error":
        return "🔴 Error"
    if status.lower() != "idle":
        return "🟢 Active"
    return BADGE.get(health, "🟡 Idle")


def _load_dashboard_state(tracker: SwarmStateTracker) -> dict:
    db_stats: dict = {}
    top_listings: list = []
    try:
        db = StoreDatabase(default_db_path())
        db_stats = db.stats()
        tracker.sync_metrics_from_db(db_stats)
        top_listings = db.top_listings(limit=15, min_score=0.0)
    except Exception:
        pass
    state = tracker.load()
    state["_db_stats"] = db_stats
    state["_top_listings"] = top_listings
    return state


def run_dashboard(*, refresh_seconds: int = 3) -> None:
    try:
        import os
        import streamlit as st
    except ImportError as exc:
        raise SystemExit(
            "Streamlit is required for the dashboard. Install with: pip install -e \".[etsy]\""
        ) from exc

    refresh_seconds = int(os.environ.get("ETSY_DASHBOARD_REFRESH", refresh_seconds))

    st.set_page_config(
        page_title="Etsy AI Swarm",
        page_icon="🛰️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    if refresh_seconds > 0:
        st.markdown(
            f'<meta http-equiv="refresh" content="{refresh_seconds}">',
            unsafe_allow_html=True,
        )

    tracker = SwarmStateTracker()
    state = _load_dashboard_state(tracker)
    metrics = state.get("metrics") or {}
    agents = state.get("agents") or []

    st.title("Etsy AI Swarm — Live Status")
    st.caption(f"State file: `{default_state_path()}` · auto-refresh every {refresh_seconds}s")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Scraped listings", int(metrics.get("scraped_listings") or state.get("_db_stats", {}).get("listings") or 0))
    c2.metric("Listing drafts", int(metrics.get("listings_generated") or 0))
    c3.metric("Scrape runs", int(metrics.get("scrape_runs") or 0))
    c4.metric("Successful uploads", int(metrics.get("successful_uploads") or 0))
    c5.metric("Revenue (USD)", f"${float(metrics.get('revenue_usd') or 0):.2f}")
    c6.metric("Compute cost (USD)", f"${float(metrics.get('compute_cost_usd') or 0):.4f}")
    success = int(metrics.get("successes") or 0)
    errors = int(metrics.get("errors") or 0)
    rate = (success / (success + errors) * 100) if (success + errors) else 100.0
    st.sidebar.metric("Agent success rate", f"{rate:.0f}%")

    st.subheader("Agent cards")
    cards = st.columns(min(len(agents) or 1, 5))
    for index, agent in enumerate(agents[:5]):
        with cards[index]:
            badge = _status_badge(agent)
            st.markdown(f"### {agent.get('name', 'Agent')}")
            st.markdown(f"**{badge}**")
            st.write(f"Status: `{agent.get('status', 'Idle')}`")
            st.write(f"Last active: `{agent.get('last_active', 'n/a')}`")
            st.progress(
                min(
                    1.0,
                    (int(agent.get("success_count") or 0))
                    / max(int(agent.get("success_count") or 0) + int(agent.get("error_count") or 0), 1),
                )
            )
            st.caption(
                f"✓ {agent.get('success_count', 0)} · ✗ {agent.get('error_count', 0)} · "
                f"health: {agent.get('health', 'idle')}"
            )

    top = state.get("_top_listings") or []
    if top:
        st.subheader("Top scraped listings (SQLite)")
        rows = [
            {
                "title": (row.get("title") or "")[:70],
                "score": row.get("performance_score"),
                "price": row.get("price_amount"),
                "reviews": row.get("review_count"),
                "shop": row.get("shop_name"),
            }
            for row in top
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info(
            "No scraped listings yet. Run: "
            "`python3 -m etsy_ai_space scrape \"recovery definition shirt\" --demo`"
        )

    st.subheader("Live log feed")
    log_text = tracker.tail_log_file(lines=100)
    st.text_area(
        "System log",
        value=log_text,
        height=260,
        disabled=True,
        label_visibility="collapsed",
    )

    with st.expander("Raw state.json"):
        st.code(json.dumps(state, indent=2), language="json")


def main() -> None:
    run_dashboard()


if __name__ == "__main__":
    main()
