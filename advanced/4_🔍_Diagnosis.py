"""Knowledge-gap detection: scores, patterns, Claude's diagnosis, periodic reports."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from secondbrain import claude, diagnostics, reports
from secondbrain.llm import LLMError
from secondbrain.taxonomy import ERROR_TYPES
from secondbrain.ui import clear_bridge, empty_state, get_store, llm_bridge, nav_link, page

page(
    "Knowledge gaps",
    "Not “you failed 4 cards” — which knowledge is broken, why, how badly, and how urgently.",
    "🔍",
)

store = get_store()
if store.review_count() == 0:
    empty_state("No performance data yet.", "Study in AnkiDroid, then sync your answers back.")
    nav_link("pages/2_🔄_Sync.py", "Go to Sync", "🔄")
    st.stop()

profile = diagnostics.build_profile(store)

tab_gaps, tab_claude, tab_reports, tab_plan, tab_tax = st.tabs(
    ["📊 Gap score", "🩺 Claude", "🗓 Reports", "🃏 Anki plan", "📕 Taxonomy"]
)

# ---------------------------------------------------------------------------
with tab_gaps:
    st.caption(
        "Knowledge-Gap Score = frequency × severity × recency × retrieval difficulty × low stability."
    )
    ranked = sorted([u for u in profile.units if u.attempts], key=lambda u: u.gap_score, reverse=True)

    for i, u in enumerate(ranked[:10], 1):
        if u.gap_score <= 0:
            continue
        st.markdown(
            f"<div class='sb-card'><b>Priority {i} — {u.label}</b><br>"
            f"<span class='sb-tag'>{u.top_error or 'unclassified'}</span>"
            f"<span class='sb-tag'>gap {u.gap_score:.1f}</span>"
            f"<span class='sb-tag'>{u.failures}/{u.attempts} failures</span>"
            f"<span class='sb-tag'>importance {u.importance}/5</span>"
            f"<span class='sb-tag'>{u.status}</span><br>"
            f"<span class='sb-muted'>{', '.join(u.signatures) or 'no failure signature'}</span></div>",
            unsafe_allow_html=True,
        )
        with st.expander("Why this score?"):
            if u.gap_factors:
                st.dataframe(
                    pd.DataFrame([u.gap_factors]).T.rename(columns={0: "factor (0-1)"}),
                    width="stretch",
                )
            for e in u.evidence:
                st.markdown(f"- {e}")
            if u.level_pass_rate:
                st.caption("Pass rate by cognitive level")
                st.bar_chart(pd.Series(u.level_pass_rate).sort_index(), height=140)
            for h in u.error_hypotheses:
                st.markdown(f"- `{h['error_type']}` ({h['confidence']:.2f}) — {h['evidence']}")

    if profile.patterns:
        st.subheader("Patterns across questions")
        for p in profile.patterns:
            st.markdown(
                f"<div class='sb-card'>{p.narrative}<br>"
                f"<span class='sb-tag'>{p.failing_units}/{p.units_involved} units</span>"
                f"<span class='sb-tag'>failure rate {p.failure_rate:.0%}</span></div>",
                unsafe_allow_html=True,
            )

# ---------------------------------------------------------------------------
with tab_claude:
    st.caption(
        "Claude receives the longitudinal dossier and returns five things: the gap report, the "
        "learning prescription, the NotebookLM prompt, an Anki update plan and the mastery status."
    )
    limit = st.slider("How many weak units to send", 3, 25, 10)
    dossier = claude.build_dossier(store, profile, limit=limit)

    if not dossier["units"]:
        empty_state("Nothing to diagnose yet.")
    else:
        with st.expander("Performance dossier (what Claude receives)"):
            st.json(dossier, expanded=False)

        prompt = claude.build_diagnostic_prompt(dossier)
        raw = llm_bridge(prompt, key="claude_diag", provider="claude", label="Diagnose with Gemini")

        if raw:
            try:
                result = claude.parse_diagnosis(raw)
            except LLMError as exc:
                st.error(f"Could not read the response: {exc}")
                result = None

            if result:
                for item in result.diagnoses:
                    ku = store.get_ku(item.get("ku_id", ""))
                    label = ku.label if ku else item.get("ku_id", "?")
                    presc = item.get("learning_prescription") or item.get("study_plan") or {}
                    st.markdown(
                        f"<div class='sb-card'><b>{label}</b> "
                        f"<span class='sb-tag'>{', '.join(item.get('error_types') or [])}</span><br>"
                        f"{item.get('why','')}<br>"
                        f"<span class='sb-muted'>{presc.get('how_much','')}</span></div>",
                        unsafe_allow_html=True,
                    )
                if st.button("Apply — save gaps and prescriptions", type="primary", width="stretch"):
                    report = claude.apply_diagnosis(store, result, profile)
                    clear_bridge("claude_diag")
                    st.success(f"{report['diagnoses']} gaps · {report['plans']} prescriptions saved.")
                    nav_link("pages/5_💊_Prescription.py", "Open the prescriptions", "💊")

    st.divider()
    if st.button("Run the built-in analysis instead (no Claude needed)", width="stretch"):
        bundle = reports.run_analysis(store)
        st.success(
            f"{len(bundle.gaps)} gaps scored · {len(bundle.prescriptions)} prescriptions written."
        )
        nav_link("pages/5_💊_Prescription.py", "Open the prescriptions", "💊")

# ---------------------------------------------------------------------------
with tab_reports:
    scale = st.radio("Time scale", list(reports.WINDOWS), horizontal=True, index=1)
    st.caption(reports.WINDOWS[scale][1])
    if st.button("Run the analysis", type="primary", width="stretch"):
        st.session_state["bundle_scale"] = scale

    if st.session_state.get("bundle_scale") == scale:
        bundle = reports.run_analysis(store, scale=scale)
        w = bundle.window
        c1, c2, c3 = st.columns(3)
        c1.metric("Reviews", w.reviews)
        c2.metric("Lapse rate", f"{w.lapse_rate:.0%}")
        c3.metric("Knowledge debt", w.knowledge_debt, help="Units currently WEAK or RELEARNING")

        if w.chronic:
            st.markdown("**Chronic weaknesses**")
            for label in dict.fromkeys(w.chronic):
                st.markdown(f"- 🔴 {label}")
        if w.new_weaknesses:
            st.markdown("**New weaknesses in this window**")
            for label in dict.fromkeys(w.new_weaknesses):
                st.markdown(f"- 🟠 {label}")
        if w.mastered_in_window:
            st.markdown("**Mastered in this window**")
            for label in w.mastered_in_window:
                st.markdown(f"- ✅ {label}")
        if w.reactivated:
            st.markdown("**Reactivated after a decline**")
            for label in w.reactivated:
                st.markdown(f"- ♻️ {label}")
        if bundle.transitions:
            st.markdown("**Status changes**")
            for t in bundle.transitions:
                st.markdown(f"- {t.label}: `{t.old}` → `{t.new}` ({t.reason})")

        st.download_button(
            "⬇︎ Full report (Markdown)",
            reports.bundle_markdown(store, bundle),
            file_name=f"{scale}_report.md",
            width="stretch",
        )

# ---------------------------------------------------------------------------
with tab_plan:
    plan = reports.anki_update_plan(store, profile)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("New", len(plan.new_cards))
    c2.metric("Suspend", len(plan.suspend_candidates))
    c3.metric("Retire", len(plan.retire_candidates))
    c4.metric("Retag", len(plan.tag_updates))

    if plan.suspend_candidates:
        st.markdown("**Leeches — suspend until the source has been re-read**")
        for item in plan.suspend_candidates:
            st.markdown(f"- {item['unit']} — {item['question'][:80]} · *{item['reason']}*")
    if plan.retire_candidates:
        st.markdown("**Likely bad cards — rewrite or split**")
        for item in plan.retire_candidates:
            st.markdown(f"- {item['unit']} — {item['question'][:80]} · *{item['reason']}*")

    with st.form("apply_plan"):
        st.caption("Apply the parts you agree with.")
        do_suspend = st.checkbox("Suspend leeches", value=True)
        do_retag = st.checkbox("Update status tags", value=True)
        do_retire = st.checkbox("Retire the flagged cards", value=False)
        if st.form_submit_button("Apply", type="primary"):
            done = reports.apply_anki_plan(store, plan, suspend=do_suspend,
                                           retire=do_retire, retag=do_retag)
            st.success(f"suspended {done['suspended']} · retired {done['retired']} · retagged {done['retagged']}")

# ---------------------------------------------------------------------------
with tab_tax:
    for key, info in ERROR_TYPES.items():
        st.markdown(
            f"<div class='sb-card'><b>{key}</b><br>{info['definition']}<br>"
            f"<span class='sb-muted'>Remedy: {info['remedy']}</span></div>",
            unsafe_allow_html=True,
        )
