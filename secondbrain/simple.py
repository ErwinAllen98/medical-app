"""Simple, phone-first interface — no jargon, no multi-page confusion.

Every function speaks plain language so the UI never needs to translate
internal terms like THRESHOLD_ERROR or gap_score into something a doctor
can read while walking between patients.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .diagnostics import UnitProfile, WeaknessProfile, build_profile
from .models import Card, KnowledgeUnit, new_id, now_iso
from .store import Store

# ---------------------------------------------------------------------------
# Kind → internal error_target mapping
# ---------------------------------------------------------------------------
KIND_TO_ERROR: dict[str, str] = {
    "fact": "FACTUAL_ERROR",
    "number": "THRESHOLD_ERROR",
    "difference": "DISCRIMINATION_ERROR",
    "decision": "MANAGEMENT_ERROR",
    "exception": "EXCEPTION_ERROR",
}

# Human-readable Persian labels for each kind
KIND_LABELS: dict[str, str] = {
    "fact": "حقیقت",
    "number": "عدد",
    "difference": "تفاوت",
    "decision": "تصمیم",
    "exception": "استثنا",
}

# ---------------------------------------------------------------------------
# study_prompt  —  the prompt the user pastes into NotebookLM
# ---------------------------------------------------------------------------

def study_prompt(topic: str) -> str:
    """Return a short prompt (≤15 lines) the user pastes into NotebookLM.

    NotebookLM will only use sources already loaded in that notebook —
    no outside facts allowed.
    """
    return f"""You are a medical flashcard generator. Use ONLY the sources in this notebook — no outside knowledge.
