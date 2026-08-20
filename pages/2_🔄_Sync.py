"""Layer 3-4 — getting cards into Anki and review history back, from a phone.

Order of preference on mobile:
  1. AnkiWeb sync   — hub ⇄ AnkiWeb ⇄ AnkiDroid (just press sync in AnkiDroid)
  2. File bridge    — download .apkg → open with AnkiDroid; upload its export back
  3. AnkiConnect    — desktop only
  4. CSV            — last resort
"""

from __future__ import annotations

import streamlit as st

from secondbrain import anki, colpkg, ingest
from secondbrain.ankiweb import AnkiWebBridge, AnkiWebError, library_available
from secondbrain.config import Settings
from secondbrain.ui import empty_state, get_store, page

page(
    "Anki sync",
    "NotebookLM → hub → AnkiWeb → AnkiDroid on your phone, and the review history back again.",
    "🔄",
)

store = get_store()
settings = Settings.load()
bridge = AnkiWebBridge(settings)
pending = store.cards_without_anki()
all_cards = store.list_cards()

c1, c2, c3 = st.columns(3)
c1.metric("Cards", len(all_cards))
c2.metric("Waiting", len(pending))
c3.metric("Reviews", store.stats()["reviews"])

tab_web, tab_file, tab_desktop, tab_csv = st.tabs(
    ["☁️ AnkiWeb", "📁 File (AnkiDroid)", "🖥 AnkiConnect", "📄 CSV"]
)

# ---------------------------------------------------------------------------
with tab_web:
    st.markdown(
        "<div class='sb-card'><b>The phone loop</b><br>"
        "<span class='sb-muted'>The hub keeps its own Anki collection and syncs it with your "
        "AnkiWeb account. In AnkiDroid you just press <b>Sync</b> — the new cards appear, and the "
        "next sync brings your answers back here for Claude to analyse.</span></div>",
        unsafe_allow_html=True,
    )

    if not library_available():
        st.error("The `anki` package is missing. Install it with `pip install anki`.")
    elif not bridge.configured:
        st.warning("AnkiWeb is not configured yet.")
        st.markdown(
            """
Add these to `.streamlit/secrets.toml` (or as environment variables):

```toml
ANKIWEB_USERNAME = "your AnkiWeb email"
ANKIWEB_PASSWORD = "your AnkiWeb password"
```

The password is only used to log in to AnkiWeb from this hub. If you would rather not store it,
use the **File (AnkiDroid)** tab — it needs no account at all.
"""
        )
    else:
        stats = bridge.local_stats()
        st.caption(
            f"Local mirror: {stats['notes']} notes · {stats['second_brain_notes']} from the Second Brain · "
            f"{stats['reviews']} reviews on record"
            + ("" if stats["notes"] else " — the first sync will download your AnkiWeb collection.")
        )

        if st.button("🔄 Sync now", type="primary", width="stretch"):
            with st.spinner("Talking to AnkiWeb…"):
                try:
                    result = bridge.round_trip(store)
                except AnkiWebError as exc:
                    st.error(str(exc))
                    result = None
            if result:
                if result.needs_choice:
                    st.warning(result.notes[0] if result.notes else result.status)
                else:
                    st.success(
                        f"{result.status} · {result.pushed} new cards sent · "
                        f"{result.pulled} new review events imported"
                    )
                    if result.pushed:
                        st.info("Now open AnkiDroid and press **Sync** to pull the cards onto your phone.")
                for note in result.notes:
                    st.caption(note)
                if result.server_message:
                    st.caption(f"AnkiWeb: {result.server_message}")

        cols = st.columns(2)
        if cols[0].button("⬇︎ Only fetch answers", width="stretch"):
            try:
                result = bridge.round_trip(store, push=False)
                st.success(f"{result.status} · {result.pulled} new review events")
            except AnkiWebError as exc:
                st.error(str(exc))
        if cols[1].button("⬆︎ Only send cards", width="stretch"):
            try:
                result = bridge.round_trip(store, pull=False)
                st.success(f"{result.status} · {result.pushed} cards sent")
            except AnkiWebError as exc:
                st.error(str(exc))

        with st.expander("⚠️ Advanced — force a full upload"):
            st.markdown(
                "A **full upload replaces the collection stored on AnkiWeb** with the hub's copy. "
                "Only do this if AnkiWeb asked for it and you know the hub's mirror is the good one."
            )
            confirm = st.text_input("Type FULL UPLOAD to confirm")
            if st.button("Force full upload", disabled=confirm.strip() != "FULL UPLOAD"):
                try:
                    result = bridge.sync(allow_full_upload=True)
                    st.success(result.status)
                except AnkiWebError as exc:
                    st.error(str(exc))

