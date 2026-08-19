"""Second Brain — closed-loop adaptive medical learning hub.

Home / control room: the state of the loop, today's priorities, and one button
that advances the whole cycle.

Dr Erfan Alinejad Ghadi — Iran Medical Council No. 219890
"""

from __future__ import annotations

import streamlit as st

from secondbrain import diagnostics, mastery, pipeline
from secondbrain.ui import empty_state, get_store, page, severity_badge

page(
    "Second Brain",
    "Sources → NotebookLM → Anki/FSRS → Claude → targeted re-study → mastery → Notion",
    "🧠",
)

store = get_store()
stats = store.stats()

# ---------------------------------------------------------------------------
# The four questions the system exists to answer
# ---------------------------------------------------------------------------
st.markdown(
    """
<div class='sb-card'>
<b>The system continuously answers four questions:</b><br>
<span class='sb-muted'>What don't I know? · Why don't I know it? · Where in my sources can I fix it? ·
How do we know I have finally mastered it?</span><br><br>
It is optimised for <b>eliminated knowledge gaps</b>, never for the number of flashcards created.
</div>
""",
    unsafe_allow_html=True,
)

if stats["knowledge_units"] == 0:
    empty_state(
        "The brain is empty.",
        "Add a source on the Sources page — or load the demo collection below to watch the whole loop run.",
    )
    if st.button("Load demo collection (5 units, 60 days of simulated FSRS history)", type="primary"):
        pipeline.seed_demo(store)
        pipeline.run_cycle(store, pull_from_anki=False)
        st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Loop status
# ---------------------------------------------------------------------------
profile = diagnostics.build_profile(store)
weak = profile.weak_units

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Knowledge units", stats["knowledge_units"])
c2.metric("Weak right now", len(weak), delta=f"-{stats['mastered']} mastered", delta_color="normal")
c3.metric("Reviews analysed", stats["reviews"])
c4.metric("Open re-study plans", stats["open_plans"])
c5.metric("In Notion", stats["notion_pages"])

st.divider()

left, right = st.columns([3, 2])

with left:
    st.subheader("🔴 Patterns across your failures")
    st.caption("Not “you failed 4 cards” — the recurring shape of the gap.")
    if not profile.patterns:
        empty_state("No cross-card pattern detected yet.", "Import more Anki review history to sharpen this.")
    for p in profile.patterns[:5]:
        st.markdown(
            f"<div class='sb-card'>{p.narrative}<br>"
            f"<span class='sb-tag'>{p.failing_units}/{p.units_involved} units</span>"
            f"<span class='sb-tag'>{p.failures}/{p.attempts} failures</span>"
            f"<span class='sb-tag'>{p.dominant_error or 'mixed'}</span>"
            f"{severity_badge(p.severity)}</div>",
            unsafe_allow_html=True,
        )

    st.subheader("🎯 Today's priorities")
    for unit in profile.top(5):
        if not unit.attempts:
            continue
        errs = ", ".join(h["error_type"] for h in unit.error_hypotheses[:2]) or "—"
        st.markdown(
            f"<div class='sb-card'><b>{unit.label}</b><br>"
            f"<span class='sb-muted'>{unit.failures}/{unit.attempts} failures · "
            f"{', '.join(unit.signatures) or 'no signature'} · likely {errs}</span><br>"
            f"{severity_badge(unit.priority)}</div>",
            unsafe_allow_html=True,
        )

with right:
    st.subheader("⚙️ Advance the loop")
    st.caption("Pull performance data, rebuild the weakness profile, refresh plans, re-check mastery.")
    pull = st.toggle("Also pull review history from AnkiConnect", value=False)
    if st.button("Run one cycle", type="primary", width="stretch"):
        with st.spinner("Running the loop…"):
            report = pipeline.run_cycle(store, pull_from_anki=pull)
        st.success(
            f"{report.pulled_reviews} new reviews · {report.weak_units} weak units · "
            f"{report.plans} plans · {len(report.promoted)} newly mastered"
        )
        for note in report.notes:
            st.info(note)
        for label in report.promoted:
            st.balloons()
            st.success(f"MASTERED: {label}")

    st.markdown("**The loop**")
    st.markdown(
        "".join(f"<span class='sb-step'>{i+1}. {name}</span>" for i, (name, _) in enumerate(pipeline.LOOP_STEPS)),
        unsafe_allow_html=True,
    )
    with st.expander("What each stage does"):
        for name, desc in pipeline.LOOP_STEPS:
            st.markdown(f"**{name}** — {desc}")

    st.subheader("🏆 Closest to mastery")
    for rep in mastery.evaluate_all(store)[:5]:
        if rep.mastered:
            st.markdown(f"✅ **{rep.label}** — mastered")
        else:
            missing = ", ".join(c.label for c in rep.missing[:2])
            st.markdown(f"⏳ **{rep.label}** — {rep.score:.0%} · missing: {missing}")

st.divider()
with st.expander("Recent activity"):
    for event in store.recent_events(15):
        st.markdown(f"`{event['created_at']}` **{event['kind']}** — {event['payload']}")
