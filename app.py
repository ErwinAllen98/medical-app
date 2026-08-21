"""Second Brain — one-page, phone-first.

Three sections, zero jargon, big buttons:
  1. کارت‌سازی — build flashcards from NotebookLM
  2. ضعف‌ها — Anki lapses + gaps found in chat analysis
  3. تحلیل چت با NotebookLM — check a conversation against your sources

Advanced pages live in ``advanced/`` so Streamlit does not auto-load them.

Dr Erfan Alinejad Ghadi — Iran Medical Council No. 219890
"""

from __future__ import annotations

import html

import streamlit as st

from secondbrain import chat_analysis, simple
from secondbrain.config import Settings
from secondbrain.ui import copy_button, get_store

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Second Brain · یک‌صفحه",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
  .block-container {
    padding-top: 1rem !important;
    padding-bottom: 2rem !important;
    padding-left: .8rem !important;
    padding-right: .8rem !important;
    max-width: 700px;
  }
  .stButton > button, .stDownloadButton > button {
    min-height: 52px !important;
    font-size: 1.1rem !important;
    border-radius: 12px !important;
    width: 100%;
  }
  .stTextInput input, .stTextArea textarea {
    font-size: 17px !important;
  }
  .stTabs [data-baseweb="tab"] {
    font-size: 1.02rem;
    font-weight: 600;
    padding: 10px 14px;
    white-space: nowrap;
  }
  .stTabs [data-baseweb="tab-list"] { overflow-x: auto; scrollbar-width: none; }
  .sb-hero {
    background: linear-gradient(135deg, #14352b 0%, #1c5f4a 55%, #2c7a5f 100%);
    color: #f6f4ef;
    padding: 18px 22px;
    border-radius: 14px;
    margin-bottom: 16px;
  }
  .sb-hero h1 { margin: 0 0 4px 0; font-size: 1.4rem; }
  .sb-hero p  { margin: 0; opacity: .85; font-size: .9rem; }
  .sb-card {
    border: 1px solid #e6e2d9;
    border-radius: 12px;
    padding: 14px 16px;
    background: #fffdf9;
    margin-bottom: 14px;
  }
  .ws-label   { font-weight: 700; font-size: 1.05rem; color: #1f2933; }
  .ws-summary { color: #9e1030; font-weight: 600; }
  .ws-source  { color: #4b5563; font-size: .88rem; }
  .ws-time    { color: #6b7280; font-size: .82rem; }
  .ws-origin  { display:inline-block; background:#eef3f0; color:#1c5f4a;
                border-radius:999px; padding:1px 8px; font-size:.75rem; margin-bottom:6px; }
  .claim-v { font-weight: 700; font-size: .88rem; }
  @media (max-width: 640px) {
    .sb-hero h1 { font-size: 1.15rem; }
    .sb-hero p  { font-size: .8rem; }
  }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    "<div class='sb-hero'><h1>🧠 Second Brain</h1>"
    "<p>کارت‌سازی · ضعف‌ها · تحلیل چت با NotebookLM</p></div>",
    unsafe_allow_html=True,
)

try:
    from secondbrain.secrets_store import apply_to_env

    apply_to_env()
except Exception:
    pass

# Clear widget values *before* the widgets are instantiated on this run.
if st.session_state.pop("_reset_paste_reply", False):
    st.session_state["paste_reply"] = ""
if st.session_state.pop("_reset_chat_reply", False):
    st.session_state["chat_reply"] = ""

store = get_store()

banner = st.session_state.pop("banner", None)
if banner:
    kind, msg = banner
    getattr(st, kind, st.info)(msg)


# ---------------------------------------------------------------------------
# Shared: AnkiWeb push + optional GitHub backup
# ---------------------------------------------------------------------------

def _anki_and_backup(store, ku_id: str) -> str:
    """Best-effort push of newly saved cards. Returns a short Persian suffix."""
    bits: list[str] = []
    try:
        from secondbrain.ankiweb import AnkiWebBridge, library_available

        settings = Settings.load()
        if library_available() and settings.ankiweb_username and settings.ankiweb_password:
            bridge = AnkiWebBridge(settings)
            cards = store.list_cards(ku_id=ku_id) if ku_id else []
            pushed = bridge.push(store, cards=cards) if cards else 0
            bridge.sync()
            if pushed:
                bits.append(f" → {pushed} کارت رفت تو آنکی")
    except Exception as exc:
        bits.append(f"  ⚠️ آنکی: {exc}")

    try:
        from secondbrain.backup import configured, push as backup_push

        if configured():
            backup_push()
            bits.append("  · بکاپ گرفته شد ✅")
    except Exception:
        pass
    return "".join(bits)


def _show_spot(spot: simple.WeakSpot, key_prefix: str, index: int) -> None:
    origin = "از تحلیل چت" if spot.origin == "chat" else "از آنکی"
    st.markdown(
        f"<div class='sb-card'>"
        f"<div class='ws-origin'>{html.escape(origin)}</div>"
        f"<div class='ws-label'>{html.escape(spot.label)}</div>"
        f"<div class='ws-summary'>{html.escape(spot.summary)}</div>"
        f"<div class='ws-source'>📖 {html.escape(spot.source_hint)}</div>"
        f"<div class='ws-time'>⏱ {html.escape(spot.time_estimate)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    rp = simple.restudy_prompt(
        topic=spot.label,
        where=spot.source_hint,
        error_types=spot.error_types,
    )
    copy_button(
        rp,
        label=f"📋 کپی پرامپت رفع ضعف — {spot.label}",
        key=f"{key_prefix}_{index}",
    )


# ===================================================================
#  Three sections on one page
# ===================================================================

tab_cards, tab_weak, tab_chat = st.tabs(
    ["🃏 کارت‌سازی", "🎯 ضعف‌ها", "💬 تحلیل چت"]
)


# -------------------------------------------------------------------
#  1. کارت‌سازی
# -------------------------------------------------------------------
with tab_cards:
    st.markdown("## 🃏 کارت‌سازی")
    st.caption("موضوع بده → پرامپت رو تو NotebookLM پیست کن → جواب رو برگردون → کارت بره آنکی.")

    topic = st.text_input(
        "موضوع",
        placeholder="مثلاً: SGLT2 inhibitor thresholds in CKD",
        key="simple_topic",
    )

    if topic:
        prompt_text = simple.study_prompt(topic)
        copy_button(prompt_text, label="📋 کپی پرامپت — پیست کن تو NotebookLM", key="copy_study")
        st.link_button(
            "🔗 باز کردن NotebookLM",
            "https://notebooklm.google.com/",
            use_container_width=True,
        )

    st.markdown("---")

    reply = st.text_area(
        "📋 جواب NotebookLM رو اینجا پیست کن",
        height=220,
        placeholder="JSON یا جدول | سوال | جواب | یا خطوط Q:/A:",
        key="paste_reply",
    )

    if st.button(
        "🚀 بساز و بفرست به آنکی",
        type="primary",
        use_container_width=True,
        disabled=not (reply or "").strip(),
        key="build_cards",
    ):
        with st.spinner("در حال پردازش…"):
            parsed = simple.parse_reply(reply)

        if not parsed.ok:
            st.error(parsed.raw_error)
        else:
            result = simple.save_cards(store, parsed)
            cards_saved = result.get("cards_saved", 0)
            if cards_saved == 0:
                st.warning("هیچ کارتی ذخیره نشد. فرمت پیست رو چک کن.")
            else:
                extra = _anki_and_backup(store, result.get("ku_id", ""))
                st.session_state["banner"] = (
                    "success",
                    f"✅ {cards_saved} کارت ذخیره شد!{extra}",
                )
                st.session_state["_reset_paste_reply"] = True
                st.rerun()


# -------------------------------------------------------------------
#  2. ضعف‌ها
# -------------------------------------------------------------------
with tab_weak:
    st.markdown("## 🎯 ضعف‌ها")
    st.caption("جواب‌های آنکی + ضعف‌هایی که از تحلیل چت پیدا شدن.")

    if st.button("📥 جواب‌هامو از آنکی بیار", type="primary", use_container_width=True, key="pull_anki"):
        with st.spinner("در حال خواندن جواب‌ها از آنکی…"):
            pulled = 0
            try:
                from secondbrain.anki import pull_reviews
                from secondbrain.ankiweb import AnkiWebBridge, library_available

                settings = Settings.load()
                try:
                    pulled = pull_reviews(store)
                except Exception:
                    pass
                if library_available() and settings.ankiweb_username and settings.ankiweb_password:
                    bridge = AnkiWebBridge(settings)
                    bridge.sync()
                    pulled += bridge.pull(store)
            except Exception as exc:
                st.warning(f"آنکی در دسترس نیست: {exc}")

            if pulled:
                st.session_state["banner"] = ("success", f"{pulled} جواب جدید خونده شد.")
            else:
                st.session_state["banner"] = (
                    "info",
                    "جواب جدیدی نبود — یا آنکی وصل نیست یا هنوز جوابی ثبت نشده.",
                )
            st.rerun()

    spots = simple.weak_spots(store, limit=3)
    chat_gaps = chat_analysis.list_open_gaps(store, limit=3)

    if not spots and not chat_gaps:
        stats = store.stats()
        if stats["reviews"] == 0 and stats["knowledge_units"] == 0:
            st.markdown(
                "<div class='sb-card'>هنوز کارتی نساختی و جوابی از آنکی نیومده.<br>"
                "از بخش «کارت‌سازی» یا «تحلیل چت» شروع کن.</div>",
                unsafe_allow_html=True,
            )
        elif stats["reviews"] == 0:
            st.markdown(
                "<div class='sb-card'>هنوز جوابی از آنکی نیومده.<br>"
                "اول کارت بساز، بعد تو آنکی جواب بده، بعد دکمه‌ی بالا رو بزن.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.success("🎉 چیزی پیدا نشد که ضعف داشته باشی — ادامه بده!")
    else:
        for i, spot in enumerate(spots):
            _show_spot(spot, "copy_restudy", i)
        for i, spot in enumerate(chat_gaps):
            _show_spot(spot, "copy_chat_gap", i)


# -------------------------------------------------------------------
#  3. تحلیل چت با NotebookLM
# -------------------------------------------------------------------
with tab_chat:
    st.markdown("## 💬 تحلیل چت با NotebookLM")
    st.caption(
        "چت NotebookLM، تلگرام، بحث کیس یا هر گفتگوی بالینی رو پیست کن. "
        "NotebookLM فقط با منبع‌های خودت ادعاها رو چک می‌کنه، ضعف‌ها رو می‌گه و کارت می‌سازه."
    )

    uploaded = st.file_uploader(
        "یا فایل متنی چت را آپلود کن",
        type=["txt", "md"],
        key="chat_file",
    )
    if uploaded is not None:
        st.session_state["chat_paste"] = uploaded.getvalue().decode("utf-8", errors="replace")

    chat_text = st.text_area(
        "چت رو اینجا پیست کن",
        height=200,
        placeholder="User: …\nNotebookLM: …\nیا کپی از تلگرام / بحث کیس",
        key="chat_paste",
    )

    focus = st.text_input(
        "تمرکز (اختیاری)",
        placeholder="مثلاً: فقط آستانه‌های SGLT2 در CKD",
        key="chat_focus",
    )

    chat_ready = bool((chat_text or "").strip())
    if chat_ready:
        prompt_text = chat_analysis.analysis_prompt(chat_text, focus=focus or "")
        copy_button(
            prompt_text,
            label="📋 کپی پرامپت تحلیل — پیست کن تو NotebookLM",
            key="copy_chat_prompt",
        )
        st.link_button(
            "🔗 باز کردن NotebookLM",
            "https://notebooklm.google.com/",
            use_container_width=True,
        )

    st.markdown("---")

    chat_reply = st.text_area(
        "📋 جواب NotebookLM رو اینجا پیست کن",
        height=220,
        placeholder='{"topic":"...","claims":[...],"gaps":[...],"cards":[...]}',
        key="chat_reply",
    )

    if st.button(
        "🔎 تحلیل کن",
        type="primary",
        use_container_width=True,
        disabled=not (chat_reply or "").strip(),
        key="run_chat_analysis",
    ):
        parsed = chat_analysis.parse_analysis(chat_reply)
        if not parsed.ok:
            st.session_state.pop("last_analysis", None)
            st.error(parsed.raw_error)
        else:
            st.session_state["last_analysis"] = parsed

    parsed = st.session_state.get("last_analysis")
    if parsed and getattr(parsed, "ok", False):
        _VERDICT_COLOR = {
            "supported": "#1c5f4a",
            "contradicted": "#9e1030",
            "unsupported": "#b0631a",
            "unclear": "#6b7280",
        }
        if parsed.topic:
            st.markdown(f"**موضوع:** {html.escape(parsed.topic)}", unsafe_allow_html=True)
        if parsed.where:
            st.caption(f"📖 {parsed.where}")
        if parsed.summary:
            st.markdown(
                f"<div class='sb-card'>{html.escape(parsed.summary)}</div>",
                unsafe_allow_html=True,
            )

        if parsed.claims:
            st.markdown("#### ادعاها")
            for claim in parsed.claims:
                color = _VERDICT_COLOR.get(claim.verdict, "#6b7280")
                note = f"<div class='ws-time'>{html.escape(claim.note)}</div>" if claim.note else ""
                where = (
                    f"<div class='ws-source'>📖 {html.escape(claim.where)}</div>"
                    if claim.where
                    else ""
                )
                st.markdown(
                    f"<div class='sb-card'>"
                    f"<div class='claim-v' style='color:{color}'>{html.escape(claim.verdict_fa)}</div>"
                    f"<div>{html.escape(claim.text)}</div>"
                    f"{where}{note}</div>",
                    unsafe_allow_html=True,
                )

        if parsed.gaps:
            st.markdown("#### ضعف‌ها")
            for gap in parsed.gaps:
                why = f"<div class='ws-summary'>{html.escape(gap.why)}</div>" if gap.why else ""
                where = (
                    f"<div class='ws-source'>📖 {html.escape(gap.where)}</div>"
                    if gap.where
                    else ""
                )
                st.markdown(
                    f"<div class='sb-card'>"
                    f"<div class='ws-label'>{html.escape(gap.label)}</div>"
                    f"{why}{where}</div>",
                    unsafe_allow_html=True,
                )

        if parsed.cards:
            st.markdown(f"#### {len(parsed.cards)} کارت پیشنهادی")
            with st.expander("پیش‌نمایش کارت‌ها"):
                for card in parsed.cards:
                    st.markdown(f"**Q.** {card['q']}")
                    st.markdown(f"**A.** {card['a']}")
                    st.caption(simple.KIND_LABELS.get(card.get("kind", "fact"), card.get("kind", "")))
                    st.divider()

        if st.button(
            "🚀 ذخیره کن و بفرست به آنکی",
            type="primary",
            use_container_width=True,
            key="save_chat_analysis",
        ):
            with st.spinner("در حال ذخیره…"):
                result = chat_analysis.save_analysis(store, parsed)
            extra = _anki_and_backup(store, result.get("ku_id", ""))
            n = result.get("cards_saved", 0)
            g = result.get("gaps", 0)
            st.session_state["banner"] = (
                "success",
                f"✅ {n} کارت ذخیره شد · {g} ضعف ثبت شد{extra}",
            )
            st.session_state["_reset_chat_reply"] = True
            st.rerun()


# ===================================================================
#  Tiny sidebar — just stats, no jargon
# ===================================================================
with st.sidebar:
    stats = store.stats()
    st.markdown("### 🧠 Second Brain")
    st.metric("کارت", stats["cards"])
    st.metric("جواب", stats["reviews"])
    st.metric("یاد گرفته", stats["mastered"])
    st.divider()
    st.caption("صفحات پیشرفته در پوشه advanced/ هستن — این صفحه همان سه بخش است.")
    st.caption("Dr Erfan Alinejad Ghadi · ایران · شماره پروانه ۲۱۹۸۹۰")
