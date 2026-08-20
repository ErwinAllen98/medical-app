"""The Learning Prescription — and the prompt that sends the loop back to NotebookLM.

A prescription answers six questions, never more:

    WHAT  I do not know
    WHY   it matters / why it keeps failing
    WHERE in the source it is repaired
    WHAT  concept must be relearned
    HOW   to learn it (reading, comparison, clinical case, MCQ, cloze, retrieval…)
    HOW MUCH is enough — minimum necessary learning, maximum knowledge gain

It then emits a ready-to-paste prompt for Gemini NotebookLM, so the loop closes:
Anki performance → Claude → prescription → NotebookLM → new material → Anki.
"""

from __future__ import annotations

from .diagnostics import UnitProfile, WeaknessProfile
from .models import KnowledgeUnit, StudyPlan
from .restudy import review_target
from .store import Store
from .taxonomy import (
    COGNITIVE_LEVELS,
    ERROR_TO_LEVEL,
    ERROR_TYPES,
    LEARNING_METHODS,
    methods_for,
)

# ---------------------------------------------------------------------------
# HOW MUCH — the dose of study, kept deliberately small
# ---------------------------------------------------------------------------

_DOSE_BY_ERROR = {
    "FACTUAL_ERROR": "One paragraph or one table row. 5 minutes.",
    "THRESHOLD_ERROR": "Only the numbers and their units — one table. 5–8 minutes.",
    "EXCEPTION_ERROR": "The rule plus its exception list. 8 minutes.",
    "DISCRIMINATION_ERROR": "The two entities side by side, nothing else. 10 minutes.",
    "CONCEPT_ERROR": "The mechanism paragraph, until you can explain it aloud. 12 minutes.",
    "SEQUENCE_ERROR": "The algorithm figure only. 10 minutes.",
    "INDICATION_ERROR": "The indication list with its evidence grade. 10 minutes.",
    "CONTRAINDICATION_ERROR": "Absolute vs relative contraindications. 10 minutes.",
    "MONITORING_ERROR": "The monitoring schedule table. 8 minutes.",
    "MANAGEMENT_ERROR": "The management algorithm end to end. 15 minutes.",
}


def _dose(error_types: list[str], unit: UnitProfile | None) -> str:
    base = next((_DOSE_BY_ERROR[e] for e in error_types if e in _DOSE_BY_ERROR),
                "One focused pass over the identified section. 10 minutes.")
    if unit and (unit.failure_rate >= 0.6 or "KNOWLEDGE_GAP" in unit.signatures):
        return base + " Read it twice, then close the book and say it out loud."
    return base + " Do not read the rest of the chapter."


def _objective(ku: KnowledgeUnit, error_types: list[str], level: int) -> str:
    goal = COGNITIVE_LEVELS.get(level, COGNITIVE_LEVELS[1])["goal"]
    focus = ERROR_TYPES.get(error_types[0], {}).get("label", "this knowledge") if error_types else "this knowledge"
    return (
        f"After this session I must be able to apply {ku.subtopic or ku.topic} correctly at the level of "
        f"“{goal}”, with no {focus.lower()} error."
    )


# ---------------------------------------------------------------------------
# The NotebookLM prompt (the return path of the loop)
# ---------------------------------------------------------------------------

def build_gemini_prompt(
    store: Store,
    ku: KnowledgeUnit,
    error_types: list[str],
    gap_description: str,
    objective: str,
    dose: str,
    methods: list[str],
) -> str:
    source_title = store.source_titles().get(ku.source_id, ku.source_id or "the uploaded source")
    location = " · ".join(b for b in (ku.chapter, ku.section, ku.location) if b) or "not recorded — search the source"
    method_lines = "\n".join(f"   - {LEARNING_METHODS.get(m, m)}" for m in methods)

    return f"""LEARNING TARGET:
{ku.topic} — {ku.subtopic or ku.statement}

KNOWLEDGE GAP:
{gap_description}

ERROR TYPE:
{", ".join(error_types) or "unclassified"}

SOURCE:
{source_title}

SOURCE LOCATION:
{location}

LEARNING OBJECTIVE:
{objective}

STUDY DOSE:
{dose}

PREFERRED LEARNING METHODS:
{method_lines}

TASK:
I am studying only to close this specific knowledge gap.

Please:
1. Find the relevant part of the source.
2. Extract only the information needed to close this gap.
3. Explain how it relates to the knowledge unit above.
4. Point out the discriminating features and the important exceptions.
5. Finish with a few retrieval-practice questions on exactly this gap.
6. Do not introduce any information from outside the source.
"""


# ---------------------------------------------------------------------------
# Building the prescription
# ---------------------------------------------------------------------------

