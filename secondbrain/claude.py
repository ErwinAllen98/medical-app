"""Layer 5: Claude as the learning-diagnostic engine.

Builds a longitudinal performance dossier, asks Claude *why* the doctor keeps
failing, and parses the answer back into diagnoses, review targets and plans.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .diagnostics import WeaknessProfile
from .llm import extract_json
from .models import Diagnosis, StudyPlan, now_iso
from .store import Store
from .taxonomy import COGNITIVE_LEVELS, ERROR_TYPES, LEARNING_METHODS, methods_for

RESPONSE_SCHEMA = {
    "diagnoses": [
        {
            "ku_id": "string — copy from the dossier",
            "error_types": ["one or more keys from the taxonomy, most likely first"],
            "confidence": "0.0-1.0",
            "why": "string — the mechanism of the failure, not a restatement of the failure",
            "interference_with": ["ku_id or concept name that is being confused with this one"],
            "review_target": {
                "chapter": "string — from the dossier metadata",
                "section": "string",
                "location": "string — page/table/figure",
                "what_to_read": "string — the exact paragraph/table/algorithm to reread",
                "why_this_section": "string",
            },
            "learning_prescription": {
                "what": "string — what exactly is not known",
                "why": "string — why the gap exists and why it matters clinically",
                "what_to_study": "string — the concept/values to relearn, nothing more",
                "how": ["3-6 concrete instructions for the study session"],
                "how_much": "string — the minimum dose that closes this gap (e.g. 'one table, 6 minutes')",
                "methods": ["READING | CONCEPT_EXPLANATION | COMPARISON | CLINICAL_CASE | MCQ | CLOZE | RETRIEVAL_PRACTICE | SPACED_REPETITION"],
                "ignore_for_now": ["sections that are a distraction right now"],
                "next_level": "integer 1-5 — the cognitive level the reassessment should target",
                "learning_objective": "string — what I must be able to do after studying",
            },
            "gemini_notebook_prompt": "string — a ready-to-paste NotebookLM prompt using the LEARNING TARGET / KNOWLEDGE GAP / ERROR TYPE / SOURCE / SOURCE LOCATION / LEARNING OBJECTIVE / TASK structure",
        }
    ],
    "patterns": [
        {
            "topic": "string",
            "pattern": "string — e.g. 'you repeatedly fail SGLT2i initiation thresholds'",
            "ku_ids": ["..."],
            "dominant_error": "taxonomy key",
            "clinical_risk": "string — what could go wrong with a patient because of this gap",
        }
    ],
    "priority_order": ["ku_id, most urgent first"],
    "anki_update_plan": {
        "suspend": [{"ku_id": "...", "reason": "leech / superseded"}],
        "retire": [{"ku_id": "...", "reason": "ambiguous or badly written card"}],
        "new_cards_needed": [{"ku_id": "...", "what_to_test": "...", "card_type": "BASIC | CLOZE | MCQ"}],
        "tags": [{"ku_id": "...", "add": ["..."], "remove": ["..."]}],
    },
    "mastery_status": [{"ku_id": "...", "status": "UNSEEN | LEARNING | WEAK | RELEARNING | STABLE | MASTERED | ARCHIVED"}],
}


@dataclass
class ClaudeDiagnosis:
    diagnoses: list[dict] = field(default_factory=list)
    patterns: list[dict] = field(default_factory=list)
    priority_order: list[str] = field(default_factory=list)
    anki_update_plan: dict = field(default_factory=dict)
    mastery_status: list[dict] = field(default_factory=list)
    raw: str = ""


def build_dossier(store: Store, profile: WeaknessProfile, limit: int = 15) -> dict:
    """Longitudinal, machine-readable performance record for the weakest units."""
    titles = store.source_titles()
    units = [u for u in profile.top(limit) if u.attempts]
    dossier_units = []

    for u in units:
        ku = store.get_ku(u.ku_id)
        if not ku:
            continue
        cards = {c.id: c for c in store.list_cards(ku.id, include_retired=True)}
        history = []
        for rv in store.reviews_for_ku(ku.id):
            card = cards.get(rv.card_id)
            history.append(
                {
                    "date": rv.reviewed_at,
                    "rating": rv.rating,
                    "outcome": "FAIL" if rv.failed else "PASS",
                    "level": card.cognitive_level if card else None,
                    "probes": card.error_target if card else None,
                    "question": (card.question[:160] if card else ""),
                    "seconds": round((rv.duration_ms or 0) / 1000.0, 1),
                    "stability_days": rv.stability,
                    "retrievability": rv.retrievability,
                }
            )

        dossier_units.append(
            {
                "ku_id": ku.id,
                "topic": ku.topic,
                "subtopic": ku.subtopic,
                "knowledge": ku.statement,
                "thresholds": ku.thresholds,
                "exceptions": ku.exceptions,
                "algorithm": ku.algorithm,
                "common_mistakes": ku.common_mistakes,
                "clinical_importance": ku.importance,
                "source": {
                    "title": titles.get(ku.source_id, ku.source_id),
                    "chapter": ku.chapter,
                    "section": ku.section,
                    "location": ku.location,
                },
                "metrics": {
                    "attempts": u.attempts,
                    "failures": u.failures,
                    "failure_rate": u.failure_rate,
                    "repeated_failure_streak": u.repeated_failure_count,
                    "lapses_after_success": u.lapses_after_success,
                    "distinct_failed_formulations": u.distinct_failed_cards,
                    "pass_rate_by_level": u.level_pass_rate,
                    "days_since_last_review": u.last_reviewed_days,
                    "mean_stability_days": u.mean_stability,
                    "min_retrievability": u.min_retrievability,
                    "mean_answer_seconds": u.mean_answer_seconds,
                    "severity": u.severity,
                },
                "detected_signatures": u.signatures,
                "heuristic_hypotheses": u.error_hypotheses,
                "review_history": history,
                "neighbours": [
                    {"ku_id": n.ku_id, "label": n.label}
                    for n in profile.units
                    if n.topic == ku.topic and n.ku_id != ku.id
                ][:6],
            }
        )

    return {
        "generated_at": profile.generated_at,
        "topic_patterns": [p.to_dict() for p in profile.patterns],
        "units": dossier_units,
    }


def build_diagnostic_prompt(dossier: dict) -> str:
    taxonomy = "\n".join(
        f"  {k}: {v['definition']}" for k, v in ERROR_TYPES.items()
    )
    levels = "\n".join(f"  {k}: {v['label']} — {v['goal']}" for k, v in COGNITIVE_LEVELS.items())

    return f"""You are the learning-diagnostic engine of a physician's medical Second Brain.

