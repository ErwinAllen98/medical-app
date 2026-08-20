"""Second Brain — one-page, phone-first.

Two sections, zero jargon, big buttons:
  1. کارت بساز  — build flashcards from NotebookLM
  2. چی بلد نیستم — see what you don't know, get fix prompts

Dr Erfan Alinejad Ghadi — Iran Medical Council No. 219890
"""

from __future__ import annotations

import streamlit as st

from secondbrain import simple
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

# --- CSS: mobile-first, big buttons, single column ---
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
  /* hero */
  .sb-hero {
    background: linear-gradient(135deg, #14352b 0%, #1c5f4a 55%, #2c7a5f 100%);
    color: #f6f4ef;
    padding: 18px 22px;
    border-radius: 14px;
    margin-bottom: 20px;
  }
  .sb-hero h1 { margin: 0 0 4px 0; font-size: 1.4rem; }
  .sb-hero p  { margin: 0; opacity: .85; font-size: .9rem; }
  /* card */
  .sb-card {
    border: 1px solid #e6e2d9;
    border-radius: 12px;
    padding: 14px 16px;
    background: #fffdf9;
    margin-bottom: 14px;
  }
  /* section divider */
  .sb-section {
    border-top: 3px solid #1c5f4a;
    padding-top: 18px;
    margin-top: 28px;
  }
  /* weak spot card */
  .ws-label   { font-weight: 700; font-size: 1.05rem; color: #1f2933; }
  .ws-summary { color: #9e1030; font-weight: 600; }
  .ws-source  { color: #4b5563; font-size: .88rem; }
  .ws-time    { color: #6b7280; font-size: .82rem; }
  @media (max-width: 640px) {
    .sb-hero h1 { font-size: 1.15rem; }
    .sb-hero p  { font-size: .8rem; }
  }
</style>
""",
    unsafe_allow_html=True,
)

# --- Hero ---
st.markdown(
    "<div class='sb-hero'><h1>🧠 Second Brain</h1>"
    "<p>کارت بساز از NotebookLM · ببین چی بلد نیستی · درستش کن</p></div>",
    unsafe_allow_html=True,
)

# --- Apply secrets if available ---
try:
    from secondbrain.secrets_store import apply_to_env
    apply_to_env()
except Exception:
    pass

store = get_store()

# ===================================================================
#  SECTION 1 — کارت بساز
# ===================================================================

st.markdown("## 🃏 کارت بساز")

topic = st.text_input(
    "موضوع",
    placeholder="مثلاً: SGLT2 inhibitor thresholds in CKD",
    key="simple_topic",
)

if topic:
    prompt_text = simple.study_prompt(topic)
    copy_button(prompt_text, label="📋 کپی پرامپت — پیست کن تو NotebookLM", key="copy_study")
    st.link_button("🔗 باز کردن NotebookLM", "https://notebooklm.google.com/", use_container_width=True)

st.markdown("---")

reply = st.text_area(
    "📋 جواب NotebookLM رو اینجا پیست کن",
    height=220,
    placeholder='JSON یا جدول | سوال | جواب | یا خطوط Q:/A:',
    key="paste_reply",
)

if st.button("🚀 بساز و بفرست به آنکی", type="primary", use_container_width=True, disabled=not reply.strip()):
    with st.spinner("در حال پردازش…"):
        parsed = simple.parse_reply(reply)

        if not parsed.ok:
            st.error(parsed.raw_error)
            st.stop()

        # Save cards to the store
        result = simple.save_cards(store, parsed)
        cards_saved = result.get("cards_saved", 0)

        if cards_saved == 0:
            st.warning("هیچ کارتی ذخیره نشد. فرمت پیست رو چک کن.")
            st.stop()

        st.success(f"✅ {cards_saved} کارت ذخیره شد!")

        # --- Push to AnkiWeb bridge ---
        anki_msg = ""
        try:
            from secondbrain.ankiweb import AnkiWebBridge, library_available
            settings = Settings.load()
            if library_available() and settings.ankiweb_username and settings.ankiweb_password:
                bridge = AnkiWebBridge(settings)
                # Push the newly created cards
                ku_id = result.get("ku_id", "")
                if ku_id:
                    new_cards = store.list_cards(ku_id=ku_id)
                    pushed = bridge.push(store, cards=new_cards)
                    bridge.sync()
                    anki_msg = f"  → {pushed} کارت رفت تو آنکی"
        except Exception as exc:
            anki_msg = f"  ⚠️ آنکی: {exc}"

        # --- Backup ---
        backup_msg = ""
        try:
            from secondbrain.backup import configured, push as backup_push
            if configured():
                backup_push()
                backup_msg = "  · بکاپ گرفته شد ✅"
        except Exception:
            pass

        st.info(f"{cards_saved} کارت ساخته شد{anki_msg}{backup_msg}")
        # Clear the text area so a new paste can start fresh
        st.rerun()


# ===================================================================
#  SECTION 2 — چی بلد نیستم
# ===================================================================

st.markdown("<div class='sb-section'></div>", unsafe_allow_html=True)
st.markdown("## 🎯 چی بلد نیستم")

if st.button("📥 جواب‌هامو از آنکی بیار", type="primary", use_container_width=True):
    with st.spinner("در حال خواندن جواب‌ها از آنکی…"):
        pulled = 0
        try:
            from secondbrain.ankiweb import AnkiWebBridge, library_available
            from secondbrain.anki import pull_reviews
            settings = Settings.load()
            # Try AnkiConnect first
            try:
                pulled = pull_reviews(store)
            except Exception:
                pass
            # Then AnkiWeb bridge
            if library_available() and settings.ankiweb_username and settings.ankiweb_password:
                bridge = AnkiWebBridge(settings)
                bridge.sync()
                pulled += bridge.pull(store)
        except Exception as exc:
            st.warning(f"آنکی در دسترس نیست: {exc}")

        if pulled:
            st.success(f"{pulled} جواب جدید خونده شد.")
        else:
            st.info("جواب جدیدی نبود — یا آنکی وصل نیست یا هنوز جوابی ثبت نشده.")
        st.rerun()

# --- Show weak spots ---
spots = simple.weak_spots(store, limit=3)

if not spots:
    stats = store.stats()
    if stats["reviews"] == 0:
        st.markdown(
            "<div class='sb-card'>هنوز جوابی از آنکی نیومده.<br>"
            "اول کارت بساز، بعد تو آنکی جواب بده، بعد دکمه‌ی بالا رو بزن.</div>",
            unsafe_allow_html=True,
        )
    elif stats["knowledge_units"] == 0:
        st.markdown(
            "<div class='sb-card'>هنوز کارتی نساختی.<br>"
            "از بخش «کارت بساز» بالا شروع کن.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.success("🎉 چیزی پیدا نشد که ضعف داشته باشی — ادامه بده!")
else:
    for i, spot in enumerate(spots):
        st.markdown(
            f"<div class='sb-card'>"
            f"<div class='ws-label'>{spot.label}</div>"
            f"<div class='ws-summary'>{spot.summary}</div>"
            f"<div class='ws-source'>📖 {spot.source_hint}</div>"
            f"<div class='ws-time'>⏱ {spot.time_estimate}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        # Restudy prompt for this spot
        rp = simple.restudy_prompt(
            topic=spot.label,
            where=spot.source_hint,
            error_types=spot.error_types,
        )
        copy_button(
            rp,
            label=f"📋 کپی پرامپت رفع ضعف — {spot.label}",
            key=f"copy_restudy_{i}",
        )


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
    st.caption("Dr Erfan Alinejad Ghadi · ایران · شماره پروانه ۲۱۹۸۹۰")