# ---------------------------------------------------------------------------
with tab_file:
    st.markdown(
        "<div class='sb-card'><b>No account needed</b><br>"
        "<span class='sb-muted'>Download the deck, tap the file in Chrome's downloads and choose "
        "AnkiDroid. After studying, export from AnkiDroid and upload it back here.</span></div>",
        unsafe_allow_html=True,
    )

    st.markdown("**1 · Send the cards to your phone**")
    scope = st.radio("Include", ["Only new cards", "All cards"], horizontal=True)
    if st.button("Build the deck file", width="stretch"):
        cards = pending if scope.startswith("Only") else all_cards
        try:
            if library_available() and bridge.collection_exists:
                bridge.push(store, cards=cards)
                path = bridge.export_apkg()
            else:
                path = anki.export_apkg(store, cards=cards)
            st.session_state["apkg_path"] = path
        except (anki.AnkiError, AnkiWebError) as exc:
            st.error(str(exc))

    if st.session_state.get("apkg_path"):
        with open(st.session_state["apkg_path"], "rb") as fh:
            st.download_button(
                "⬇︎ Download the deck (.apkg)",
                fh.read(),
                file_name="second_brain.apkg",
                mime="application/octet-stream",
                width="stretch",
            )
        st.caption("Chrome ▸ Downloads ▸ tap the file ▸ open with AnkiDroid.")

    st.divider()
    st.markdown("**2 · Bring your answers back**")
    st.caption(
        "AnkiDroid ▸ ⚙ Settings ▸ Advanced ▸ **Export collection** (keep “include scheduling”), "
        "then upload the .colpkg/.apkg here. Cards are matched by their SecondBrainID field, so "
        "nothing breaks even if Anki renumbers the notes."
    )
    uploaded = st.file_uploader("AnkiDroid export", type=["colpkg", "apkg", "anki2"])
    if uploaded and st.button("Import review history", type="primary", width="stretch"):
        try:
            report = colpkg.import_collection(store, uploaded.read())
            st.success(
                f"{report['new_reviews']} new review events imported "
                f"(file contained {report['reviews_in_file']} reviews over {report['notes_in_file']} notes)."
            )
            if report["new_reviews"] == 0 and report["reviews_in_file"]:
                st.info(
                    "Nothing new — either these reviews were already imported, or the notes in the "
                    "file were not created by the hub."
                )
        except colpkg.CollectionFileError as exc:
            st.error(str(exc))

# ---------------------------------------------------------------------------
with tab_desktop:
    client = anki.AnkiConnect()
    online = client.available()
    st.markdown(f"**AnkiConnect:** {'🟢 connected' if online else '⚪️ not reachable at ' + client.url}")
    st.caption("Desktop Anki with the AnkiConnect add-on, on the same machine as this hub.")
    cols = st.columns(2)
    if cols[0].button("Push cards", disabled=not online, width="stretch"):
        try:
            report = anki.push_cards(store)
            st.success(f"added {report.added} · skipped {report.skipped} · failed {report.failed}")
        except anki.AnkiError as exc:
            st.error(str(exc))
    if cols[1].button("Pull reviews", disabled=not online, width="stretch"):
        try:
            st.success(f"{anki.pull_reviews(store)} new review events")
        except anki.AnkiError as exc:
            st.error(str(exc))

# ---------------------------------------------------------------------------
with tab_csv:
    st.caption("Manual path: a CSV of the revlog. Column names are matched flexibly.")
    with st.expander("SQL for Anki ▸ Tools ▸ Debug Console"):
        st.code(ingest.ANKI_DB_QUERY, language="sql")
    st.download_button("Template CSV", ingest.CSV_TEMPLATE, file_name="reviews_template.csv")
    pasted = st.text_area("Paste CSV", height=140)
    if st.button("Import CSV"):
        if not pasted.strip():
            st.warning("Nothing to import.")
        else:
            report = ingest.import_csv(store, pasted)
            if report["error"]:
                st.error(report["error"])
            else:
                st.success(f"{report['new']} new review events (matched {report['matched']} rows).")

# ---------------------------------------------------------------------------
st.divider()
with st.expander(f"🔍 Browse the {len(all_cards)} cards"):
    kus = store.list_kus()
    if not kus:
        empty_state("No knowledge units yet.")
    else:
        labels = {k.id: k.label for k in kus}
        chosen = st.selectbox("Knowledge unit", list(labels), format_func=lambda i: labels[i])
        for card in store.list_cards(chosen, include_retired=True):
            status = "in Anki" if card.anki_note_id else "not sent yet"
            st.markdown(
                f"<div class='sb-card'><span class='sb-tag'>gen {card.generation}</span>"
                f"<span class='sb-tag'>L{card.cognitive_level}</span>"
                f"<span class='sb-tag'>{status}</span><br>"
                f"<b>{card.question}</b><br>{card.answer}</div>",
                unsafe_allow_html=True,
            )
