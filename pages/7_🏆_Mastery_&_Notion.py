"""Layers 11-12 — the mastery criterion and the Notion repository."""

from __future__ import annotations

import streamlit as st

from secondbrain import mastery, notion
from secondbrain.config import Settings
from secondbrain.ui import empty_state, get_store, page

page(
    "Mastery & Notion",
    "One correct answer is not mastery. A unit is archived only after repeated, time-spread, "
    "multi-formulation, application-level success with no error pattern left.",
    "🏆",
)

store = get_store()
settings = Settings.load()
reports = mastery.evaluate_all(store)

if not reports:
    empty_state("No knowledge units yet.")
    st.stop()

mastered = [r for r in reports if r.mastered]
c1, c2, c3 = st.columns(3)
c1.metric("Mastered", len(mastered))
c2.metric("In progress", len(reports) - len(mastered))
c3.metric("Pages in Notion", store.stats()["notion_pages"])

tab_mastery, tab_notion = st.tabs(["✅ Mastery check", "🗂 Notion repository"])

with tab_mastery:
    if st.button("Re-evaluate everything and promote what qualifies", type="primary"):
        promoted = mastery.sweep(store)
        if promoted:
            st.balloons()
            for r in promoted:
                st.success(f"MASTERED — {r.label}")
        else:
            st.info("Nothing new qualifies yet.")
        st.rerun()

    for report in reports:
        ku = store.get_ku(report.ku_id)
        icon = "✅" if report.mastered else "⏳"
        with st.expander(f"{icon} {report.label} — {report.score:.0%}", expanded=False):
            st.progress(report.score)
            for c in report.criteria:
                mark = "✅" if c.passed else "⬜️"
                st.markdown(f"{mark} **{c.label}** — <span class='sb-muted'>{c.detail}</span>",
                            unsafe_allow_html=True)
            if ku and ku.status != "MASTERED" and report.mastered:
                if st.button("Mark as mastered", key=f"promote_{report.ku_id}"):
                    mastery.promote(store, report.ku_id)
                    st.rerun()

with tab_notion:
    st.caption(
        "Notion is the long-term repository, not the reasoning engine. Each page records the core "
        "knowledge, its source location — and the weakness history that produced the mastery."
    )
    configured = bool(settings.notion_token and settings.notion_database_id)
    st.markdown(f"**Notion API:** {'🟢 configured' if configured else '⚪️ not configured'}")
    if not configured:
        st.caption(
            "Add NOTION_TOKEN and NOTION_DATABASE_ID to your secrets, or use the Markdown export below. "
            "Suggested database properties: Topic, Subtopic, Status, Source, Source location, "
            "Importance (number), Mastery score (number), Anki tags, Anki note IDs."
        )

    if not mastered:
        empty_state("Nothing mastered yet.", "Keep the loop running — the archive fills itself.")
    else:
        exported = store.notion_exports()
        for report in mastered:
            page_obj = notion.build_page(store, report.ku_id)
            if not page_obj:
                continue
            status = "🗂 in Notion" if report.ku_id in exported else "🆕 not exported"
            with st.expander(f"{report.label} · {status}"):
                st.markdown(page_obj.markdown)

        c1, c2 = st.columns(2)
        if c1.button("Push mastered units to Notion", type="primary", disabled=not configured):
            try:
                result = notion.push_mastered(store)
                st.success(f"{result['sent']} pages created · {result['skipped']} already there")
                for err in result["errors"]:
                    st.error(err)
                st.rerun()
            except notion.NotionError as exc:
                st.error(str(exc))

        if c2.button("Export Markdown instead"):
            path = notion.export_markdown(store)
            with open(path, encoding="utf-8") as fh:
                st.download_button("Download notion_mastered.md", fh.read(),
                                   file_name="notion_mastered.md")
            st.success(f"Written to {path}")
