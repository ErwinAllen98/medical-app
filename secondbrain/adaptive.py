"""Layers 9-10: adaptive re-questioning.

After targeted re-study we must find out whether the concept was learned or the
original answer was merely memorised. So the next questions must be *different
formulations* of the same knowledge, aimed at the weakest cognitive layer.
"""

from __future__ import annotations

import json

from .diagnostics import UnitProfile
from .extraction import _tags_for
from .llm import extract_json
from .models import Card, KnowledgeUnit, StudyPlan
from .store import Store
from .taxonomy import COGNITIVE_LEVELS, ERROR_TO_LEVEL, ERROR_TYPES

LEVEL_UP_PASS_RATE = 0.8
LEVEL_DOWN_PASS_RATE = 0.5


def next_level(unit: UnitProfile, plan: StudyPlan | None = None) -> int:
    """Dynamic difficulty: always attack the weakest *relevant* cognitive layer."""
    if plan and plan.next_level:
        base = plan.next_level
    else:
        errors = [h["error_type"] for h in unit.error_hypotheses]
        base = max((ERROR_TO_LEVEL.get(e, 2) for e in errors), default=2)

    rates = unit.level_pass_rate
    if not rates:
        return max(1, min(5, base))

    # If a level is still shaky, stay there; otherwise climb.
    for lvl in sorted(rates):
        if rates[lvl] < LEVEL_DOWN_PASS_RATE:
            return lvl
    highest_solid = max((lvl for lvl, r in rates.items() if r >= LEVEL_UP_PASS_RATE), default=0)
    if highest_solid:
        return max(1, min(5, max(base, highest_solid + 1)))
    return max(1, min(5, base))


def build_requestion_prompt(
    store: Store,
    ku: KnowledgeUnit,
    target_level: int,
    error_types: list[str],
    n_items: int = 4,
    language: str = "English question, English answer",
) -> str:
    """Prompt for NotebookLM/Gemini to write NEW items probing a known weakness."""
    existing = [c.question for c in store.list_cards(ku.id, include_retired=True)]
    source_title = store.source_titles().get(ku.source_id, ku.source_id)
    err_block = "\n".join(
        f"  {e}: {ERROR_TYPES[e]['definition']} → remedy: {ERROR_TYPES[e]['remedy']}"
        for e in error_types
        if e in ERROR_TYPES
    ) or "  (no specific error type identified — probe broadly)"
    level_info = COGNITIVE_LEVELS.get(target_level, COGNITIVE_LEVELS[1])

    return f"""You are the adaptive re-questioning layer of a medical Second Brain.

The physician has just re-read the source section below. Your job is to find out
whether the knowledge was actually LEARNED or the previous answer was merely
MEMORISED. Therefore you must NOT repeat any earlier question.

KNOWLEDGE UNIT
  Topic: {ku.topic} › {ku.subtopic}
  Statement: {ku.statement}
  Thresholds: {ku.thresholds or "—"}
  Exceptions: {ku.exceptions or "—"}
  Algorithm: {ku.algorithm or "—"}
  Classic pitfall: {ku.common_mistakes or "—"}

SOURCE (the only allowed knowledge base)
  {source_title} · {ku.chapter} · {ku.section} · {ku.location}

DIAGNOSED WEAKNESS
{err_block}

TARGET COGNITIVE LEVEL: {target_level} — {level_info['label']}
  Goal of this level: {level_info['goal']}

QUESTIONS ALREADY USED (forbidden — reformulate, do not rephrase superficially):
{json.dumps(existing, ensure_ascii=False, indent=2)}

REQUIREMENTS
- Write {n_items} NEW items that attack the diagnosed weakness from different angles:
  the same threshold in a different clinical scenario, boundary cases just above and
  just below the cut-off, the exception rather than the rule, a similar-but-different
  value or drug, and one real clinical application.
- At least one item must be a discrimination item that forces a choice between the
  correct concept and its closest look-alike.
- Stay strictly inside the source. No outside facts.
- Explanations must state why the distractors are wrong.

OUTPUT — STRICT JSON ONLY:
{{
  "cards": [
    {{
      "card_type": "BASIC | MCQ",
      "question": "string",
      "answer": "string",
      "options": ["only for MCQ"],
      "correct_option": 0,
      "explanation": "string",
      "cognitive_level": {target_level},
      "error_target": "one taxonomy key",
      "angle": "boundary_case | exception | different_scenario | look_alike | application"
    }}
  ]
}}
"""


def parse_requestion(raw: str | dict, ku: KnowledgeUnit, generation: int = 2) -> list[Card]:
    data = raw if isinstance(raw, dict) else extract_json(raw)
    items = data.get("cards") if isinstance(data, dict) else data
    cards: list[Card] = []
    for c in items or []:
        if not isinstance(c, dict):
            continue
        question = (c.get("question") or "").strip()
        answer = (c.get("answer") or "").strip()
        if not question or not answer:
            continue
        card_type = (c.get("card_type") or "BASIC").upper()
        options = [str(o).strip() for o in (c.get("options") or []) if str(o).strip()]
        correct = c.get("correct_option")
        try:
            correct = int(correct) if correct is not None else None
        except (TypeError, ValueError):
            correct = None
        if card_type == "MCQ" and len(options) < 2:
            card_type, options, correct = "BASIC", [], None
        try:
            level = max(1, min(5, int(c.get("cognitive_level") or 2)))
        except (TypeError, ValueError):
            level = 2
        error_target = str(c.get("error_target") or "").strip().upper()
        if error_target not in ERROR_TYPES:
            error_target = ""

        tags = _tags_for(ku, level, error_target) + [f"gen::{generation}"]
        angle = str(c.get("angle") or "").strip()
        if angle:
            tags.append(f"angle::{angle}")

        cards.append(
            Card(
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
        )
    return cards


def next_generation(store: Store, ku_id: str) -> int:
    cards = store.list_cards(ku_id, include_retired=True)
    return (max((c.generation for c in cards), default=0)) + 1
