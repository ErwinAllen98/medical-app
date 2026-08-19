"""Shared Streamlit helpers for the Second Brain hub."""

from __future__ import annotations

import streamlit as st

from .config import Settings
from .store import Store

ACCENT = "#1c5f4a"

BASE_CSS = """
<style>
  .sb-hero { background: linear-gradient(135deg, #14352b 0%, #1c5f4a 55%, #2c7a5f 100%);
             color: #f6f4ef; padding: 22px 26px; border-radius: 14px; margin-bottom: 18px; }
  .sb-hero h1 { margin: 0 0 6px 0; font-size: 1.65rem; letter-spacing: -0.01em; }
  .sb-hero p { margin: 0; opacity: .85; font-size: .95rem; }
  .sb-step { display:inline-block; background:#eef3f0; color:#1c5f4a; border:1px solid #cfe0d8;
             border-radius: 999px; padding: 3px 11px; font-size: .78rem; margin: 0 6px 6px 0; }
  .sb-card { border: 1px solid #e6e2d9; border-radius: 12px; padding: 14px 16px;
             background: #fffdf9; margin-bottom: 12px; }
  .sb-tag { display:inline-block; background:#f2efe8; border-radius:6px; padding:1px 7px;
            font-size:.74rem; color:#6b6255; margin-right:5px; font-family: ui-monospace, monospace; }
  .sb-bad { color:#9e1030; font-weight:600; }
  .sb-good { color:#1c5f4a; font-weight:600; }
  .sb-muted { color:#8a8f98; font-size:.85rem; }
  div[data-testid="stMetricValue"] { font-size: 1.5rem; }
</style>
"""


@st.cache_resource
def get_store() -> Store:
    return Store()


def page(title: str, subtitle: str, icon: str = "🧠") -> None:
    st.set_page_config(page_title=f"{title} · Second Brain", page_icon=icon, layout="wide")
    st.markdown(BASE_CSS, unsafe_allow_html=True)
    st.markdown(
        f"<div class='sb-hero'><h1>{icon} {title}</h1><p>{subtitle}</p></div>",
        unsafe_allow_html=True,
    )
    sidebar()


def sidebar() -> None:
    store = get_store()
    settings = Settings.load()
    stats = store.stats()

    with st.sidebar:
        st.markdown("### 🧠 Second Brain")
        st.caption("Closed-loop adaptive medical learning")
        c1, c2 = st.columns(2)
        c1.metric("Knowledge units", stats["knowledge_units"])
        c2.metric("Mastered", stats["mastered"])
        c1.metric("Cards", stats["cards"])
        c2.metric("Reviews", stats["reviews"])

        st.divider()
        st.markdown("**Connections**")
        st.write(_dot(bool(settings.gemini_api_key)) + " Gemini / NotebookLM")
        st.write(_dot(bool(settings.anthropic_api_key)) + " Claude (diagnostics)")
        st.write(_dot(_anki_up(settings)) + " AnkiConnect")
        st.write(_dot(bool(settings.notion_token and settings.notion_database_id)) + " Notion")
        st.caption("Missing keys are fine — every step has a manual copy-paste bridge.")

        st.divider()
        st.caption("Dr Erfan Alinejad Ghadi · Iran Medical Council No. 219890")


def _dot(ok: bool) -> str:
    return "🟢" if ok else "⚪️"


@st.cache_data(ttl=20, show_spinner=False)
def _anki_up(settings: Settings) -> bool:
    from .anki import AnkiConnect

    try:
        return AnkiConnect(settings.anki_connect_url, timeout=2).available()
    except Exception:
        return False


def llm_bridge(
    prompt: str,
    key: str,
    provider: str = "gemini",
    label: str = "Run",
    help_text: str = "",
) -> str | None:
    """Show a prompt, let the doctor run it via API *or* paste the reply back.

    Returns the raw model response when one is available, otherwise ``None``.
    NotebookLM has no public API, so the manual bridge is always offered.
    """
    from .llm import LLMError, call_claude, call_gemini, claude_available, gemini_available

    settings = Settings.load()
    state_key = f"llm_out_{key}"

    with st.expander("📋 The exact prompt (paste this into NotebookLM / Claude)", expanded=False):
        st.code(prompt, language="markdown")
        st.caption(help_text or "Grounded in your sources only — no outside facts allowed.")

    tab_api, tab_manual = st.tabs(["⚡ Run through the API", "📥 Paste the reply"])

    with tab_api:
        available = gemini_available(settings) if provider == "gemini" else claude_available(settings)
        if not available:
            st.info(
                f"No {'GEMINI_API_KEY' if provider == 'gemini' else 'ANTHROPIC_API_KEY'} configured — "
                "use the paste tab, which also keeps NotebookLM's source grounding."
            )
        elif st.button(label, key=f"run_{key}", type="primary"):
            with st.spinner("Thinking…"):
                try:
                    result = call_gemini(prompt, settings) if provider == "gemini" else call_claude(prompt, settings)
                    st.session_state[state_key] = result.text
                except LLMError as exc:
                    st.error(str(exc))

    with tab_manual:
        pasted = st.text_area(
            "Model response (JSON)",
            height=220,
            key=f"paste_{key}",
            placeholder='{"knowledge_units": [ ... ]}',
        )
        if st.button("Use this response", key=f"use_{key}"):
            if pasted.strip():
                st.session_state[state_key] = pasted
            else:
                st.warning("Nothing pasted yet.")

    return st.session_state.get(state_key)


def clear_bridge(key: str) -> None:
    st.session_state.pop(f"llm_out_{key}", None)


def severity_badge(value: float) -> str:
    if value >= 3:
        return f"<span class='sb-bad'>severity {value:.1f}</span>"
    if value >= 1:
        return f"<span style='color:#b0631a;font-weight:600'>severity {value:.1f}</span>"
    return f"<span class='sb-good'>severity {value:.1f}</span>"


def empty_state(message: str, hint: str = "") -> None:
    st.markdown(
        f"<div class='sb-card'><b>{message}</b><br><span class='sb-muted'>{hint}</span></div>",
        unsafe_allow_html=True,
    )
