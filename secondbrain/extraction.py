"""Layer 1-2: source-grounded knowledge extraction (NotebookLM / Gemini).

Everything produced here must be traceable to the uploaded source. Items that
cannot name their chapter/section/location are rejected by ``parse_extraction``
unless ``strict=False``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import extract_json
from .models import Card, KnowledgeUnit, Source
from .taxonomy import COGNITIVE_LEVELS, ERROR_TYPE_KEYS

EXTRACTION_SCHEMA = {
    "knowledge_units": [
        {
            "topic": "string — broad clinical topic, e.g. 'Type 2 diabetes'",
            "subtopic": "string — precise focus, e.g. 'SGLT2 inhibitor initiation'",
            "statement": "string — the knowledge unit in one or two precise sentences",
            "clinical_significance": "string — why this matters at the bedside",
            "thresholds": "string — numeric cut-offs, ranges, doses ('' if none)",
            "exceptions": "string — special populations / exceptions ('' if none)",
            "algorithm": "string — ordered steps if the unit is an algorithm ('' if none)",
            "common_mistakes": "string — the classic error doctors make here",
            "chapter": "string — chapter in the source",
            "section": "string — section/heading in the source",
            "location": "string — page number, table, figure or timestamp",
            "why_relevant": "string — why this exact location answers this unit",
            "importance": "integer 1-5 — clinical importance",
            "cards": [
                {
                    "card_type": "BASIC | CLOZE | MCQ",
                    "question": "string",
                    "answer": "string — for MCQ, the full text of the correct option",
                    "options": ["only for MCQ: 4 option strings"],
                    "correct_option": "only for MCQ: 0-based index of the correct option",
                    "explanation": "string — why the answer is right, grounded in the source",
                    "cognitive_level": "integer 1-5",
                    "error_target": "one of the error taxonomy keys this item probes",
                }
            ],
        }
    ]
}


@dataclass
class ExtractionResult:
    knowledge_units: list[KnowledgeUnit] = field(default_factory=list)
    cards: dict[str, list[Card]] = field(default_factory=dict)  # ku_id -> cards
    rejected: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def card_count(self) -> int:
        return sum(len(v) for v in self.cards.values())


def _levels_block() -> str:
    return "\n".join(
        f"  {lvl}. {info['label']} — {info['goal']}" for lvl, info in COGNITIVE_LEVELS.items()
    )


def build_extraction_prompt(
    source: Source,
    scope: str = "",
    max_units: int = 12,
    language: str = "English question, English answer",
    focus_errors: list[str] | None = None,
) -> str:
    """Prompt to paste into NotebookLM (or send to Gemini) for a given source."""
    focus = ""
    if focus_errors:
        focus = (
            "\nPRIORITY: bias the items towards these error types, because they are "
            "known weaknesses: " + ", ".join(focus_errors) + "\n"
        )
    scope_line = f"Restrict yourself to this scope inside the source: {scope}\n" if scope else ""

    return f"""You are the knowledge-extraction layer of a closed-loop medical learning system.

SOURCE (the ONLY knowledge you may use)
  Title: {source.title}
  Type: {source.kind}
  Citation: {source.citation or "n/a"}

HARD RULES
1. Use ONLY the uploaded source. Never add outside facts, and never fill gaps from
   general knowledge. If the source does not say it, it does not exist.
2. Every knowledge unit MUST be traceable: chapter, section, and page/table/figure.
   If you cannot locate it in the source, do not emit it.
3. Optimise for long-term retention of clinically important knowledge, NOT for the
   number of cards. Fewer, sharper units win.
4. One knowledge unit = one clinically meaningful idea. Apply the Minimum
   Information Principle to the cards derived from it.
5. Cover: core facts, concepts, clinical reasoning, diagnosis, differential
   diagnosis, indications, contraindications, treatment, monitoring, thresholds,
   exceptions, sequences/algorithms and guideline-based decisions.
{scope_line}{focus}
COGNITIVE LEVELS for the cards:
{_levels_block()}

ERROR TAXONOMY (pick the one each card probes):
{", ".join(ERROR_TYPE_KEYS)}

OUTPUT
Return STRICT JSON ONLY, no prose, no code fences, matching this schema:
{json.dumps(EXTRACTION_SCHEMA, ensure_ascii=False, indent=2)}

