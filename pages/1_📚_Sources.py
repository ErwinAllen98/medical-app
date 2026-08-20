"""Layer 1-2 — register authoritative sources and extract source-grounded knowledge."""

from __future__ import annotations

import streamlit as st

from secondbrain import extraction
from secondbrain.llm import LLMError
from secondbrain.models import Source
from secondbrain.taxonomy import ERROR_TYPE_KEYS
from secondbrain.ui import clear_bridge, empty_state, get_store, llm_bridge, page

page(
    "Sources & Extraction",
    "Your uploaded sources are the only allowed knowledge base. Anything that cannot be traced "
    "back to a chapter, section or page is rejected.",
    "📚",
)

store = get_store()

tab_new, tab_extract, tab_library = st.tabs(["➕ Register a source", "🧪 Extract knowledge", "📖 Library"])

# ---------------------------------------------------------------------------
with tab_new:
    st.caption("Register the same sources you uploaded into NotebookLM, so every card stays traceable.")
    with st.form("new_source"):
        title = st.text_input("Title", placeholder="ADA Standards of Care 2026")
        kind = st.selectbox(
            "Type", ["guideline", "textbook", "review article", "lecture notes", "pdf", "slides", "other"]
        )
        citation = st.text_input("Citation / edition / DOI", placeholder="Diabetes Care 2026;49(Suppl. 1)")
        notes = st.text_area("Notes", placeholder="Which chapters matter to you, what you uploaded to NotebookLM…")
        if st.form_submit_button("Register source", type="primary"):
            if not title.strip():
                st.warning("A title is required.")
            else:
                store.upsert_source(Source(title=title.strip(), kind=kind, citation=citation, notes=notes))
                st.success(f"Registered “{title}”.")
                st.rerun()

# ---------------------------------------------------------------------------
with tab_extract:
    sources = store.list_sources()
    if not sources:
        empty_state("Register a source first.", "Extraction is only allowed against a declared source.")
        st.stop()

    labels = {s.id: f"{s.title} ({s.kind})" for s in sources}
    source_id = st.selectbox("Source", list(labels), format_func=lambda i: labels[i])
    source = store.get_source(source_id)

    c1, c2 = st.columns(2)
    scope = c1.text_input("Scope inside the source", placeholder="Chapter 11 — CKD and Risk Management")
    max_units = c2.slider("Maximum knowledge units", 3, 25, 10)
    c3, c4 = st.columns(2)
    language = c3.selectbox(
        "Card language",
        ["English question, English answer",
         "Persian question, English answer (bilingual)",
         "Persian question, Persian answer"],
    )
    focus = c4.multiselect("Bias towards known weaknesses", ERROR_TYPE_KEYS)
    strict = st.toggle(
        "Strict traceability (reject any unit without chapter/section/page)", value=True
    )

    prompt = extraction.build_extraction_prompt(
        source, scope=scope, max_units=max_units, language=language, focus_errors=focus
    )
    st.markdown("#### Run the extraction")
    st.caption(
        "Paste the prompt into the NotebookLM chat for this notebook — that keeps the answers grounded "
        "in your uploaded files — then paste the JSON back here. Or run it through the Gemini API."
    )
    raw = llm_bridge(prompt, key=f"extract_{source_id}", provider="gemini", label="Extract with Gemini")

    if raw:
        try:
            result = extraction.parse_extraction(raw, source, strict=strict)
        except LLMError as exc:
            st.error(f"Could not read the response: {exc}")
            result = None

        if result:
            c1, c2, c3 = st.columns(3)
            c1.metric("Knowledge units", len(result.knowledge_units))
            c2.metric("Cards", result.card_count)
            c3.metric("Rejected", len(result.rejected))
            for warning in result.warnings:
                st.warning(warning)
            if result.rejected:
                with st.expander(f"{len(result.rejected)} items rejected (not traceable / malformed)"):
                    st.json(result.rejected)

            for ku in result.knowledge_units:
                with st.expander(f"{ku.label} · importance {ku.importance}", expanded=False):
                    st.write(ku.statement)
                    st.caption(f"📍 {ku.chapter} · {ku.section} · {ku.location}")
                    if ku.thresholds:
                        st.markdown(f"**Thresholds:** {ku.thresholds}")
                    if ku.exceptions:
                        st.markdown(f"**Exceptions:** {ku.exceptions}")
                    if ku.algorithm:
                        st.markdown(f"**Algorithm:** {ku.algorithm}")
                    if ku.common_mistakes:
                        st.markdown(f"**Classic pitfall:** {ku.common_mistakes}")
                    for card in result.cards.get(ku.id, []):
                        st.markdown(
                            f"<div class='sb-card'><span class='sb-tag'>L{card.cognitive_level}</span>"
                            f"<span class='sb-tag'>{card.card_type}</span>"
                            f"<span class='sb-tag'>{card.error_target or 'general'}</span><br>"
                            f"<b>{card.question}</b><br>{card.answer}</div>",
                            unsafe_allow_html=True,
                        )

            if result.knowledge_units and st.button("Save to the Second Brain", type="primary"):
                units, cards = extraction.commit_extraction(store, result)
                clear_bridge(f"extract_{source_id}")
                st.success(f"Saved {units} knowledge units and {cards} cards. Next stop: the Anki page.")
                st.rerun()

# ---------------------------------------------------------------------------
with tab_library:
    sources = store.list_sources()
    if not sources:
        empty_state("No sources registered yet.")
    for s in sources:
        units = [k for k in store.list_kus() if k.source_id == s.id]
        mastered = sum(1 for k in units if k.status == "MASTERED")
        st.markdown(
            f"<div class='sb-card'><b>{s.title}</b> <span class='sb-tag'>{s.kind}</span><br>"
            f"<span class='sb-muted'>{s.citation or '—'}</span><br>"
            f"<span class='sb-tag'>{len(units)} knowledge units</span>"
            f"<span class='sb-tag'>{mastered} mastered</span></div>",
            unsafe_allow_html=True,
        )
