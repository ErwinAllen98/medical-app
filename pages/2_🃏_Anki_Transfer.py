"""Layer 3 — automatic transfer of validated cards into Anki."""

from __future__ import annotations

import streamlit as st

from secondbrain import anki
from secondbrain.config import Settings
from secondbrain.ui import empty_state, get_store, page

page(
    "Cards → Anki",
    "Validated cards move into your collection through AnkiConnect. No manual copy-paste of individual cards.",
    "🃏",
)

store = get_store()
settings = Settings.load()
pending = store.cards_without_anki()
all_cards = store.list_cards()

c1, c2, c3 = st.columns(3)
c1.metric("Cards in the brain", len(all_cards))
c2.metric("Already in Anki", len(all_cards) - len(pending))
c3.metric("Waiting to transfer", len(pending))

client = anki.AnkiConnect()
online = client.available()
st.markdown(
    f"**AnkiConnect:** {'🟢 connected at ' + client.url if online else '⚪️ not reachable at ' + client.url}"
)
if not online:
    st.caption(
        "Open Anki with the AnkiConnect add-on (code 2055492159) on the same machine as this hub. "
        "If the hub runs elsewhere, use the .apkg export below — it carries the same note type and tags."
    )

st.divider()
tab_push, tab_export, tab_browse = st.tabs(["🚀 Transfer", "💾 .apkg export", "🔍 Browse cards"])

with tab_push:
    deck = st.text_input("Target deck", value=settings.anki_deck)
    st.caption(
        f"Note type “{settings.anki_model}” is created automatically with the fields "
        f"{', '.join(anki.NOTE_FIELDS)} — every note carries its source and its knowledge-unit id."
    )
    if not pending:
        empty_state("Everything has already been transferred.", "Generate new cards to fill this queue.")
    else:
        with st.expander(f"Preview the {len(pending)} pending cards"):
            for card in pending[:40]:
                fields = anki.render_fields(store, card)
                st.markdown(
                    f"<div class='sb-card'><span class='sb-tag'>L{card.cognitive_level}</span>"
                    f"<span class='sb-tag'>{card.error_target or 'general'}</span><br>"
                    f"<b>{card.question}</b><br>{card.answer}"
                    f"<br><span class='sb-muted'>{fields['Source']}</span></div>",
                    unsafe_allow_html=True,
                )
        if st.button("Send to Anki", type="primary", disabled=not online):
            try:
                report = anki.push_cards(store, deck=deck)
                st.success(f"Added {report.added} · skipped {report.skipped} · failed {report.failed}")
                for err in report.errors[:10]:
                    st.error(err)
                st.rerun()
            except anki.AnkiError as exc:
                st.error(str(exc))

with tab_export:
    st.caption("Offline path: one import into Anki, same note type, tags and traceability preserved.")
    scope = st.radio("Export", ["Only cards not yet in Anki", "All cards"], horizontal=True)
    if st.button("Build .apkg"):
        cards = pending if scope.startswith("Only") else all_cards
        try:
            path = anki.export_apkg(store, cards=cards)
            with open(path, "rb") as fh:
                st.download_button(
                    "Download second_brain.apkg", fh.read(),
                    file_name="second_brain.apkg", mime="application/octet-stream",
                )
            st.success(f"Built {len(cards)} notes → {path}")
        except anki.AnkiError as exc:
            st.error(str(exc))

with tab_browse:
    kus = store.list_kus()
    if not kus:
        empty_state("No knowledge units yet.")
    else:
        labels = {k.id: k.label for k in kus}
        chosen = st.selectbox("Knowledge unit", list(labels), format_func=lambda i: labels[i])
        ku = store.get_ku(chosen)
        st.markdown(f"**{ku.statement}**")
        st.caption(f"📍 {ku.source_locator(store.source_titles().get(ku.source_id, ''))}")
        for card in store.list_cards(chosen, include_retired=True):
            status = f"note {card.anki_note_id}" if card.anki_note_id else "not in Anki"
            st.markdown(
                f"<div class='sb-card'><span class='sb-tag'>gen {card.generation}</span>"
                f"<span class='sb-tag'>L{card.cognitive_level}</span>"
                f"<span class='sb-tag'>{card.error_target or 'general'}</span>"
                f"<span class='sb-tag'>{status}</span><br>"
                f"<b>{card.question}</b><br>{card.answer}"
                + (f"<br><span class='sb-muted'>{card.explanation}</span>" if card.explanation else "")
                + "</div>",
                unsafe_allow_html=True,
            )