Produce at most {max_units} knowledge units, each with 2-4 cards spread across
cognitive levels (at least one level 1-2 item and one level 3-4 item).
Language of the cards: {language}.
"""


def parse_extraction(
    raw: str | dict,
    source: Source,
    strict: bool = True,
    generation: int = 1,
) -> ExtractionResult:
    """Validate the model output and turn it into domain objects."""
    data = raw if isinstance(raw, (dict, list)) else extract_json(raw)
    if isinstance(data, list):
        data = {"knowledge_units": data}
    units = data.get("knowledge_units") or data.get("units") or []

    result = ExtractionResult()
    for item in units:
        if not isinstance(item, dict):
            continue
        statement = (item.get("statement") or "").strip()
        topic = (item.get("topic") or "").strip()
        if not statement or not topic:
            result.rejected.append({"reason": "missing topic or statement", "item": item})
            continue

        chapter = (item.get("chapter") or "").strip()
        section = (item.get("section") or "").strip()
        location = str(item.get("location") or "").strip()
        if strict and not (chapter or section or location):
            result.rejected.append({"reason": "not traceable to the source", "item": item})
            continue

        try:
            importance = max(1, min(5, int(item.get("importance") or 3)))
        except (TypeError, ValueError):
            importance = 3

        ku = KnowledgeUnit(
            topic=topic,
            subtopic=(item.get("subtopic") or "").strip(),
            statement=statement,
            clinical_significance=(item.get("clinical_significance") or "").strip(),
            thresholds=(item.get("thresholds") or "").strip(),
            exceptions=(item.get("exceptions") or "").strip(),
            algorithm=(item.get("algorithm") or "").strip(),
            common_mistakes=(item.get("common_mistakes") or "").strip(),
            source_id=source.id,
            chapter=chapter,
            section=section,
            location=location,
            why_relevant=(item.get("why_relevant") or "").strip(),
            importance=importance,
        )

        cards: list[Card] = []
        for c in item.get("cards") or []:
            card = _parse_card(c, ku, generation)
            if card:
                cards.append(card)
            else:
                result.rejected.append({"reason": "invalid card", "item": c})
        if not cards:
            result.warnings.append(f"'{ku.label}' arrived without any usable card.")

        result.knowledge_units.append(ku)
        result.cards[ku.id] = cards

    if not result.knowledge_units:
        result.warnings.append("No knowledge unit survived validation.")
    return result


def _parse_card(c: dict, ku: KnowledgeUnit, generation: int) -> Card | None:
    if not isinstance(c, dict):
        return None
    question = (c.get("question") or "").strip()
    answer = (c.get("answer") or "").strip()
    if not question or not answer:
        return None

    card_type = (c.get("card_type") or "BASIC").upper()
    if card_type not in {"BASIC", "CLOZE", "MCQ"}:
        card_type = "BASIC"

    options = [str(o).strip() for o in (c.get("options") or []) if str(o).strip()]
    correct = c.get("correct_option")
    try:
        correct = int(correct) if correct is not None else None
    except (TypeError, ValueError):
        correct = None
    if card_type == "MCQ":
        if len(options) < 2:
            card_type = "BASIC"
            options, correct = [], None
        elif correct is None or not (0 <= correct < len(options)):
            correct = next((i for i, o in enumerate(options) if o.lower() == answer.lower()), 0)

    try:
        level = max(1, min(5, int(c.get("cognitive_level") or 1)))
    except (TypeError, ValueError):
        level = 1

    error_target = str(c.get("error_target") or "").strip().upper()
    if error_target not in ERROR_TYPE_KEYS:
        error_target = ""

    tags = _tags_for(ku, level, error_target)
    return Card(
        ku_id=ku.id,
        question=question,
        answer=answer,
        card_type=card_type,
        options=options,
        correct_option=correct,
        explanation=(c.get("explanation") or "").strip(),
        cognitive_level=level,
        error_target=error_target,
        tags=tags,
        generation=generation,
    )


def _slug(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in text.strip())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_") or "general"


def _tags_for(ku: KnowledgeUnit, level: int, error_target: str) -> list[str]:
    tags = [
        "SecondBrain",
        f"KU::{ku.id}",
        f"topic::{_slug(ku.topic)}",
        f"level::L{level}",
    ]
    if ku.subtopic:
        tags.append(f"subtopic::{_slug(ku.subtopic)}")
    if error_target:
        tags.append(f"probes::{error_target}")
    return tags


def commit_extraction(store, result: ExtractionResult) -> tuple[int, int]:
    """Persist an extraction result. Returns (units, cards) written."""
    for ku in result.knowledge_units:
        store.upsert_ku(ku)
        for card in result.cards.get(ku.id, []):
            store.upsert_card(card)
    store.log_event(
        "extraction",
        {
            "units": len(result.knowledge_units),
            "cards": result.card_count,
            "rejected": len(result.rejected),
        },
    )
    return len(result.knowledge_units), result.card_count
