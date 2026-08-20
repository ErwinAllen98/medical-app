"""Mastery detection, the knowledge lifecycle, and the Notion archive."""

from __future__ import annotations

import streamlit as st

from secondbrain import lifecycle, mastery, notion
from secondbrain.config import Settings
from secondbrain.taxonomy import STATUS_FLOW, STATUSES
from secondbrain.ui import empty_state, get_store, page

page(
    "Mastery & archive",
    "UNSEEN → LEARNING → WEAK → RELEARNING → STABLE → MASTERED → ARCHIVED. "
    "Archiving is never permanent: a decline reactivates the unit.",
    "🏆",
)

store = get_store()
settings = Settings.load()

if not store.list_kus():
    empty_state("No knowledge units yet.")
    st.stop()

if st.button("↻ Recompute statuses", width="stretch"):
    transitions = lifecycle.sync_statuses(store)
    promoted = mastery.sweep(store)
    if transitions:
        for t in transitions:
            st.write(f"{t.label}: `{t.old}` → `{t.new}` — {t.reason}")
    if promoted:
        st.balloons()
    st.success(f"{len(transitions)} status changes · {len(promoted)} newly mastered")

counts = lifecycle.counts(store)
cols = st.columns(len(STATUS_FLOW))
for col, status in zip(cols, STATUS_FLOW):
    col.metric(status.title(), counts.get(status, 0), help=STATUSES[status]["meaning"])

tab_status, tab_mastery, tab_notion = st.tabs(["🔄 Lifecycle", "✅ Mastery check", "🗂 Notion"])

# ---------------------------------------------------------------------------
with tab_status:
    for status in STATUS_FLOW:
        units = [ku for ku in store.list_kus() if ku.status == status]
        if not units:
            continue
        st.markdown(f"**{status}** — {STATUSES[status]['meaning']}")
        for ku in units:
            st.markdown(
                f"<div class='sb-card'>{ku.label}"
                f"<span class='sb-tag'>importance {ku.importance}/5</span>"
                + (f"<span class='sb-tag'>mastered {ku.mastered_at[:10]}</span>" if ku.mastered_at else "")
                + "</div>",
                unsafe_allow_html=True,
            )

# ---------------------------------------------------------------------------
with tab_mastery:
    st.caption(
        "One correct answer is not mastery. All six criteria must hold: repeated retrieval, "
        "spread over time, several formulations, clinical application, a clean recent streak, "
        "and no unresolved knowledge gap."
    )
    for report in mastery.evaluate_all(store):
        icon = "✅" if report.mastered else "⏳"
        with st.expander(f"{icon} {report.label} — {report.score:.0%}"):
            st.progress(report.score)
            for c in report.criteria:
                mark = "✅" if c.passed else "⬜️"
                st.markdown(f"{mark} **{c.label}** — <span class='sb-muted'>{c.detail}</span>",
                            unsafe_allow_html=True)

# ---------------------------------------------------------------------------
with tab_notion:
    configured = bool(settings.notion_token and settings.notion_database_id)
    st.markdown(f"**Notion:** {'🟢 configured' if configured else '⚪️ not configured'}")
    st.caption(
        "Only mastered knowledge is archived — with its weakness history: what you used to get "
        "wrong and how it was repaired. Archived units keep being reviewed by Anki."
    )

    ready = [ku for ku in store.list_kus() if ku.status in {"MASTERED", "ARCHIVED"}]
    if not ready:
        empty_state("Nothing mastered yet.", "Keep the loop running — the archive fills itself.")
    else:
        exported = store.notion_exports()
        for ku in ready:
            page_obj = notion.build_page(store, ku.id)
            if not page_obj:
                continue
            tag = "🗂 archived in Notion" if ku.id in exported else "🆕 not exported"
            with st.expander(f"{ku.label} · {tag}"):
                st.markdown(page_obj.markdown)

        c1, c2 = st.columns(2)
        if c1.button("Archive to Notion", type="primary", disabled=not configured, width="stretch"):
            try:
                result = notion.push_mastered(store)
                st.success(f"{result['sent']} pages created · {result['skipped']} already there")
                for err in result["errors"]:
                    st.error(err)
                st.rerun()
            except notion.NotionError as exc:
                st.error(str(exc))
        if c2.button("Export Markdown instead", width="stretch"):
            path = notion.export_markdown(store)
            with open(path, encoding="utf-8") as fh:
                st.download_button("Download notion_mastered.md", fh.read(),
                                   file_name="notion_mastered.md", width="stretch")
