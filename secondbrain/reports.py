"""Periodic analysis (daily / weekly / monthly / yearly) and the full output bundle.

Every analysis run produces the five deliverables the system is defined by:

    A. Knowledge Gap Report
    B. Learning Prescription
    C. Gemini NotebookLM prompt
    D. Anki Update Plan
    E. Mastery Status
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import lifecycle
from .diagnostics import (
    UnitProfile,
    WeaknessProfile,
    build_profile,
    persist_hypotheses as _persist_hypotheses,
)
from .mastery import evaluate_all
from .models import StudyPlan
from .prescription import prescribe, to_markdown
from .store import Store
from .taxonomy import STATUS_FLOW

WINDOWS = {
    "daily": (1, "New errors, fresh lapses, urgent gaps, critical cards."),
    "weekly": (7, "Learning trend, recurring weaknesses, high-risk topics, prescriptions."),
    "monthly": (30, "Topic comparison, mastery trend, chronic weaknesses."),
    "yearly": (365, "Whole-system review: knowledge debt, mastered topics, re-learning needs."),
}


def _parse(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class WindowReport:
    scale: str
    goal: str
    days: int
    reviews: int = 0
    lapses: int = 0
    lapse_rate: float = 0.0
    units_touched: int = 0
    new_weaknesses: list[str] = field(default_factory=list)
    chronic: list[str] = field(default_factory=list)
    improving: list[str] = field(default_factory=list)
    mastered_in_window: list[str] = field(default_factory=list)
    reactivated: list[str] = field(default_factory=list)
    knowledge_debt: int = 0

    def to_dict(self) -> dict:
        return self.__dict__


def window_report(store: Store, scale: str = "weekly", profile: WeaknessProfile | None = None) -> WindowReport:
    days, goal = WINDOWS.get(scale, WINDOWS["weekly"])
    profile = profile or build_profile(store)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    cards = {c.id: c for c in store.list_cards(include_retired=True)}
    ku_of_card = {cid: c.ku_id for cid, c in cards.items()}
    labels = {ku.id: ku.label for ku in store.list_kus()}

    reviews = [r for r in store.list_reviews() if _parse(r.reviewed_at) >= cutoff]
    lapses = [r for r in reviews if r.failed]
    touched = {ku_of_card.get(r.card_id) for r in reviews} - {None}

    report = WindowReport(scale=scale, goal=goal, days=days, reviews=len(reviews), lapses=len(lapses))
    report.lapse_rate = round(len(lapses) / len(reviews), 3) if reviews else 0.0
    report.units_touched = len(touched)

    failing_now = {ku_of_card.get(r.card_id) for r in lapses} - {None}
    for ku_id in failing_now:
        unit = profile.by_id(ku_id)
        if not unit:
            continue
        label = labels.get(ku_id, ku_id)
        if unit.repeated_failure_count >= 3 or unit.failure_rate >= 0.5:
            report.chronic.append(label)
        else:
            report.new_weaknesses.append(label)

    for unit in profile.units:
        if unit.attempts and unit.failure_rate <= 0.2 and unit.status in {"STABLE", "LEARNING"}:
            report.improving.append(unit.label)

    for ku in store.list_kus():
        if ku.mastered_at and _parse(ku.mastered_at) >= cutoff:
            report.mastered_in_window.append(ku.label)

    for event in store.recent_events(200):
        if event["kind"] == "reactivated" and _parse(event["created_at"]) >= cutoff:
            report.reactivated.append(event["payload"].get("label", ""))

    report.knowledge_debt = sum(
        1 for ku in store.list_kus() if ku.status in {"WEAK", "RELEARNING"}
    )
    report.improving = report.improving[:8]
    return report


# ---------------------------------------------------------------------------
# D. Anki Update Plan
# ---------------------------------------------------------------------------

@dataclass
class AnkiUpdatePlan:
    new_cards: list[dict] = field(default_factory=list)
    suspend_candidates: list[dict] = field(default_factory=list)
    retire_candidates: list[dict] = field(default_factory=list)
    tag_updates: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__

    @property
    def empty(self) -> bool:
        return not (self.new_cards or self.suspend_candidates or self.retire_candidates or self.tag_updates)


def anki_update_plan(store: Store, profile: WeaknessProfile | None = None) -> AnkiUpdatePlan:
    profile = profile or build_profile(store)
    plan = AnkiUpdatePlan()
    labels = {ku.id: ku.label for ku in store.list_kus()}
    status_of = {ku.id: ku.status for ku in store.list_kus()}

    for card in store.list_cards():
        reviews = store.list_reviews(card.id)
        lapses = sum(1 for r in reviews if r.failed)
        successes = len(reviews) - lapses
        label = labels.get(card.ku_id, card.ku_id)

        if not card.anki_note_id:
            plan.new_cards.append({"card_id": card.id, "unit": label, "question": card.question})

        # A card that has been answered many times and never once correctly is more
        # likely to be a badly written card than a knowledge gap.
        if len(reviews) >= 4 and successes == 0:
            plan.retire_candidates.append(
                {"card_id": card.id, "unit": label, "question": card.question,
                 "reason": f"{lapses} attempts, never correct — rewrite or split this card"}
            )
        elif lapses >= 5 and not card.suspended:
            plan.suspend_candidates.append(
                {"card_id": card.id, "unit": label, "question": card.question,
                 "reason": f"leech: {lapses} lapses — suspend until the source has been re-read"}
            )

        wanted = f"status::{status_of.get(card.ku_id, 'LEARNING')}"
        current = [t for t in card.tags if t.startswith("status::")]
        if current != [wanted]:
            plan.tag_updates.append({"card_id": card.id, "unit": label, "add": wanted,
                                     "remove": current})

    return plan


def apply_anki_plan(store: Store, plan: AnkiUpdatePlan, suspend: bool = True,
                    retire: bool = False, retag: bool = True) -> dict:
    """Apply the parts of the plan the doctor confirmed."""
    done = {"suspended": 0, "retired": 0, "retagged": 0}

    if suspend:
        for item in plan.suspend_candidates:
            card = store.get_card(item["card_id"])
            if card:
                card.suspended = 1
                store.upsert_card(card)
                done["suspended"] += 1
    if retire:
        for item in plan.retire_candidates:
            card = store.get_card(item["card_id"])
            if card:
                card.retired = 1
                store.upsert_card(card)
                done["retired"] += 1
    if retag:
        for item in plan.tag_updates:
            card = store.get_card(item["card_id"])
            if card:
                card.tags = [t for t in card.tags if not t.startswith("status::")] + [item["add"]]
                store.upsert_card(card)
                done["retagged"] += 1

    store.log_event("anki_update_plan", done)
    return done


# ---------------------------------------------------------------------------
# The full bundle
# ---------------------------------------------------------------------------

@dataclass
class AnalysisBundle:
    scale: str
    window: WindowReport
    gaps: list[UnitProfile]
    prescriptions: list[StudyPlan]
    anki_plan: AnkiUpdatePlan
    statuses: dict[str, int]
    transitions: list[lifecycle.Transition]
    patterns: list[dict] = field(default_factory=list)

    @property
    def top_prescription(self) -> StudyPlan | None:
        return self.prescriptions[0] if self.prescriptions else None


def run_analysis(store: Store, scale: str = "weekly", limit: int = 10) -> AnalysisBundle:
    """One full pass: profile → gaps → prescriptions → Anki plan → statuses."""
    profile = build_profile(store)
    diagnostics_saved = _persist_hypotheses(store, profile)
    prescriptions = prescribe(store, profile, limit=limit)
    transitions = lifecycle.sync_statuses(store, profile)
    profile = build_profile(store)  # statuses changed, refresh the view

    gaps = sorted([u for u in profile.units if u.gap_score > 0],
                  key=lambda u: u.gap_score, reverse=True)[:limit]

    return AnalysisBundle(
        scale=scale,
        window=window_report(store, scale, profile),
        gaps=gaps,
        prescriptions=prescriptions,
        anki_plan=anki_update_plan(store, profile),
        statuses=lifecycle.counts(store),
        transitions=transitions,
        patterns=[p.to_dict() for p in profile.patterns],
    )


def bundle_markdown(store: Store, bundle: AnalysisBundle) -> str:
    w = bundle.window
    lines = [
        f"# {bundle.scale.capitalize()} learning report",
        f"*{w.goal}*",
        "",
        "## A · Knowledge Gap Report",
        f"{w.reviews} reviews · {w.lapses} lapses ({w.lapse_rate:.0%}) · "
        f"{w.units_touched} knowledge units touched · knowledge debt: {w.knowledge_debt} units",
        "",
    ]
    for i, unit in enumerate(bundle.gaps, 1):
        lines.append(
            f"**Priority {i} — {unit.label}**  \n"
            f"Error type: {unit.top_error or 'unclassified'} · "
            f"Frequency: {unit.failures}/{unit.attempts} · "
            f"Severity: {unit.importance}/5 · "
            f"Gap score: {unit.gap_score:.1f} · "
            f"FSRS: stability {unit.mean_stability or '—'}d, difficulty {unit.mean_difficulty or '—'}"
        )
    if bundle.patterns:
        lines += ["", "**Patterns**"] + [f"- {p['narrative']}" for p in bundle.patterns]

    lines += ["", "## B · Learning Prescriptions", ""]
    for plan in bundle.prescriptions:
        lines.append(to_markdown(store, plan))
        lines.append("")

    lines += ["## C · Gemini NotebookLM prompt (top priority)", ""]
    top = bundle.top_prescription
    lines += ["```", top.gemini_prompt if top else "Nothing to study — no open gap.", "```", ""]

    plan = bundle.anki_plan
    lines += [
        "## D · Anki Update Plan",
        f"- New cards to send: {len(plan.new_cards)}",
        f"- Suspend candidates (leeches): {len(plan.suspend_candidates)}",
        f"- Retire candidates (likely bad cards): {len(plan.retire_candidates)}",
        f"- Tag updates: {len(plan.tag_updates)}",
        "",
        "## E · Mastery Status",
    ]
    for status in STATUS_FLOW:
        lines.append(f"- {status}: {bundle.statuses.get(status, 0)}")
    if bundle.transitions:
        lines += ["", "**Status changes this run**"] + [
            f"- {t.label}: {t.old} → {t.new} ({t.reason})" for t in bundle.transitions
        ]
    if w.reactivated:
        lines += ["", "**Reactivated after decline**"] + [f"- {r}" for r in w.reactivated]

    mastery = [r for r in evaluate_all(store) if r.mastered]
    if mastery:
        lines += ["", "**Mastered**"] + [f"- {r.label}" for r in mastery]
    return "\n".join(lines)
