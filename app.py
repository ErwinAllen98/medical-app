"""Second Brain — closed-loop adaptive medical learning.

Home: the one question the system exists to answer —
“given my real learning data, what is the single best thing to learn right now?”

Dr Erfan Alinejad Ghadi — Iran Medical Council No. 219890
"""

from __future__ import annotations

import streamlit as st

from secondbrain import diagnostics, lifecycle, pipeline, reports
from secondbrain.taxonomy import STATUS_FLOW
from secondbrain.ui import copy_button, empty_state, get_store, nav_link, open_notebooklm, page

page(
    "Second Brain",
    "Sources → NotebookLM → Anki/FSRS → gap detection → prescription → re-test → mastery → Notion",
    "🧠",
)

store = get_store()
stats = store.stats()

# ---------------------------------------------------------------------------
if stats["knowledge_units"] == 0:
    empty_state(
        "The brain is empty.",
        "Add a source on the Capture page — or load the demo collection to watch the loop run.",
    )
    if st.button("Load the demo collection", type="primary", width="stretch"):
        pipeline.seed_demo(store)
        pipeline.run_cycle(store, pull_from_anki=False)
        st.rerun()
    st.stop()

profile = diagnostics.build_profile(store)
plans = sorted(store.list_plans("OPEN"), key=lambda p: p.gap_score, reverse=True)

# ---------------------------------------------------------------------------
# 1. The answer to the only question that matters
# ---------------------------------------------------------------------------
st.subheader("👉 Learn this right now")

if plans:
    plan = plans[0]
    ku = store.get_ku(plan.ku_id)
    st.markdown(
        f"<div class='sb-card'><b>{ku.label if ku else plan.ku_id}</b>"
        f"<span class='sb-tag'>gap {plan.gap_score:.1f}</span>"
        f"<span class='sb-tag'>{', '.join(plan.error_types) or 'unclassified'}</span><br><br>"
        f"<b>What:</b> {plan.what}<br><br>"
        f"<b>Where:</b> {plan.where.splitlines()[0]}<br><br>"
        f"<b>How much:</b> {plan.how_much or 'only the identified section'}</div>",
        unsafe_allow_html=True,
    )
    if plan.gemini_prompt:
        copy_button(plan.gemini_prompt, label="📋 Copy the NotebookLM prompt", key="home")
        open_notebooklm()
    nav_link("pages/5_💊_Prescription.py", "Open the full prescription", "💊")
else:
    top = next((u for u in profile.top(1)), None)
    if top and top.gap_score > 0:
        st.info(f"Weakest area: **{top.label}** (gap {top.gap_score:.1f}) — run the loop to get a prescription.")
    else:
        st.success("No open knowledge gap. Keep reviewing in Anki and sync your answers back.")

# ---------------------------------------------------------------------------
# 2. One button. Nothing runs on a schedule — the loop turns when you tap this.
# ---------------------------------------------------------------------------
if st.button("🔄 Sync", type="primary", width="stretch"):
    with st.spinner("Fetching your answers, analysing, prescribing, backing up…"):
        report = pipeline.full_sync(store)
    st.success(
        f"{report.answers_pulled} answers in · {report.cards_pushed} cards out · "
        f"{report.prescriptions} prescriptions"
        + (" · backed up ✅" if report.backed_up else "")
    )
    if report.next_action:
        st.info(f"👉 Next: {report.next_action}")
    for label in report.reactivated:
        st.warning(f"♻️ Reactivated after a decline: {label}")
    for step in report.steps:
        st.caption(step)
    for problem in report.problems:
        st.warning(problem)
    st.rerun()
st.caption(
    "Nothing runs in the background: the loop advances only when you tap Sync — "
    "no server, no computer left on."
)

# ---------------------------------------------------------------------------
# 3. Where everything stands
# ---------------------------------------------------------------------------
counts = lifecycle.counts(store)
cols = st.columns(len(STATUS_FLOW))
for col, status in zip(cols, STATUS_FLOW):
    col.metric(status[:5].title(), counts.get(status, 0), help=status)

nav1, nav2, nav3 = st.columns(3)
nav_link("pages/1_📚_Sources.py", "Capture", "📚", nav1)
nav_link("pages/2_🔄_Sync.py", "Sync", "🔄", nav2)
nav_link("pages/4_🔍_Diagnosis.py", "Gaps", "🔍", nav3)
nav4, nav5, nav6 = st.columns(3)
nav_link("pages/5_💊_Prescription.py", "Prescription", "💊", nav4)
nav_link("pages/6_🔁_Adaptive_Questions.py", "Re-test", "🔁", nav5)
nav_link("pages/7_🏆_Mastery_&_Notion.py", "Mastery", "🏆", nav6)
nav_link("pages/8_⚙️_Connections.py", "Connections — add your API keys", "⚙️")

# ---------------------------------------------------------------------------
# 4. Detail, kept out of the way
# ---------------------------------------------------------------------------
with st.expander("📱 How the loop works from your phone"):
    st.markdown(
        """
1. **Capture** — copy the prompt, paste it into NotebookLM, paste the JSON back.
2. **Sync** — one tap; the cards land in AnkiDroid through AnkiWeb.
3. **Study** — Anki + FSRS, as usual.
4. **Sync** again — your answers come back here.
5. **Gaps → Prescription** — what you don't know, why, where to fix it, how much to read.
6. **Re-test** — new questions on the same weakness, until it is mastered.
"""
    )

with st.expander("🔴 Patterns across your failures"):
    if not profile.patterns:
        st.caption("No cross-card pattern detected yet.")
    for p in profile.patterns[:5]:
        st.markdown(f"- {p.narrative}")

with st.expander("🗓 Reports"):
    scale = st.radio("Scale", list(reports.WINDOWS), horizontal=True, index=1, key="home_scale")
    w = reports.window_report(store, scale, profile)
    c1, c2, c3 = st.columns(3)
    c1.metric("Reviews", w.reviews)
    c2.metric("Lapse rate", f"{w.lapse_rate:.0%}")
    c3.metric("Knowledge debt", w.knowledge_debt)
    nav_link("pages/4_🔍_Diagnosis.py", "Full report", "🗓")

with st.expander("Recent activity"):
    for event in store.recent_events(12):
        st.markdown(f"`{event['created_at'][:16]}` **{event['kind']}** — {event['payload']}")