Topic: {topic}
Make exactly 10 flashcards. Output ONLY valid JSON:
{{"topic":"{topic}","where":"chapter/section/page","cards":[{{"q":"...","a":"...","kind":"fact"}}]}}
For "kind" use one of: fact (discrete fact), number (cut-off/dose/range), difference (A-vs-B distinction), decision (next step/management), exception (contraindication/special population).
Do not add any text before or after the JSON."""


# ---------------------------------------------------------------------------
# parse_reply  —  accept 3 formats from NotebookLM
# ---------------------------------------------------------------------------

@dataclass
class ParsedCards:
    topic: str = ""
    where: str = ""
    cards: list[dict[str, str]] = None  # type: ignore[assignment]
    raw_error: str = ""

    def __post_init__(self) -> None:
        if self.cards is None:
            self.cards = []

    @property
    def ok(self) -> bool:
        return bool(self.cards) and not self.raw_error


def parse_reply(text: str) -> ParsedCards:
    """Parse the model reply: JSON, markdown table, or Q:/A: lines.

    Returns a ParsedCards.  If nothing is recognised, raw_error is set.
    """
    text = text.strip()
    if not text:
        return ParsedCards(raw_error="هیچ متنی وارد نشده.")

    # --- 1. JSON -----------------------------------------------------------
    result = _try_json(text)
    if result is not None:
        return result

    # --- 2. Markdown table  | سوال | جواب |  -----------------------------
    result = _try_table(text)
    if result is not None:
        return result

    # --- 3. Q: / A: lines --------------------------------------------------
    result = _try_qa(text)
    if result is not None:
        return result

    return ParsedCards(raw_error="فرمت پیست شده قابل تشخیص نیست.\n\nسه فرمت پذیرفته:\n1) JSON\n2) جدول مارک‌داون: | سوال | جواب |\n3) خطوط Q: و A:")


def _try_json(text: str) -> ParsedCards | None:
    """Extract JSON even if wrapped in ```json ... ``` or has leading text."""
    # Try to find a JSON object in the text
    candidates = [text]
    # Extract from code fences
    for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL):
        candidates.insert(0, m.group(1))
    # Find first { ... }
    start = text.find("{")
    if start >= 0:
        candidates.insert(0, text[start:])

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict) or "cards" not in obj:
            continue
        cards = []
        for c in obj["cards"]:
            if not isinstance(c, dict):
                continue
            q = c.get("q", c.get("question", "")).strip()
            a = c.get("a", c.get("answer", "")).strip()
            if not q or not a:
                continue
            kind = c.get("kind", "fact").strip().lower()
            if kind not in KIND_TO_ERROR:
                kind = "fact"
            cards.append({"q": q, "a": a, "kind": kind})
        if not cards:
            continue
        return ParsedCards(
            topic=obj.get("topic", ""),
            where=obj.get("where", ""),
            cards=cards,
        )
    return None


def _try_table(text: str) -> ParsedCards | None:
    """Parse a markdown table: | سوال | جواب | or | Q | A |."""
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
    if len(lines) < 2:
        return None
    cards: list[dict[str, str]] = []
    header_seen = False
    for line in lines:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        # Skip separator lines like |---|---|
        if all(set(c) <= {"-", ":"} for c in cells):
            continue
        # First non-separator row is the header — skip it
        if not header_seen:
            header_seen = True
            continue
        if len(cells) >= 2:
            cards.append({"q": cells[0], "a": cells[1], "kind": "fact"})
    if not cards:
        return None
    return ParsedCards(cards=cards)


def _try_qa(text: str) -> ParsedCards | None:
    """Parse Q: ... / A: ... lines."""
    cards: list[dict[str, str]] = []
    current_q: str = ""
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^Q\s*[:.]", stripped, re.IGNORECASE):
            current_q = re.sub(r"^Q\s*[:.]\s*", "", stripped, flags=re.IGNORECASE)
        elif re.match(r"^A\s*[:.]", stripped, re.IGNORECASE) and current_q:
            answer = re.sub(r"^A\s*[:.]\s*", "", stripped, flags=re.IGNORECASE)
            cards.append({"q": current_q, "a": answer, "kind": "fact"})
            current_q = ""
    if not cards:
        return None
    return ParsedCards(cards=cards)


# ---------------------------------------------------------------------------
# save_cards  —  persist one paste as a KnowledgeUnit + its cards
# ---------------------------------------------------------------------------

def save_cards(store: Store, parsed: ParsedCards) -> dict:
    """One paste = one KnowledgeUnit + N cards.

    Returns a summary dict: {"ku_id": ..., "cards_saved": ...}
    """
    if not parsed.ok:
        return {"ku_id": "", "cards_saved": 0, "error": parsed.raw_error}

    topic = parsed.topic or "نامشخص"

    # Ensure a source exists (FK constraint requires it)
    source_title = f"NotebookLM — {topic}"
    source = store.find_source_by_title(source_title)
    if not source:
        from .models import Source
        source = Source(title=source_title, kind="notebooklm", citation="Imported via simple interface")
        store.upsert_source(source)

    ku = KnowledgeUnit(
        topic=topic,
        subtopic="",
        statement=f"{len(parsed.cards)} کارت از {topic}",
        source_id=source.id,
        chapter=parsed.where or "",
        section="",
        location="",
    )
    store.upsert_ku(ku)

    saved = 0
    for c in parsed.cards:
        kind = c.get("kind", "fact")
        error_target = KIND_TO_ERROR.get(kind, "FACTUAL_ERROR")
        card = Card(
            ku_id=ku.id,
            question=c["q"],
            answer=c["a"],
            card_type="BASIC",
            error_target=error_target,
            tags=[f"simple::{kind}", "notebooklm"],
        )
        store.upsert_card(card)
        saved += 1

    store.log_event("simple_save", {"ku_id": ku.id, "cards": saved})
    return {"ku_id": ku.id, "cards_saved": saved}


# ---------------------------------------------------------------------------
# weak_spots  —  plain-language summary of what you don't know
# ---------------------------------------------------------------------------

@dataclass
class WeakSpot:
    label: str          # topic label in simple language
    summary: str        # e.g. "۱۰ بار از ۱۹ بار غلط — عددها از دستت در می‌رن"
    source_hint: str    # where to read, e.g. "[منبع·بخش]"
    time_estimate: str  # e.g. "حدود ۵ دقیقه"
    ku_id: str = ""     # internal id for the restudy prompt
    error_types: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.error_types is None:
            self.error_types = []


# Persian labels for internal error types
_ERROR_PERSIAN: dict[str, str] = {
    "FACTUAL_ERROR": "حقیقت‌ها یادت نمی‌مونن",
    "THRESHOLD_ERROR": "عددها از دستت در می‌رن",
    "DISCRIMINATION_ERROR": "دوتا چیز شبیه‌ هم رو قاطی می‌کنی",
    "MANAGEMENT_ERROR": "تصمیم‌گیری‌ها مشکل داره",
    "EXCEPTION_ERROR": "استثناها رو فراموش می‌کنی",
    "CONCEPT_ERROR": "مکانیزمش رو نفهمیدی",
    "SEQUENCE_ERROR": "ترتیب قدم‌ها رو بلد نیستی",
    "INDICATION_ERROR": "کی باید استفاده کنی رو نمی‌دونی",
    "CONTRAINDICATION_ERROR": "منع مصرف‌ها رو بلد نیستی",
    "MONITORING_ERROR": "پیگیری و پایش مشکل داره",
}


def weak_spots(store: Store, limit: int = 3) -> list[WeakSpot]:
    """Return the top weak spots in plain Persian.

    Uses diagnostics.build_profile under the hood, but the output
    contains zero jargon — just what's wrong, where to read, and how long.
    """
    profile = build_profile(store)
    weak = [u for u in profile.weak_units if u.attempts > 0]
    weak.sort(key=lambda u: u.priority, reverse=True)

    spots: list[WeakSpot] = []
    for unit in weak[:limit]:
        # --- plain summary ---
        failures = unit.failures
        attempts = unit.attempts
        top_error = unit.top_error or "FACTUAL_ERROR"
        persian_error = _ERROR_PERSIAN.get(top_error, "مشکل داری")

        summary = f"{failures} بار از {attempts} بار غلط — {persian_error}"

        # --- source hint ---
        ku = store.get_ku(unit.ku_id)
        source_parts: list[str] = []
        if ku:
            source_title = store.source_titles().get(ku.source_id, "")
            for part in (source_title, ku.chapter, ku.section, ku.location):
                if part:
                    source_parts.append(part)
        source_hint = " · ".join(source_parts) if source_parts else "منبع ثبت نشده"

        # --- time estimate (very rough) ---
        # Assume ~5 min per weak unit, more if multiple error types
        minutes = max(5, 5 * len(unit.error_hypotheses))
        time_estimate = f"حدود {minutes} دقیقه"

        spots.append(WeakSpot(
            label=unit.label,
            summary=summary,
            source_hint=source_hint,
            time_estimate=time_estimate,
            ku_id=unit.ku_id,
            error_types=[h["error_type"] for h in unit.error_hypotheses],
        ))
    return spots


# ---------------------------------------------------------------------------
# restudy_prompt  —  targeted re-study for one weak spot
# ---------------------------------------------------------------------------

def restudy_prompt(
    topic: str,
    where: str = "",
    error_types: list[str] | None = None,
    minutes: int = 5,
) -> str:
    """Prompt for NotebookLM: re-study only the identified weak spot.

    Asks NotebookLM to:
      - show only the relevant section (≤ N minutes of reading)
      - generate 4 new questions from a different angle
    """
    error_desc = ""
    if error_types:
        parts = [_ERROR_PERSIAN.get(e, e) for e in error_types[:2]]
        error_desc = "مشکل: " + " و ".join(parts)

    where_line = f"\nWhere: {where}" if where else ""

    return f"""You are a medical tutor helping a doctor fix a specific weakness.
Use ONLY the sources in this notebook — no outside knowledge.

Topic: {topic}{where_line}
{error_desc}
Budget: ≤ {minutes} minutes of reading.

Instructions:
1. Show ONLY the relevant section — skip everything else.
2. Then make 4 NEW flashcards from a DIFFERENT angle than before
   (e.g. if the previous cards asked for numbers, ask about mechanisms;
    if they asked for definitions, ask about exceptions or clinical cases).
3. Output ONLY valid JSON:
{{
  "topic": "{topic}",
  "where": "chapter/section/page",
  "cards": [
    {{"q": "...", "a": "...", "kind": "fact|number|difference|decision|exception"}}
  ]
}}

Do not repeat any question the user has already seen."""
