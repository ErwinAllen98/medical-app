"""Point-of-care layer — clinical tools that apply the mastered knowledge.

The Second Brain is not only about remembering: the last mile is using the
knowledge at the bedside. This page hosts the standalone clinical tools.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from secondbrain.ui import page

page(
    "Clinical tools",
    "The application layer of the loop — knowledge that has been mastered is used here, at the bedside.",
    "💉",
)

HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "tirzepatide.html"

st.caption(
    "Tirzepatide Pen Master Calculator — pen dial status and injection simulator. "
    "60 clicks = 0.6 mL; the pen holds 240 units."
)

if HTML_PATH.exists():
    components.html(HTML_PATH.read_text(encoding="utf-8"), height=980, scrolling=True)
    with open(HTML_PATH, "rb") as fh:
        st.download_button(
            "⬇︎ Download the standalone calculator (works offline)",
            fh.read(),
            file_name="tirzepatide_calculator.html",
            mime="text/html",
        )
else:
    st.error(f"Calculator not found at {HTML_PATH}")

st.divider()
st.markdown(
    """
**Why this lives inside the Second Brain**

A dosing tool is where the loop pays off: the knowledge units about tirzepatide titration,
contraindications and monitoring are extracted from your sources, tested in Anki, repaired
through targeted re-study — and then applied here without arithmetic errors.
"""
)
