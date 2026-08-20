"""Layers 7-8: source localisation and the targeted re-study plan.

Works with or without Claude: if no LLM output is available, a deterministic
plan is generated from the weakness profile + the source metadata that every
knowledge unit already carries.
"""

from __future__ import annotations

from .diagnostics import UnitProfile, WeaknessProfile
from .models import ReviewTarget, StudyPlan
from .store import Store
from .taxonomy import ERROR_TO_LEVEL, ERROR_TYPES


def review_target(store: Store, ku_id: str, error_types: list[str] | None = None) -> ReviewTarget | None:
    """WHERE the fix lives — never 'review the chapter', always a precise anchor."""
    ku = store.get_ku(ku_id)
    if not ku:
        return None
    source_title = store.source_titles().get(ku.source_id, ku.source_id or "unknown source")
    errors = error_types or [d.error_type for d in store.list_diagnoses(ku_id, unresolved_only=True)]

    focus: list[str] = []
    if "THRESHOLD_ERROR" in errors and ku.thresholds:
        focus.append(f"The exact numbers: {ku.thresholds}")
    if "EXCEPTION_ERROR" in errors and ku.exceptions:
        focus.append(f"The exception list: {ku.exceptions}")
    if "SEQUENCE_ERROR" in errors and ku.algorithm:
        focus.append(f"The order of steps: {ku.algorithm}")
    if "DISCRIMINATION_ERROR" in errors:
        focus.append("The contrast with the neighbouring entity — build an A-vs-B table while reading.")
    if "CONCEPT_ERROR" in errors:
        focus.append("The mechanism paragraph: be able to explain the 'why' out loud before moving on.")
    for err in errors:
        info = ERROR_TYPES.get(err)
        if info and info["remedy"] not in focus:
            focus.append(info["remedy"])
    if ku.common_mistakes:
        focus.append(f"The classic pitfall: {ku.common_mistakes}")
    if not focus:
        focus.append(f"Re-anchor the core statement: {ku.statement}")

    ignore = ["Everything in this chapter that is not about " + (ku.subtopic or ku.topic)]

    return ReviewTarget(
        ku_id=ku.id,
        source_title=source_title,
        chapter=ku.chapter,
        section=ku.section,
        location=ku.location,
        knowledge_unit=ku.statement,
        why_relevant=ku.why_relevant
        or f"This is where {source_title} defines {ku.subtopic or ku.topic}.",
        focus_points=focus[:6],
        ignore_for_now=ignore,
    )


def build_plan(store: Store, unit: UnitProfile) -> StudyPlan | None:
    """WHAT → WHERE → WHY → HOW for one weak knowledge unit."""
    ku = store.get_ku(unit.ku_id)
    if not ku:
        return None

    diagnoses = store.list_diagnoses(unit.ku_id, unresolved_only=True)
    errors = [d.error_type for d in diagnoses] or [
        h["error_type"] for h in unit.error_hypotheses
    ][:2]
    errors = list(dict.fromkeys(errors))
    target = review_target(store, unit.ku_id, errors)
    if not target:
        return None

    where = " · ".join(
        b for b in (target.source_title, target.chapter, target.section, target.location) if b
    )

    what = ku.statement
    if unit.signatures:
        what += f"  [{', '.join(unit.signatures)}]"

    why_bits = []
    for err in errors[:3]:
        info = ERROR_TYPES.get(err)
        if info:
            why_bits.append(f"{info['label']}: {info['definition']}")
    why_bits.extend(unit.evidence[:3])
    why = " | ".join(why_bits) or "Performance is unstable on this unit."

    how = list(target.focus_points)
    how.append(f"Then close the source and restate the unit from memory in one sentence.")
    for ig in target.ignore_for_now:
        how.append(f"Ignore for now: {ig}")

    # Adaptive difficulty: attack the weakest layer that is still shaky, and only
    # climb towards the error's natural level once the lower layers hold.
    next_level = max((ERROR_TO_LEVEL.get(e, 2) for e in errors), default=2)
    shaky = [lvl for lvl, rate in sorted(unit.level_pass_rate.items()) if rate < 0.5]
    if shaky:
        next_level = shaky[0]
    if unit.failure_rate >= 0.6 or "KNOWLEDGE_GAP" in unit.signatures:
        next_level = 1  # collapse back to source + basic recall

    return StudyPlan(
        ku_id=ku.id,
        what=what,
        where=where + (f"\n→ {target.why_relevant}" if target.why_relevant else ""),
        why=why,
        how=how,
        next_level=next_level,
        error_types=errors,
        priority=unit.priority,
    )


def generate_plans(store: Store, profile: WeaknessProfile, limit: int = 10) -> list[StudyPlan]:
    """Create/refresh study plans for the weakest units."""
    plans: list[StudyPlan] = []
    for unit in sorted(profile.weak_units, key=lambda u: u.priority, reverse=True)[:limit]:
        plan = build_plan(store, unit)
        if plan:
            store.save_plan(plan)
            store.set_ku_status(unit.ku_id, "RELEARNING")
            plans.append(plan)
    store.log_event("study_plans", {"count": len(plans)})
    return plans


def plan_to_markdown(store: Store, plan: StudyPlan) -> str:
    ku = store.get_ku(plan.ku_id)
    title = ku.label if ku else plan.ku_id
    lines = [
        f"### {title}",
        "",
        f"**WHAT you do not know**  \n{plan.what}",
        "",
        f"**WHERE to fix it**  \n{plan.where}",
        "",
        f"**WHY it keeps failing**  \n{plan.why}",
        "",
        "**HOW to re-read**",
    ]
    lines += [f"- {step}" for step in plan.how]
    lines += ["", f"*Next questions will target cognitive level {plan.next_level}.*"]
    return "\n".join(lines)
