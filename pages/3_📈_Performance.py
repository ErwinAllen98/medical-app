"""Layer 4 — what the FSRS sensor is telling us, before Claude interprets it."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from secondbrain import diagnostics, ingest
from secondbrain.ui import empty_state, get_store, page

page(
    "Performance",
    "FSRS is the sensor, not the diagnosis. It tells us THAT you are struggling — the next page "
    "works out WHY.",
    "📈",
)

store = get_store()
stats = store.stats()

c1, c2, c3 = st.columns(3)
c1.metric("Reviews", stats["reviews"])
c2.metric("Cards in Anki", stats["in_anki"])
c3.metric("Knowledge units", stats["knowledge_units"])

if stats["reviews"] == 0:
    empty_state(
        "No review history yet.",
        "Study in AnkiDroid, then press Sync on the 🔄 Sync page to bring your answers back.",
    )
    st.page_link("pages/2_🔄_Sync.py", label="Go to Sync", icon="🔄")
    st.stop()

reviews = store.list_reviews()
rows = [
    {
        "date": r.reviewed_at[:10],
        "rating": r.rating,
        "failed": 1 if r.failed else 0,
        "seconds": round((r.duration_ms or 0) / 1000, 1),
        "origin": r.origin,
    }
    for r in reviews
]
df = pd.DataFrame(rows)

st.subheader("Daily load and lapses")
daily = df.groupby("date").agg(reviews=("rating", "size"), lapses=("failed", "sum"))
st.bar_chart(daily, height=220)

c1, c2, c3 = st.columns(3)
c1.metric("Overall lapse rate", f"{df['failed'].mean():.0%}")
c2.metric("Median answer time", f"{df['seconds'].median():.0f}s")
c3.metric("Sources of data", ", ".join(sorted(df["origin"].unique())))

st.subheader("Per knowledge unit")
profile = diagnostics.build_profile(store)
table = pd.DataFrame(
    [
        {
            "Knowledge unit": u.label,
            "Attempts": u.attempts,
            "Failure rate": u.failure_rate,
            "Stability (d)": u.mean_stability,
            "Last seen (d)": u.last_reviewed_days,
            "Status": u.status,
        }
        for u in profile.units
        if u.attempts
    ]
)
st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        "Failure rate": st.column_config.ProgressColumn(
            "Failure rate", min_value=0, max_value=1, format="%.0f%%"
        )
    },
)

st.subheader("FSRS memory state")
st.caption("Recomputed locally from our own review log — useful when the import carried no FSRS columns.")
kus = [k for k in store.list_kus() if store.reviews_for_ku(k.id)]
if kus:
    labels = {k.id: k.label for k in kus}
    chosen = st.selectbox("Knowledge unit", list(labels), format_func=lambda i: labels[i])
    for card in store.list_cards(chosen):
        state = ingest.fsrs_memory_state(store, card.id)
        card_reviews = store.list_reviews(card.id)
        lapses = sum(1 for r in card_reviews if r.failed)
        badge = (
            f"<span class='sb-tag'>stability {state['stability']:.1f}d</span>"
            f"<span class='sb-tag'>difficulty {state['difficulty']:.1f}</span>"
            if state and state.get("stability") is not None
            else "<span class='sb-muted'>not reviewed yet</span>"
        )
        st.markdown(
            f"<div class='sb-card'><b>{card.question}</b><br>"
            f"<span class='sb-tag'>L{card.cognitive_level}</span>"
            f"<span class='sb-tag'>{len(card_reviews)} reviews</span>"
            f"<span class='sb-tag'>{lapses} lapses</span>{badge}</div>",
            unsafe_allow_html=True,
        )
