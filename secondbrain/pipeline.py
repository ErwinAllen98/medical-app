"""One-call orchestration of the closed loop + a demo seed.

``run_cycle`` executes the parts of the loop that do not need a human or an LLM:
pull performance data → profile → heuristic diagnosis → plans → mastery sweep.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import anki as anki_mod
from . import diagnostics, mastery, restudy
from .models import Card, KnowledgeUnit, Review, Source
from .store import Store


@dataclass
class CycleReport:
    pulled_reviews: int = 0
    profiled_units: int = 0
    weak_units: int = 0
    patterns: int = 0
    hypotheses: int = 0
    plans: int = 0
    promoted: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def run_cycle(store: Store, pull_from_anki: bool = True) -> CycleReport:
    report = CycleReport()

    if pull_from_anki:
        try:
            report.pulled_reviews = anki_mod.pull_reviews(store)
        except anki_mod.AnkiError as exc:
            report.notes.append(str(exc))

    profile = diagnostics.build_profile(store)
    report.profiled_units = len(profile.units)
    report.weak_units = len(profile.weak_units)
    report.patterns = len(profile.patterns)
    report.hypotheses = diagnostics.persist_hypotheses(store, profile)
    report.plans = len(restudy.generate_plans(store, profile))
    report.promoted = [r.label for r in mastery.sweep(store)]

    store.log_event("cycle", {
        "pulled": report.pulled_reviews, "weak": report.weak_units,
        "plans": report.plans, "promoted": len(report.promoted),
    })
    return report


LOOP_STEPS = [
    ("Sources", "Guidelines, textbooks, reviews, slides — the only allowed knowledge base."),
    ("NotebookLM", "Source-grounded extraction of knowledge units, MCQs and cards."),
    ("Validation", "Traceability check: no chapter/section/page → the item is rejected."),
    ("AnkiConnect", "Automatic transfer into the Anki collection — no copy-paste."),
    ("Anki + FSRS", "Daily study; scheduling, stability, difficulty, retrievability."),
    ("Performance data", "Review log pulled back into the hub."),
    ("Claude", "Longitudinal diagnosis: why the knowledge keeps failing."),
    ("Weakness profile", "Cumulative, cross-card patterns instead of isolated lapses."),
    ("Source localisation", "The exact chapter/section/table that repairs the gap."),
    ("Targeted re-study", "WHAT → WHERE → WHY → HOW, and what to ignore for now."),
    ("Adaptive questions", "New formulations at the weakest cognitive layer."),
    ("Mastery check", "Repeated, time-spread, multi-format, application-level success."),
    ("Notion", "Mastered knowledge + the weakness history that produced it."),
]


# ---------------------------------------------------------------------------
# Demo seed — lets the hub be explored before any real source is processed.
# ---------------------------------------------------------------------------

_DEMO = [
    {
        "topic": "Type 2 diabetes",
        "subtopic": "SGLT2 inhibitor initiation thresholds",
        "statement": "In T2D with CKD, an SGLT2 inhibitor is recommended when eGFR is ≥ 20 mL/min/1.73 m² and can be continued until dialysis or transplantation.",
        "clinical_significance": "Cardiorenal protection is independent of glycaemic effect; stopping too early loses the benefit.",
        "thresholds": "Initiate at eGFR ≥ 20; continue below 20 once started; albuminuria ≥ 200 mg/g strengthens the indication.",
        "exceptions": "Do not initiate in type 1 diabetes or recurrent DKA; hold during acute illness/surgery.",
        "algorithm": "",
        "common_mistakes": "Stopping the drug when eGFR falls below 30, or believing initiation requires eGFR ≥ 45.",
        "chapter": "Chapter 11 — CKD and Risk Management",
        "section": "Pharmacologic therapy in CKD",
        "location": "p. S231, Table 11.3",
        "why_relevant": "Table 11.3 lists the eGFR cut-offs for initiation and continuation.",
        "importance": 5,
        "cards": [
            ("What is the minimum eGFR for initiating an SGLT2 inhibitor in T2D with CKD?",
             "eGFR ≥ 20 mL/min/1.73 m²", 1, "THRESHOLD_ERROR"),
            ("An SGLT2 inhibitor was started at eGFR 34, which now falls to 22. What do you do?",
             "Continue it — once started, therapy is maintained until dialysis or transplantation.", 4, "MANAGEMENT_ERROR"),
            ("Why is an SGLT2 inhibitor still indicated when its glucose-lowering effect fades at low eGFR?",
             "Because the cardiorenal benefit is haemodynamic/tubuloglomerular, not glycaemic.", 2, "CONCEPT_ERROR"),
        ],
    },
    {
        "topic": "Type 2 diabetes",
        "subtopic": "GLP-1 RA vs SGLT2i selection",
        "statement": "In established ASCVD, both GLP-1 RA and SGLT2i reduce MACE; with heart failure or CKD predominance the SGLT2 inhibitor is preferred.",
        "clinical_significance": "Drug choice is driven by the dominant comorbidity, not by HbA1c alone.",
        "thresholds": "Independent of baseline HbA1c and metformin use.",
        "exceptions": "Prefer GLP-1 RA when weight loss dominates or eGFR is < 20.",
        "algorithm": "Assess ASCVD → assess HF/CKD → choose agent → then optimise HbA1c.",
        "common_mistakes": "Choosing on HbA1c instead of comorbidity; assuming the two classes are interchangeable.",
        "chapter": "Chapter 9 — Pharmacologic Approaches",
        "section": "Cardiorenal risk-based selection",
        "location": "p. S164, Figure 9.3",
        "why_relevant": "Figure 9.3 is the decision algorithm for comorbidity-driven selection.",
        "importance": 5,
        "cards": [
            ("In T2D with HFrEF, which glucose-lowering class is preferred?",
             "An SGLT2 inhibitor.", 3, "DISCRIMINATION_ERROR"),
            ("Does the comorbidity-driven choice depend on the baseline HbA1c?",
             "No — it is recommended independently of HbA1c and of metformin use.", 2, "CONCEPT_ERROR"),
        ],
    },
    {
        "topic": "Hypertension",
        "subtopic": "Hypertensive emergency BP lowering rate",
        "statement": "In hypertensive emergency without aortic dissection, reduce MAP by no more than 25% in the first hour, then to 160/100–110 over 2–6 hours.",
        "clinical_significance": "Faster reduction risks watershed cerebral and renal ischaemia.",
        "thresholds": "≤ 25% MAP in hour 1; 160/100–110 by 2–6 h; normal over 24–48 h.",
        "exceptions": "Aortic dissection: SBP < 120 within 20 minutes. Ischaemic stroke has its own thresholds.",
        "algorithm": "Confirm target-organ damage → IV agent → hour-1 goal → 2–6 h goal → 24–48 h goal.",
        "common_mistakes": "Applying the dissection target to every emergency.",
        "chapter": "Section 11 — Hypertensive Crises",
        "section": "Acute BP reduction targets",
        "location": "Table 24, p. 1290",
        "why_relevant": "Table 24 lists the hour-by-hour targets and the dissection exception.",
        "importance": 4,
        "cards": [
            ("Maximum MAP reduction in the first hour of a hypertensive emergency?",
             "25%", 1, "THRESHOLD_ERROR"),
            ("Which hypertensive emergency requires SBP < 120 within 20 minutes?",
             "Acute aortic dissection.", 3, "EXCEPTION_ERROR"),
            ("A patient with hypertensive encephalopathy at 240/130 — what is the next step?",
             "IV agent targeting ≤ 25% MAP reduction in the first hour, not normalisation.", 4, "MANAGEMENT_ERROR"),
        ],
    },
    {
        "topic": "Anticoagulation",
        "subtopic": "DOAC dose reduction criteria in AF",
        "statement": "Apixaban 5 mg BID is reduced to 2.5 mg BID when two of three are present: age ≥ 80, weight ≤ 60 kg, creatinine ≥ 1.5 mg/dL.",
        "clinical_significance": "Both over- and under-dosing increase events; the criteria are drug-specific.",
        "thresholds": "Age ≥ 80 y; weight ≤ 60 kg; creatinine ≥ 1.5 mg/dL — two of three.",
        "exceptions": "Rivaroxaban and dabigatran use different, non-interchangeable criteria.",
        "algorithm": "",
        "common_mistakes": "Applying apixaban's criteria to rivaroxaban, or reducing on a single criterion.",
        "chapter": "Chapter 6 — Oral Anticoagulants",
        "section": "Dosing in special populations",
        "location": "Table 6.2",
        "why_relevant": "Table 6.2 lists each DOAC's reduction criteria side by side.",
        "importance": 5,
        "cards": [
            ("How many of the three apixaban dose-reduction criteria must be met?",
             "Two of three.", 1, "THRESHOLD_ERROR"),
            ("An 82-year-old, 72 kg, creatinine 1.1 — which apixaban dose?",
             "5 mg BID: only one criterion (age) is met.", 4, "THRESHOLD_ERROR"),
            ("Do rivaroxaban and apixaban share dose-reduction criteria?",
             "No — rivaroxaban is reduced on creatinine clearance alone.", 3, "DISCRIMINATION_ERROR"),
        ],
    },
    {
        "topic": "Thyroid",
        "subtopic": "Subclinical hypothyroidism treatment threshold",
        "statement": "Treat subclinical hypothyroidism when TSH is > 10 mIU/L; between 4.5 and 10 treat only with symptoms, positive TPO antibodies, pregnancy or cardiovascular risk.",
        "clinical_significance": "Avoids over-treatment while preventing progression in the at-risk group.",
        "thresholds": "TSH > 10 → treat; 4.5–10 → conditional.",
        "exceptions": "Pregnancy uses trimester-specific ranges and a lower treatment threshold.",
        "algorithm": "",
        "common_mistakes": "Treating every TSH above the reference range.",
        "chapter": "Thyroid disorders",
        "section": "Subclinical disease",
        "location": "p. 412",
        "why_relevant": "This page defines the two TSH bands and the conditional criteria.",
        "importance": 3,
        "cards": [
            ("Above which TSH is treatment of subclinical hypothyroidism recommended for everyone?",
             "TSH > 10 mIU/L", 1, "THRESHOLD_ERROR"),
            ("TSH 6.8, asymptomatic, TPO negative, not pregnant — treat?",
             "No — observe and recheck; treatment is conditional in the 4.5–10 band.", 4, "INDICATION_ERROR"),
        ],
    },
]

# (failure profile per subtopic: probability of failing, per cognitive level)
_DEMO_DIFFICULTY = {
    "SGLT2 inhibitor initiation thresholds": {1: 0.55, 2: 0.35, 3: 0.6, 4: 0.75},
    "GLP-1 RA vs SGLT2i selection": {1: 0.2, 2: 0.15, 3: 0.55, 4: 0.5},
    "Hypertensive emergency BP lowering rate": {1: 0.15, 2: 0.1, 3: 0.45, 4: 0.5},
    "DOAC dose reduction criteria in AF": {1: 0.1, 2: 0.1, 3: 0.2, 4: 0.15},
    "Subclinical hypothyroidism treatment threshold": {1: 0.05, 2: 0.05, 3: 0.1, 4: 0.1},
}


def seed_demo(store: Store, with_reviews: bool = True, seed: int = 7) -> dict:
    """Populate a realistic demo collection so the loop can be seen working."""
    rng = random.Random(seed)
    source = store.find_source_by_title("ADA Standards of Care 2025 (demo)") or Source(
        title="ADA Standards of Care 2025 (demo)",
        kind="guideline",
        citation="Demo source bundled with the hub — replace with your own NotebookLM sources.",
    )
    store.upsert_source(source)

    created_units, created_cards = 0, 0
    ku_ids: list[str] = []

    for entry in _DEMO:
        existing = next(
            (k for k in store.list_kus() if k.subtopic == entry["subtopic"]), None
        )
        if existing:
            ku_ids.append(existing.id)
            continue
        ku = KnowledgeUnit(
            topic=entry["topic"], subtopic=entry["subtopic"], statement=entry["statement"],
            clinical_significance=entry["clinical_significance"], thresholds=entry["thresholds"],
            exceptions=entry["exceptions"], algorithm=entry["algorithm"],
            common_mistakes=entry["common_mistakes"], source_id=source.id,
            chapter=entry["chapter"], section=entry["section"], location=entry["location"],
            why_relevant=entry["why_relevant"], importance=entry["importance"],
        )
        store.upsert_ku(ku)
        ku_ids.append(ku.id)
        created_units += 1

        from .extraction import _tags_for

        for question, answer, level, error_target in entry["cards"]:
            card = Card(
                ku_id=ku.id, question=question, answer=answer, card_type="BASIC",
                explanation="", cognitive_level=level, error_target=error_target,
                tags=_tags_for(ku, level, error_target), generation=1,
            )
            store.upsert_card(card)
            created_cards += 1

    # Link the two diabetes units so interference can be detected.
    diabetes = [store.get_ku(i) for i in ku_ids]
    diabetes = [k for k in diabetes if k and k.topic == "Type 2 diabetes"]
    if len(diabetes) >= 2:
        store.link_kus(diabetes[0].id, [diabetes[1].id])
        store.link_kus(diabetes[1].id, [diabetes[0].id])

    added_reviews = 0
    if with_reviews and store.review_count() == 0:
        added_reviews = _simulate_reviews(store, rng)

    return {"units": created_units, "cards": created_cards, "reviews": added_reviews,
            "source_id": source.id}


def _simulate_reviews(store: Store, rng: random.Random, days: int = 60) -> int:
    """Generate a plausible 60-day Anki/FSRS history for the demo cards."""
    now = datetime.now(timezone.utc)
    reviews: list[Review] = []

    for card in store.list_cards():
        ku = store.get_ku(card.ku_id)
        if not ku:
            continue
        profile = _DEMO_DIFFICULTY.get(ku.subtopic, {})
        p_fail = profile.get(card.cognitive_level, 0.2)

        stability = 1.5
        when = now - timedelta(days=days - rng.randint(0, 6))
        n_reviews = rng.randint(4, 8)
        for i in range(n_reviews):
            # Struggling cards slowly improve; easy cards stay easy.
            effective = max(0.03, p_fail * (1 - 0.08 * i))
            failed = rng.random() < effective
            rating = 1 if failed else rng.choice([3, 3, 3, 4] if effective < 0.2 else [2, 3, 3])
            stability = max(0.8, stability * (0.45 if failed else 2.1 + 0.3 * rng.random()))
            retrievability = round(max(0.55, min(0.98, 0.95 - effective)), 3)

            reviews.append(
                Review(
                    card_id=card.id,
                    anki_note_id=None,
                    reviewed_at=when.isoformat(timespec="seconds"),
                    rating=rating,
                    state="review" if i else "learning",
                    elapsed_days=round(stability / 2, 1),
                    scheduled_days=round(stability, 1),
                    duration_ms=int(rng.uniform(4, 28) * 1000),
                    stability=round(stability, 2),
                    difficulty=round(min(9.5, 3 + 6 * p_fail), 2),
                    retrievability=retrievability,
                    origin="simulated",
                )
            )
            step = max(1, int(stability))
            when = when + timedelta(days=min(step, 14), hours=rng.randint(0, 8))
            if when > now:
                break

    return store.add_reviews(reviews)
