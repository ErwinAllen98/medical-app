"""Layer 4 — bring Anki/FSRS performance data back into the hub."""

from __future__ import annotations

import streamlit as st

from secondbrain import anki, ingest
from secondbrain.ui import empty_state, get_store, page

page(
    "Performance data",
    "FSRS is the sensor, not the diagnosis. It tells us THAT you are struggling — we pull that "
    "signal in here so Claude can work out WHY.",
    "📈",
)

store = get_store()
stats = store.stats()

c1, c2, c3 = st.columns(3)
c1.metric("Reviews on record", stats["reviews"])
c2.metric("Cards tracked in Anki", stats["in_anki"])
c3.metric("Knowledge units", stats["knowledge_units"])

tab_pull, tab_csv, tab_fsrs = st.tabs(["🔄 Pull from AnkiConnect", "📄 Import a CSV", "🧮 Local FSRS state"])

with tab_pull:
    client = anki.AnkiConnect()
    online = client.available()
    st.markdown(f"**AnkiConnect:** {'🟢 connected' if online else '⚪️ not reachable at ' + client.url}")
    st.caption("Pulls the full review log (rating, interval, answer time) plus FSRS stability/difficulty.")
    if st.button("Pull review history", type="primary", disabled=not online):
        try:
            added = anki.pull_reviews(store)
            st.success(f"{added} new review events imported.")
            st.rerun()
        except anki.AnkiError as exc:
            st.error(str(exc))

with tab_csv:
    st.caption(
        "For when Anki lives on another machine. Column names are matched flexibly: "
        "SecondBrainID/note id, date/id, ease/rating, ivl, lastIvl, time, plus optional FSRS columns."
    )
    with st.expander("SQL to run in Anki ▸ Tools ▸ Debug Console"):
        st.code(ingest.ANKI_DB_QUERY, language="sql")
    st.download_button("Download a CSV template", ingest.CSV_TEMPLATE, file_name="reviews_template.csv")

    uploaded = st.file_uploader("Review log (CSV)", type=["csv", "txt"])
    pasted = st.text_area("…or paste CSV text", height=140)
    if st.button("Import"):
        text = uploaded.read().decode("utf-8", errors="replace") if uploaded else pasted
        if not text.strip():
            st.warning("Nothing to import.")
        else:
            report = ingest.import_csv(store, text)
            if report["error"]:
                st.error(report["error"])
            else:
                st.success(
                    f"Parsed {report['parsed']} rows · matched {report['matched']} · "
                    f"{report['new']} new review events stored."
                )
                if report["unmatched"]:
                    st.warning(
                        "Unmatched identifiers (these cards were not created by the hub): "
                        + ", ".join(report["unmatched"])
                    )

with tab_fsrs:
    st.caption(
        "Recomputes stability, difficulty and retrievability locally from our own review log — "
        "useful when the imported history had no FSRS columns."
    )
    kus = store.list_kus()
    if not kus:
        empty_state("Nothing to compute yet.")
    else:
        labels = {k.id: k.label for k in kus}
        chosen = st.selectbox("Knowledge unit", list(labels), format_func=lambda i: labels[i])
        for card in store.list_cards(chosen):
            state = ingest.fsrs_memory_state(store, card.id)
            reviews = store.list_reviews(card.id)
            fails = sum(1 for r in reviews if r.failed)
            st.markdown(
                f"<div class='sb-card'><b>{card.question}</b><br>"
                f"<span class='sb-tag'>L{card.cognitive_level}</span>"
                f"<span class='sb-tag'>{len(reviews)} reviews</span>"
                f"<span class='sb-tag'>{fails} lapses</span>"
                + (
                    f"<span class='sb-tag'>stability {state['stability']:.1f}d</span>"
                    f"<span class='sb-tag'>difficulty {state['difficulty']:.1f}</span>"
                    if state and state.get("stability") is not None
                    else "<span class='sb-muted'>no FSRS state yet</span>"
                )
                + "</div>",
                unsafe_allow_html=True,
            )