You are NOT here to say "you got this card wrong". FSRS already knows that.
You are here to explain WHY the same knowledge keeps failing, and to point at the
exact place in the original source where the gap can be repaired.

ERROR TAXONOMY — classify every weakness with these keys:
{taxonomy}

COGNITIVE LEVELS — used to decide what the next questions should test:
{levels}

ALSO DETECT (when the data supports it):
repeated failures, recurrent concepts across different cards, confusion between
similar diseases/drugs, threshold confusion, guideline-algorithm errors, outright
knowledge gaps, false confidence (fast "Easy" ratings followed by lapses),
interference between neighbouring units, information memorised but not understood
(high pass rate at levels 1-2, failure at 4-5), and information understood but not
retrievable (the reverse).

RULES
1. Reason across cards and across time, not card by card.
2. Ground every review target in the source metadata supplied in the dossier.
   Never invent a page number that is not in the dossier; if the location is
   missing, say which section to search instead.
3. Targeted re-reading only. Never say "review SGLT2 inhibitors" — say which
   table, algorithm or paragraph, and what to look for inside it.
4. Rank by clinical risk × severity, not by number of failed cards.
5. Prescribe the MINIMUM NECESSARY LEARNING: never send me back to a whole chapter.
   Say exactly what to read, by which method, and how long it should take.
6. Write the NotebookLM prompt yourself, in this exact shape, so I can paste it
   straight into the notebook that holds the source:

     LEARNING TARGET: …
     KNOWLEDGE GAP: …
     ERROR TYPE: …
     SOURCE: …
     SOURCE LOCATION: …
     LEARNING OBJECTIVE: …
     TASK: I am studying only to close this gap. Please (1) find the relevant part of
     the source, (2) extract only what is needed, (3) relate it to the knowledge unit,
     (4) point out discriminating features and exceptions, (5) end with retrieval-practice
     questions, (6) add nothing from outside the source.

You must return all five deliverables: the knowledge-gap report (diagnoses), the
learning prescription, the NotebookLM prompt, the Anki update plan, and the mastery status.

PERFORMANCE DOSSIER
{json.dumps(dossier, ensure_ascii=False, indent=2, default=str)}

