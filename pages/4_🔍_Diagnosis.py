"""Layers 5-6 — Claude as the diagnostic engine, and the Cumulative Weakness Profile."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from secondbrain import claude, diagnostics
from secondbrain.llm import LLMError
from secondbrain.taxonomy import ERROR_TYPES
from secondbrain.ui import clear_bridge, empty_state, get_store, llm_bridge, page, severity_badge

page(
    "Weakness profile & diagnosis",
    "Why do I keep getting this wrong? Errors are classified, patterns are accumulated across cards, "
    "and every weakness is scored by clinical importance.",
    "🧠",
)

store = get_store()
if store.review_count() == 0:
    empty_state("No performance data yet.", "Import your Anki review history on the Performance page.")
    st.stop()

profile = diagnostics.build_profile(store)

tab_profile, tab_claude, tab_taxonomy = st.tabs(
    ["📊 Cumulative profile", "🩺 Claude diagnosis", "📕 Error taxonomy"]
)

# ---------------------------------------------------------------------------
with tab_profile:
    st.subheader("Patterns across questions")
    if not profile.patterns:
        st.caption("No cross-card pattern yet — more review history will reveal them.")
    for p in profile.patterns:
        st.markdown(
            f"<div class='sb-card'><b>{p.narrative}</b><br>"
            f"<span class='sb-tag'>{p.failing_units}/{p.units_involved} units</span>"
            f"<span class='sb-tag'>failure rate {p.failure_rate:.0%}</span>"
            f"<span class='sb-tag'>{p.dominant_error or 'mixed'}</span>"
            f"{severity_badge(p.severity)}</div>",
            unsafe_allow_html=True,
        )

    st.subheader("Per knowledge unit")
    rows = []
    for u in sorted(profile.units, key=lambda x: x.priority, reverse=True):
        rows.append(
            {
                "Knowledge unit": u.label,
                "Attempts": u.attempts,
                "Failures": u.failures,
                "Failure rate": u.failure_rate,
                "Repeat streak": u.repeated_failure_count,
                "Importance": u.importance,
                "Likely error": u.top_error or "—",
                "Signatures": ", ".join(u.signatures),
                "Severity": u.severity,
                "Priority": u.priority,
                "Status": u.status,
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "Failure rate": st.column_config.ProgressColumn("Failure rate", min_value=0, max_value=1, format="%.0f%%"),
            "Severity": st.column_config.NumberColumn(format="%.2f"),
            "Priority": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    st.subheader("Evidence behind each weakness")
    for u in profile.top(8):
        if not u.attempts:
            continue
        with st.expander(f"{u.label} · {u.top_error or 'unclassified'}"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Failure rate", f"{u.failure_rate:.0%}")
            c2.metric("Repeat streak", u.repeated_failure_count)
            c3.metric("Mean stability", f"{u.mean_stability:.1f}d" if u.mean_stability else "—")
            c4.metric("Answer time", f"{u.mean_answer_seconds:.0f}s" if u.mean_answer_seconds else "—")
            if u.level_pass_rate:
                st.caption("Pass rate by cognitive level")
                st.bar_chart(pd.Series(u.level_pass_rate).sort_index(), height=140)
            st.markdown("**Evidence**")
            for e in u.evidence:
                st.markdown(f"- {e}")
            st.markdown("**Hypotheses**")
            for h in u.error_hypotheses:
                st.markdown(
                    f"- `{h['error_type']}` (confidence {h['confidence']:.2f}) — {h['evidence']}"
                )

# ---------------------------------------------------------------------------
with tab_claude:
    st.caption(
        "The dossier below is longitudinal: every review of every formulation, the neighbouring units, "
        "and the source metadata Claude needs to point you at the right page."
    )
    limit = st.slider("How many weak units to send", 3, 25, 10)
    dossier = claude.build_dossier(store, profile, limit=limit)

    if not dossier["units"]:
        empty_state("Nothing to diagnose.", "No unit has enough review history yet.")
    else:
        with st.expander("Performance dossier (what Claude receives)"):
            st.json(dossier, expanded=False)

        prompt = claude.build_diagnostic_prompt(dossier)
        raw = llm_bridge(
            prompt,
            key="claude_diag",
            provider="claude",
            label="Diagnose with Claude",
            help_text="Paste this into Claude if you prefer the web UI, then bring the JSON back.",
        )

        if raw:
            try:
                result = claude.parse_diagnosis(raw)
            except LLMError as exc:
                st.error(f"Could not read the response: {exc}")
                result = None

            if result:
                st.subheader("Diagnosis")
                for item in result.diagnoses:
                    ku = store.get_ku(item.get("ku_id", ""))
                    label = ku.label if ku else item.get("ku_id", "?")
                    errs = ", ".join(item.get("error_types") or [])
                    target = item.get("review_target") or {}
                    plan = item.get("study_plan") or {}
                    st.markdown(
                        f"<div class='sb-card'><b>{label}</b> <span class='sb-tag'>{errs}</span><br>"
                        f"{item.get('why','')}<br>"
                        f"<span class='sb-muted'>📍 {target.get('chapter','')} · {target.get('section','')} · "
                        f"{target.get('location','')} — {target.get('what_to_read','')}</span></div>",
                        unsafe_allow_html=True,
                    )
                    if plan.get("how"):
                        st.markdown("\n".join(f"- {h}" for h in plan["how"]))

                if result.patterns:
                    st.subheader("Patterns Claude sees")
                    for p in result.patterns:
                        st.markdown(
                            f"- **{p.get('topic','')}** — {p.get('pattern','')}  \n"
                            f"  <span class='sb-muted'>clinical risk: {p.get('clinical_risk','—')}</span>",
                            unsafe_allow_html=True,
                        )

                if st.button("Apply — save diagnoses and build re-study plans", type="primary"):
                    report = claude.apply_diagnosis(store, result, profile)
                    clear_bridge("claude_diag")
                    st.success(
                        f"{report['diagnoses']} diagnoses saved · {report['plans']} study plans created. "
                        "Open the Re-study page."
                    )
                    st.rerun()

    st.divider()
    st.caption("No Claude access right now? The hub can still classify errors heuristically.")
    if st.button("Run heuristic diagnosis instead"):
        saved = diagnostics.persist_hypotheses(store, profile)
        st.success(f"{saved} heuristic diagnoses recorded.")

# ---------------------------------------------------------------------------
with tab_taxonomy:
    st.caption("Every weakness in the system is classified with one of these keys.")
    for key, info in ERROR_TYPES.items():
        st.markdown(
            f"<div class='sb-card'><b>{key}</b> — {info['label']}<br>{info['definition']}<br>"
            f"<span class='sb-muted'>Remedy: {info['remedy']}</span></div>",
            unsafe_allow_html=True,
        )
