"""Knowledge-unit lifecycle.

    UNSEEN → LEARNING → WEAK → RELEARNING → STABLE → MASTERED → ARCHIVED

Archiving is never permanent: if performance on an archived or mastered unit
declines, it is REACTIVATED back into RELEARNING and re-enters the loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import HIGH_FAILURE_RATE
from .diagnostics import UnitProfile, WeaknessProfile, build_profile
from .mastery import MasteryReport, evaluate
from .store import Store
from .taxonomy import REACTIVATION_STATUS

WEAK_GAP_SCORE = 8.0        # a gap score above this is a real weakness
STABLE_MASTERY_SCORE = 0.66  # most mastery criteria already satisfied


@dataclass
class Transition:
    ku_id: str
    label: str
    old: str
    new: str
    reason: str


def _recent_lapse(store: Store, ku_id: str, window: int = 3) -> bool:
    reviews = store.reviews_for_ku(ku_id)
    return any(r.failed for r in reviews[-window:])


def next_status(
    store: Store,
    ku_id: str,
    current: str,
    unit: UnitProfile | None,
    report: MasteryReport | None,
) -> tuple[str, str]:
    """Return (status, reason) for one knowledge unit."""
    has_open_plan = any(p.ku_id == ku_id for p in store.list_plans("OPEN"))

    # Nothing has ever been tested.
    if not unit or not unit.attempts:
        if current in {"MASTERED", "ARCHIVED"}:
            return current, "no new data"
        return "UNSEEN", "never reviewed"

    declining = _recent_lapse(store, ku_id)

    # Reactivation beats everything: archived knowledge that starts failing again.
    if current in {"MASTERED", "ARCHIVED"} and declining:
        return REACTIVATION_STATUS, "performance decline after mastery — reactivated"

    if report and report.mastered:
        return "MASTERED", "all mastery criteria satisfied"

    if has_open_plan:
        return "RELEARNING", "a learning prescription is open"

    if unit.gap_score >= WEAK_GAP_SCORE or unit.failure_rate >= HIGH_FAILURE_RATE or unit.signatures:
        return "WEAK", f"knowledge gap score {unit.gap_score:.1f}"

    if report and report.score >= STABLE_MASTERY_SCORE and not declining:
        return "STABLE", f"reliable lately ({report.score:.0%} of mastery criteria)"

    return "LEARNING", "being tested, not settled yet"


def sync_statuses(store: Store, profile: WeaknessProfile | None = None) -> list[Transition]:
    """Recompute the lifecycle status of every knowledge unit."""
    profile = profile or build_profile(store)
    transitions: list[Transition] = []

    for ku in store.list_kus():
        unit = profile.by_id(ku.id)
        report = evaluate(store, ku.id)
        status, reason = next_status(store, ku.id, ku.status, unit, report)
        if status != ku.status and store.set_ku_status(ku.id, status):
            transitions.append(
                Transition(ku_id=ku.id, label=ku.label, old=ku.status, new=status, reason=reason)
            )
            if status == REACTIVATION_STATUS and ku.status in {"MASTERED", "ARCHIVED"}:
                store.log_event("reactivated", {"ku_id": ku.id, "label": ku.label, "reason": reason})

    return transitions


def archive(store: Store, ku_id: str) -> bool:
    """Mark a mastered unit as archived (it stays in Anki for long-term review)."""
    ku = store.get_ku(ku_id)
    if not ku or ku.status not in {"MASTERED", "ARCHIVED"}:
        return False
    return store.set_ku_status(ku_id, "ARCHIVED")


def counts(store: Store) -> dict[str, int]:
    from .taxonomy import STATUS_FLOW

    tally = {status: 0 for status in STATUS_FLOW}
    for ku in store.list_kus():
        tally[ku.status] = tally.get(ku.status, 0) + 1
    return tally
