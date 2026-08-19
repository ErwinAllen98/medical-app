"""Layer 11: the mastery criterion.

One correct answer is not mastery. A knowledge unit is MASTERED only when it
survives time, different formulations and clinical application, with no live
error pattern left.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import (
    MASTERY_CLEAN_STREAK,
    MASTERY_MIN_APPLICATION_LEVEL,
    MASTERY_MIN_FORMULATIONS,
    MASTERY_MIN_SPAN_DAYS,
    MASTERY_MIN_STABILITY_DAYS,
    MASTERY_MIN_SUCCESSES,
)
from .store import Store


def _parse(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Criterion:
    key: str
    label: str
    passed: bool
    detail: str


@dataclass
class MasteryReport:
    ku_id: str
    label: str
    mastered: bool
    criteria: list[Criterion] = field(default_factory=list)
    score: float = 0.0

    @property
    def missing(self) -> list[Criterion]:
        return [c for c in self.criteria if not c.passed]

    def to_dict(self) -> dict:
        return {
            "ku_id": self.ku_id,
            "label": self.label,
            "mastered": self.mastered,
            "score": self.score,
            "criteria": [c.__dict__ for c in self.criteria],
        }


def evaluate(store: Store, ku_id: str) -> MasteryReport | None:
    ku = store.get_ku(ku_id)
    if not ku:
        return None

    cards = {c.id: c for c in store.list_cards(ku_id, include_retired=True)}
    reviews = store.reviews_for_ku(ku_id)
    successes = [r for r in reviews if not r.failed]
    criteria: list[Criterion] = []

    # 1. Repeatedly recalled correctly
    criteria.append(
        Criterion(
            "repeated_success",
            f"At least {MASTERY_MIN_SUCCESSES} correct retrievals",
            len(successes) >= MASTERY_MIN_SUCCESSES,
            f"{len(successes)} correct so far",
        )
    )

    # 2. Survives spaced repetition (spread over time + FSRS stability)
    span_days = 0.0
    if len(successes) >= 2:
        span_days = (_parse(successes[-1].reviewed_at) - _parse(successes[0].reviewed_at)).days
    stability = max((r.stability or 0.0) for r in reviews) if reviews else 0.0
    survives = span_days >= MASTERY_MIN_SPAN_DAYS or stability >= MASTERY_MIN_STABILITY_DAYS
    criteria.append(
        Criterion(
            "survives_time",
            f"Correct across ≥ {MASTERY_MIN_SPAN_DAYS} days (or FSRS stability ≥ {MASTERY_MIN_STABILITY_DAYS:.0f}d)",
            survives,
            f"span {span_days:.0f}d, best stability {stability:.1f}d",
        )
    )

    # 3. Different question formulations
    formulations = {r.card_id for r in successes}
    criteria.append(
        Criterion(
            "multiple_formulations",
            f"Correct on ≥ {MASTERY_MIN_FORMULATIONS} different formulations",
            len(formulations) >= MASTERY_MIN_FORMULATIONS,
            f"{len(formulations)} distinct items answered correctly",
        )
    )

    # 4. Correct in a clinical / application scenario
    applied = [
        r for r in successes
        if cards.get(r.card_id) and cards[r.card_id].cognitive_level >= MASTERY_MIN_APPLICATION_LEVEL
    ]
    criteria.append(
        Criterion(
            "clinical_application",
            f"Correct at cognitive level ≥ {MASTERY_MIN_APPLICATION_LEVEL}",
            bool(applied),
            f"{len(applied)} correct application-level answers",
        )
    )

    # 5. No persistent error pattern (recent lapse-free streak)
    tail = reviews[-MASTERY_CLEAN_STREAK:]
    clean = len(tail) >= MASTERY_CLEAN_STREAK and all(not r.failed for r in tail)
    criteria.append(
        Criterion(
            "clean_streak",
            f"Last {MASTERY_CLEAN_STREAK} reviews lapse-free",
            clean,
            "clean" if clean else "a recent lapse is still on record",
        )
    )

    # 6. No unresolved diagnosis / confusion left
    open_diagnoses = store.list_diagnoses(ku_id, unresolved_only=True)
    criteria.append(
        Criterion(
            "no_open_diagnosis",
            "No unresolved error diagnosis",
            not open_diagnoses,
            "clear" if not open_diagnoses else
            f"open: {', '.join(sorted({d.error_type for d in open_diagnoses}))}",
        )
    )

    passed = sum(1 for c in criteria if c.passed)
    return MasteryReport(
        ku_id=ku_id,
        label=ku.label,
        mastered=passed == len(criteria),
        criteria=criteria,
        score=round(passed / len(criteria), 2),
    )


def evaluate_all(store: Store) -> list[MasteryReport]:
    reports = []
    for ku in store.list_kus():
        rep = evaluate(store, ku.id)
        if rep:
            reports.append(rep)
    return sorted(reports, key=lambda r: r.score, reverse=True)


def promote(store: Store, ku_id: str) -> MasteryReport | None:
    """Mark a unit MASTERED if — and only if — every criterion is satisfied."""
    report = evaluate(store, ku_id)
    if not report:
        return None
    if report.mastered:
        store.resolve_diagnoses(ku_id)
        store.set_ku_status(ku_id, "MASTERED")
        store.log_event("mastered", {"ku_id": ku_id, "label": report.label})
    return report


def sweep(store: Store) -> list[MasteryReport]:
    """Promote everything that now qualifies; demote nothing silently."""
    promoted = []
    for ku in store.list_kus():
        if ku.status == "MASTERED":
            continue
        report = promote(store, ku.id)
        if report and report.mastered:
            promoted.append(report)
    return promoted
