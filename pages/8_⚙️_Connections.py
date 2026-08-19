"""Connections — where the API keys live.

Nothing here is ever sent to a chat or committed to git: the values are written
to `.streamlit/secrets.toml`, which is git-ignored and readable only by you.
"""

from __future__ import annotations

import streamlit as st

from secondbrain import secrets_store
from secondbrain.config import Settings
from secondbrain.ui import get_store, page

page(
    "Connections",
    "Your keys stay on this machine — in .streamlit/secrets.toml, git-ignored. "
    "Never paste them into a chat.",
    "⚙️",
)

get_store()  # ensure the data directory exists
secrets_store.apply_to_env()
settings = Settings.load()
current = secrets_store.read()

# ---------------------------------------------------------------------------
st.markdown(
    """
<div class='sb-card'>
<b>What can actually be connected</b><br><br>
🟢 <b>Claude</b> — full API. Diagnoses why you keep failing.<br>
🟢 <b>Notion</b> — full API. Archives mastered knowledge.<br>
🟢 <b>Anki</b> — no API key; it syncs through your AnkiWeb account.<br>
🟡 <b>Gemini</b> — the plain Gemini API works, and it can read files you upload to it.<br>
🔴 <b>NotebookLM</b> — <b>has no public API at all.</b> Google does not offer one. That step stays
copy-and-paste — which is not a loss: pasting into your own notebook is exactly what keeps the
answers grounded in <i>your</i> sources.
</div>
""",
    unsafe_allow_html=True,
)

state = secrets_store.status(settings)
cols = st.columns(len(state))
for col, (name, ok) in zip(cols, state.items()):
    col.metric(name, "connected" if ok else "—")

# ---------------------------------------------------------------------------
st.subheader("Keys")
with st.form("connections"):
    values: dict[str, str] = {}
    for key, (label, is_secret, help_text, link) in secrets_store.FIELDS.items():
        existing = current.get(key, "")
        caption = help_text + (f"  ·  [get one]({link})" if link else "")
        values[key] = st.text_input(
            label,
            value=existing,
            type="password" if is_secret else "default",
            help=help_text,
            placeholder="not set" if not existing else "",
        )
        st.caption(caption)
    saved = st.form_submit_button("💾 Save", type="primary", width="stretch")

if saved:
    path = secrets_store.write(values)
    st.success(f"Saved to {path} (permissions 600, git-ignored).")
    st.rerun()

# ---------------------------------------------------------------------------
st.subheader("Test the connections")
st.caption("Each test makes the smallest possible real call, so you know it works before you rely on it.")

if st.button("🔌 Test everything", width="stretch"):
    settings = Settings.load()
    for name, test in secrets_store.TESTS.items():
        with st.spinner(f"Testing {name}…"):
            result = test(settings)
        if result.ok:
            st.success(f"**{name}** — {result.message}")
        else:
            st.warning(f"**{name}** — {result.message}")

# ---------------------------------------------------------------------------
with st.expander("Where the keys come from"):
    st.markdown(
        """
| Service | Where | Notes |
|---|---|---|
| Gemini | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Free tier is enough to start |
| Claude | [console.anthropic.com](https://console.anthropic.com/settings/keys) | Pay-as-you-go |
| AnkiWeb | your own AnkiWeb account | The same login you use in AnkiDroid |
| Notion | [notion.so/my-integrations](https://www.notion.so/my-integrations) | Create an *internal* integration, then **Share** your database with it |
| NotebookLM | — | No API exists. Use the Copy-prompt button instead |
"""
    )

with st.expander("Everything still works without any keys"):
    st.markdown(
        """
- **Capture** — copy the prompt into NotebookLM, paste the JSON back.
- **Sync** — build a `.apkg`, open it with AnkiDroid, upload its export back.
- **Diagnosis** — the built-in analysis scores your knowledge gaps without Claude.
- **Prescriptions** — generated locally from your own review history.
- **Notion** — export Markdown instead of pushing pages.

Keys only remove copy-and-paste; they never unlock a feature you would otherwise lose.
"""
    )
