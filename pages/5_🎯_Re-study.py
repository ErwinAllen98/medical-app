"""Layers 7-8 — source localisation and the targeted re-study plan."""

from __future__ import annotations

import streamlit as st

from secondbrain import diagnostics, restudy
from secondbrain.ui import empty_state, get_store, page, severity_badge

page(
    "Targeted re-study",
    "Never “review SGLT2 inhibitors”. Always: what you don't know, where it lives in your source, "
    "why it keeps failing, what to look at while re-reading — and what to ignore for now.",
    "🎯",
)

store = get_store()
plans = store.list_plans("OPEN")

col_a, col_b = st.columns([3, 1])
with col_b:
    if st.button("Rebuild plans from the current profile", width="stretch"):
        profile = diagnostics.build_profile(store)
        diagnostics.persist_hypotheses(store, profile)
        created = restudy.generate_plans(store, profile)
        st.success(f"{len(created)} plans refreshed.")
        st.rerun()

with col_a:
    st.metric("Open re-study plans", len(plans))

if not plans:
    empty_state(
        "No open plan.",
        "Either nothing is weak enough to need repair, or the weakness profile has not been built yet.",
    )
    st.stop()

profile = diagnostics.build_profile(store)

for plan in plans:
    ku = store.get_ku(plan.ku_id)
    if not ku:
        continue
    unit = profile.by_id(plan.ku_id)
    header = f"{ku.label}  ·  {', '.join(plan.error_types) or 'unclassified'}"
    with st.expander(header, expanded=plans.index(plan) == 0):
        if unit:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Failure rate", f"{unit.failure_rate:.0%}")
            c2.metric("Attempts", unit.attempts)
            c3.metric("Repeat streak", unit.repeated_failure_count)
            c4.markdown(severity_badge(unit.priority), unsafe_allow_html=True)

        st.markdown("#### 1 · WHAT you do not know")
        st.write(plan.what)

        st.markdown("#### 2 · WHERE to fix it")
        st.info(plan.where)

        st.markdown("#### 3 · WHY it keeps failing")
        st.write(plan.why)

        st.markdown("#### 4 · HOW to re-read")
        for step in plan.how:
            st.markdown(f"- {step}")

        st.caption(f"When you come back, the next questions will target cognitive level {plan.next_level}.")

        b1, b2, b3 = st.columns(3)
        if b1.button("✅ I have re-read this", key=f"done_{plan.id}"):
            store.complete_plan(plan.id)
            store.set_ku_status(plan.ku_id, "CONSOLIDATING")
            store.log_event("restudy_done", {"ku_id": plan.ku_id})
            st.success("Marked as re-read — now generate the adaptive questions on the next page.")
            st.rerun()
        b2.download_button(
            "⬇︎ Markdown",
            restudy.plan_to_markdown(store, plan),
            file_name=f"restudy_{plan.ku_id}.md",
            key=f"dl_{plan.id}",
        )
        if b3.button("🔁 Skip for now", key=f"skip_{plan.id}"):
            store.complete_plan(plan.id)
            st.rerun()