def build_prescription(store: Store, unit: UnitProfile) -> StudyPlan | None:
    ku = store.get_ku(unit.ku_id)
    if not ku:
        return None

    diagnoses = store.list_diagnoses(unit.ku_id, unresolved_only=True)
    error_types = list(dict.fromkeys(
        [d.error_type for d in diagnoses] or [h["error_type"] for h in unit.error_hypotheses][:2]
    ))
    target = review_target(store, unit.ku_id, error_types)
    if not target:
        return None

    # WHAT
    what = ku.statement
    if unit.signatures:
        what += f"  [{', '.join(unit.signatures)}]"

    # WHY
    why_bits = [
        f"{ERROR_TYPES[e]['label']}: {ERROR_TYPES[e]['definition']}"
        for e in error_types[:2] if e in ERROR_TYPES
    ]
    why_bits.append(
        f"Clinical importance {unit.importance}/5; "
        f"{unit.failures}/{unit.attempts} failures; knowledge-gap score {unit.gap_score:.1f}."
    )
    if ku.clinical_significance:
        why_bits.append(ku.clinical_significance)
    why = " | ".join(why_bits)

    # WHERE
    where = " · ".join(
        b for b in (target.source_title, target.chapter, target.section, target.location) if b
    )
    if target.why_relevant:
        where += f"\n→ {target.why_relevant}"

    # WHAT TO STUDY
    what_to_study = ku.thresholds or ku.exceptions or ku.algorithm or ku.statement
    if ku.common_mistakes:
        what_to_study += f"  (watch the classic pitfall: {ku.common_mistakes})"

    # HOW
    methods = methods_for(error_types)
    how = list(target.focus_points)
    how += [LEARNING_METHODS[m] for m in methods if m in LEARNING_METHODS]
    how.append("Close the source and restate the unit from memory in one sentence.")
    for ignore in target.ignore_for_now:
        how.append(f"Ignore for now: {ignore}")
    how = list(dict.fromkeys(how))[:8]

    # Next cognitive level (adaptive difficulty)
    level = max((ERROR_TO_LEVEL.get(e, 2) for e in error_types), default=2)
    shaky = [lvl for lvl, rate in sorted(unit.level_pass_rate.items()) if rate < 0.5]
    if shaky:
        level = shaky[0]
    if unit.failure_rate >= 0.6 or "KNOWLEDGE_GAP" in unit.signatures:
        level = 1

    dose = _dose(error_types, unit)
    objective = _objective(ku, error_types, level)
    gap_description = (
        f"{what} — failing {unit.failures} of {unit.attempts} attempts"
        + (f", {unit.distinct_failed_cards} different formulations" if unit.distinct_failed_cards > 1 else "")
        + (f"; signatures: {', '.join(unit.signatures)}" if unit.signatures else "")
    )

    return StudyPlan(
        ku_id=ku.id,
        what=what,
        where=where,
        why=why,
        how=how,
        what_to_study=what_to_study,
        how_much=dose,
        methods=methods,
        gemini_prompt=build_gemini_prompt(
            store, ku, error_types, gap_description, objective, dose, methods
        ),
        gap_score=unit.gap_score,
        next_level=level,
        error_types=error_types,
        priority=unit.gap_score or unit.priority,
    )


def prescribe(store: Store, profile: WeaknessProfile, limit: int = 10) -> list[StudyPlan]:
    """Create/refresh prescriptions for the highest knowledge-gap scores."""
    candidates = [u for u in profile.units if u.attempts and (u.is_weak or u.gap_score >= 5)]
    candidates.sort(key=lambda u: u.gap_score, reverse=True)

    plans: list[StudyPlan] = []
    for unit in candidates[:limit]:
        plan = build_prescription(store, unit)
        if plan:
            store.save_plan(plan)
            plans.append(plan)
    store.log_event("prescriptions", {"count": len(plans)})
    return plans


def to_markdown(store: Store, plan: StudyPlan) -> str:
    ku = store.get_ku(plan.ku_id)
    title = ku.label if ku else plan.ku_id
    lines = [
        f"### {title}",
        f"*Knowledge-gap score {plan.gap_score:.1f} · {', '.join(plan.error_types) or 'unclassified'}*",
        "",
        f"**1 · WHAT I don't know**  \n{plan.what}",
        "",
        f"**2 · WHY it matters**  \n{plan.why}",
        "",
        f"**3 · WHERE to fix it**  \n{plan.where}",
        "",
        f"**4 · WHAT to study**  \n{plan.what_to_study}",
        "",
        "**5 · HOW to study**",
        *[f"- {step}" for step in plan.how],
        "",
        f"**6 · HOW MUCH**  \n{plan.how_much}",
        "",
        f"*Reassessment will target cognitive level {plan.next_level}.*",
        "",
        "---",
        "",
        "**Prompt for Gemini NotebookLM**",
        "",
        "```",
        plan.gemini_prompt,
        "```",
    ]
    return "\n".join(lines)
