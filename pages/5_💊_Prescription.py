"""The Learning Prescription — WHAT · WHY · WHERE · WHAT TO STUDY · HOW · HOW MUCH.

This page also closes the loop: it hands you the NotebookLM prompt that turns the
diagnosed gap back into new, targeted learning material.
"""

from __future__ import annotations

import streamlit as st

from secondbrain import diagnostics, lifecycle, prescription
from secondbrain.taxonomy import LEARNING_METHODS
from secondbrain.ui import copy_button, empty_state, get_store, nav_link, open_notebooklm, page

page(
    "Learning prescription",
    "Minimum necessary learning, maximum knowledge gain — exactly what to read, how, and how much.",
    "💊",
)

store = get_store()
plans = store.list_plans("OPEN")

top = st.columns([2, 1])
top[0].metric("Open prescriptions", len(plans))
if top[1].button("↻ Rebuild", width="stretch"):
    profile = diagnostics.build_profile(store)
    diagnostics.persist_hypotheses(store, profile)
    created = prescription.prescribe(store, profile)
    lifecycle.sync_statuses(store)
    st.success(f"{len(created)} prescriptions refreshed.")
    st.rerun()

if not plans:
    empty_state(
        "Nothing to prescribe.",
        "Either no knowledge gap is open, or the performance data has not been analysed yet.",
    )
    nav_link("pages/4_🔍_Diagnosis.py", "Go to Diagnosis", "🔍")
    st.stop()

plans.sort(key=lambda p: p.gap_score, reverse=True)

for index, plan in enumerate(plans):
    ku = store.get_ku(plan.ku_id)
    if not ku:
        continue
    header = f"Priority {index + 1} · {ku.label}  —  gap {plan.gap_score:.1f}"
    with st.expander(header, expanded=index == 0):
        st.caption(f"Error type: {', '.join(plan.error_types) or 'unclassified'} · status {ku.status}")

        st.markdown("##### 1 · WHAT I don't know")
        st.write(plan.what)

        st.markdown("##### 2 · WHY it matters")
        st.write(plan.why)

        st.markdown("##### 3 · WHERE to fix it")
        st.info(plan.where)

        st.markdown("##### 4 · WHAT to study")
        st.write(plan.what_to_study or ku.statement)

        st.markdown("##### 5 · HOW to study")
        if plan.methods:
            st.caption(" · ".join(LEARNING_METHODS.get(m, m).rstrip(".") for m in plan.methods))
        for step in plan.how:
            st.markdown(f"- {step}")

        st.markdown("##### 6 · HOW MUCH")
        st.success(plan.how_much or "Only the identified section.")

        st.divider()
        st.markdown("##### ↩︎ Send it back to NotebookLM")
        st.caption(
            "This prompt asks your notebook for exactly this gap — nothing else, and nothing "
            "from outside your sources."
        )
        if plan.gemini_prompt:
            copy_button(plan.gemini_prompt, label="📋 Copy the NotebookLM prompt", key=f"gp{plan.id}")
            open_notebooklm()
            with st.expander("👀 See the prompt"):
                st.code(plan.gemini_prompt)
        else:
            st.caption("No prompt stored for this prescription — rebuild to generate one.")

        st.divider()
        c1, c2 = st.columns(2)
        if c1.button("✅ I have studied this", key=f"done_{plan.id}", width="stretch"):
            store.complete_plan(plan.id)
            store.log_event("prescription_done", {"ku_id": plan.ku_id})
            lifecycle.sync_statuses(store)
            st.success("Now let the system re-test you with new questions.")
            st.rerun()
        c2.download_button(
            "⬇︎ Markdown",
            prescription.to_markdown(store, plan),
            file_name=f"prescription_{plan.ku_id}.md",
            key=f"dl_{plan.id}",
            width="stretch",
        )
        nav_link("pages/6_🔁_Adaptive_Questions.py", "Re-test me on this weakness", "🔁")