OUTPUT
Return STRICT JSON ONLY, matching this schema:
{json.dumps(RESPONSE_SCHEMA, ensure_ascii=False, indent=2)}
"""


def parse_diagnosis(raw: str | dict) -> ClaudeDiagnosis:
    data = raw if isinstance(raw, dict) else extract_json(raw)
    return ClaudeDiagnosis(
        diagnoses=data.get("diagnoses") or [],
        patterns=data.get("patterns") or [],
        priority_order=data.get("priority_order") or [],
        anki_update_plan=data.get("anki_update_plan") or {},
        mastery_status=data.get("mastery_status") or [],
        raw=raw if isinstance(raw, str) else json.dumps(data, ensure_ascii=False),
    )


def apply_diagnosis(store: Store, result: ClaudeDiagnosis, profile: WeaknessProfile | None = None) -> dict:
    """Persist Claude's diagnoses and the study plans that come with them."""
    saved_diag = saved_plans = 0
    order = {ku_id: i for i, ku_id in enumerate(result.priority_order)}

    for item in result.diagnoses:
        ku_id = item.get("ku_id")
        if not ku_id or not store.get_ku(ku_id):
            continue
        errors = item.get("error_types") or ([item["error_type"]] if item.get("error_type") else [])
        errors = [e for e in (str(x).strip().upper() for x in errors) if e in ERROR_TYPES]
        if not errors:
            continue

        try:
            confidence = float(item.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        why = str(item.get("why") or "").strip()
        interference = item.get("interference_with") or []
        if interference:
            why += f" | interference with: {', '.join(str(i) for i in interference)}"

        for err in errors:
            store.add_diagnosis(
                Diagnosis(ku_id=ku_id, error_type=err, confidence=confidence,
                          evidence=why, engine="claude")
            )
            saved_diag += 1

        target = item.get("review_target") or {}
        plan_data = item.get("learning_prescription") or item.get("study_plan") or {}
        where_bits = [b for b in (target.get("chapter"), target.get("section"), target.get("location")) if b]
        ku = store.get_ku(ku_id)
        source_title = store.source_titles().get(ku.source_id, "") if ku else ""
        where = " · ".join([source_title] + where_bits) if source_title else " · ".join(where_bits)
        if target.get("what_to_read"):
            where += f"\n→ {target['what_to_read']}"

        how = [str(h) for h in (plan_data.get("how") or []) if str(h).strip()]
        for ignore in plan_data.get("ignore_for_now") or []:
            how.append(f"Ignore for now: {ignore}")

        try:
            next_level = max(1, min(5, int(plan_data.get("next_level") or 2)))
        except (TypeError, ValueError):
            next_level = 2

        unit_priority = 0.0
        if profile:
            up = profile.by_id(ku_id)
            unit_priority = up.priority if up else 0.0
        priority = unit_priority + (100 - order.get(ku_id, 99))

        from .prescription import build_gemini_prompt

        methods = [str(m).strip().upper() for m in (plan_data.get("methods") or [])]
        methods = [m for m in methods if m in LEARNING_METHODS] or methods_for(errors)
        how_much = str(plan_data.get("how_much") or "").strip() or "Only the identified section."
        objective = str(plan_data.get("learning_objective") or "").strip()
        gemini_prompt = str(item.get("gemini_notebook_prompt") or "").strip()
        if not gemini_prompt and ku:
            gemini_prompt = build_gemini_prompt(
                store, ku, errors,
                str(plan_data.get("what") or why).strip(),
                objective or f"Apply {ku.subtopic or ku.topic} without a {errors[0].lower()}.",
                how_much, methods,
            )

        gap = profile.by_id(ku_id) if profile else None
        store.save_plan(
            StudyPlan(
                ku_id=ku_id,
                what=str(plan_data.get("what") or item.get("why") or "").strip(),
                where=where or "source location not specified",
                why=str(plan_data.get("why") or why).strip(),
                how=how,
                what_to_study=str(plan_data.get("what_to_study") or "").strip(),
                how_much=how_much,
                methods=methods,
                gemini_prompt=gemini_prompt,
                gap_score=gap.gap_score if gap else 0.0,
                next_level=next_level,
                error_types=errors,
                priority=round(priority, 3),
            )
        )
        saved_plans += 1
        store.set_ku_status(ku_id, "RELEARNING")

    store.log_event(
        "claude_diagnosis",
        {"diagnoses": saved_diag, "plans": saved_plans, "patterns": len(result.patterns),
         "at": now_iso()},
    )
    return {"diagnoses": saved_diag, "plans": saved_plans, "patterns": len(result.patterns)}
