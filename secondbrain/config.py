"""Runtime configuration for the Second Brain pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SECOND_BRAIN_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "second_brain.db"
EXPORT_DIR = DATA_DIR / "exports"


def _secret(name: str, default: str = "") -> str:
    """Read a setting from env first, then Streamlit secrets when available."""
    value = os.environ.get(name)
    if value:
        return value
    try:  # Streamlit is optional at import time (CLI use).
        import streamlit as st  # type: ignore

        return str(st.secrets[name])  # type: ignore[index]
    except Exception:
        return default


@dataclass
class Settings:
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    notion_token: str = ""
    notion_database_id: str = ""
    anki_connect_url: str = "http://127.0.0.1:8765"
    anki_deck: str = "Second Brain::Medical"
    anki_model: str = "Second Brain Basic"
    gemini_model: str = "gemini-2.5-flash"
    claude_model: str = "claude-sonnet-4-5"

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            gemini_api_key=_secret("GEMINI_API_KEY"),
            anthropic_api_key=_secret("ANTHROPIC_API_KEY"),
            notion_token=_secret("NOTION_TOKEN"),
            notion_database_id=_secret("NOTION_DATABASE_ID"),
            anki_connect_url=_secret("ANKI_CONNECT_URL", "http://127.0.0.1:8765"),
            anki_deck=_secret("ANKI_DECK", "Second Brain::Medical"),
            anki_model=_secret("ANKI_MODEL", "Second Brain Basic"),
            gemini_model=_secret("GEMINI_MODEL", "gemini-2.5-flash"),
            claude_model=_secret("CLAUDE_MODEL", "claude-sonnet-4-5"),
        )


# ---------------------------------------------------------------------------
# Tunables for the adaptive loop
# ---------------------------------------------------------------------------

# Mastery criterion (section 11)
MASTERY_MIN_SUCCESSES = 4          # correct retrievals required
MASTERY_MIN_SPAN_DAYS = 21         # spread over time, not one session
MASTERY_MIN_FORMULATIONS = 2       # different question wordings
MASTERY_MIN_APPLICATION_LEVEL = 4  # at least one correct at level >= 4
MASTERY_CLEAN_STREAK = 3           # last N reviews must be lapse-free
MASTERY_MIN_STABILITY_DAYS = 21.0  # FSRS stability floor

# Weakness detection
REPEATED_FAILURE_THRESHOLD = 3     # lapses on one item => repeated failure
HIGH_FAILURE_RATE = 0.34           # failure rate that flags a knowledge unit
RECURRENT_CONCEPT_MIN_UNITS = 2    # failing units in a topic => topic pattern
