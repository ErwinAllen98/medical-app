"""Cumulative Weakness Profile + heuristic error diagnosis.

FSRS tells us *that* we are struggling. This module is the first layer that
starts answering *why*: it aggregates review history per knowledge unit and per
topic, detects failure signatures, and proposes error types from the taxonomy.
Claude (see ``secondbrain.claude``) refines these hypotheses.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from .config import (
    HIGH_FAILURE_RATE,
    RECURRENT_CONCEPT_MIN_UNITS,
    REPEATED_FAILURE_THRESHOLD,
)
from .models import Card, KnowledgeUnit, Review
from .store import Store
from .taxonomy import ERROR_TO_LEVEL, ERROR_TYPES


def _parse(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _days_ago(ts: str) -> float:
    return max(0.0, (datetime.now(timezone.utc) - _parse(ts)).total_seconds() / 86400.0)


@dataclass
class UnitProfile:
    """Everything we know about how the doctor performs on one knowledge unit."""

    ku_id: str
    topic: str
    subtopic: str
    label: str
    importance: int
    status: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    failure_rate: float = 0.0
    repeated_failure_count: int = 0   # max consecutive lapse streak
    lapses_after_success: int = 0     # forgetting after having known it
    distinct_cards: int = 0
    distinct_failed_cards: int = 0
    levels_attempted: list[int] = field(default_factory=list)
    level_pass_rate: dict[int, float] = field(default_factory=dict)
    last_reviewed_days: float | None = None
    last_rating: int | None = None
    mean_stability: float | None = None
    min_retrievability: float | None = None
    mean_answer_seconds: float | None = None
    mean_difficulty: float | None = None
    signatures: list[str] = field(default_factory=list)
    error_hypotheses: list[dict] = field(default_factory=list)
    severity: float = 0.0
    priority: float = 0.0
    gap_score: float = 0.0
    gap_factors: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    @property
    def top_error(self) -> str | None:
        return self.error_hypotheses[0]["error_type"] if self.error_hypotheses else None

    @property
    def is_weak(self) -> bool:
        return bool(self.signatures) or self.failure_rate >= HIGH_FAILURE_RATE

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TopicPattern:
    """A pattern that spans several knowledge units — the thing FSRS cannot see."""

    topic: str
    units_involved: int
    failing_units: int
    attempts: int
    failures: int
    failure_rate: float
    dominant_error: str | None
    severity: float
    narrative: str
    ku_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WeaknessProfile:
    units: list[UnitProfile]
    patterns: list[TopicPattern]
    generated_at: str

    @property
    def weak_units(self) -> list[UnitProfile]:
        return [u for u in self.units if u.is_weak]

    def top(self, n: int = 10) -> list[UnitProfile]:
        return sorted(self.units, key=lambda u: u.priority, reverse=True)[:n]

    def by_id(self, ku_id: str) -> UnitProfile | None:
        return next((u for u in self.units if u.ku_id == ku_id), None)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "units": [u.to_dict() for u in self.units],
            "patterns": [p.to_dict() for p in self.patterns],
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _level_stats(cards: dict[str, Card], reviews: list[Review]) -> dict[int, tuple[int, int]]:
    """level -> (attempts, successes)"""
    out: dict[int, list[int]] = {}
    for rv in reviews:
        card = cards.get(rv.card_id)
        if not card:
            continue
        bucket = out.setdefault(int(card.cognitive_level or 1), [0, 0])
        bucket[0] += 1
        if not rv.failed:
            bucket[1] += 1
    return {lvl: (a, s) for lvl, (a, s) in out.items()}


def _hypothesise(
    ku: KnowledgeUnit,
    profile: UnitProfile,
    failed_cards: list[Card],
) -> list[dict]:
    """Propose error types from card metadata + knowledge-unit content."""
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def bump(err: str, weight: float, reason: str) -> None:
        if err not in ERROR_TYPES:
            return
        scores[err] = scores.get(err, 0.0) + weight
        reasons.setdefault(err, []).append(reason)

    # 1. The card itself declares which error type it probes.
    for card in failed_cards:
        if card.error_target:
            bump(card.error_target, 1.0, f"failed an item explicitly probing {card.error_target}")

    # 2. Content of the knowledge unit hints at the kind of knowledge at risk.
    if ku.thresholds.strip():
        bump("THRESHOLD_ERROR", 0.6, "the unit carries numeric thresholds")
    if ku.exceptions.strip():
        bump("EXCEPTION_ERROR", 0.6, "the unit carries explicit exceptions")
    if ku.algorithm.strip():
        bump("SEQUENCE_ERROR", 0.5, "the unit carries a stepwise algorithm")

    text = " ".join(
        [ku.statement, ku.subtopic, ku.common_mistakes, " ".join(c.question for c in failed_cards)]
    ).lower()
    keyword_map = {
        "CONTRAINDICATION_ERROR": ("contraindicat", "avoid in", "should not be used", "منع مصرف"),
        "INDICATION_ERROR": ("indicat", "when to start", "candidate for", "اندیکاسیون"),
        "MONITORING_ERROR": ("monitor", "follow-up", "recheck", "surveillance", "پایش"),
        "MANAGEMENT_ERROR": ("first-line", "treatment of choice", "management", "escalat", "درمان"),
        "DISCRIMINATION_ERROR": ("versus", " vs ", "differentiat", "distinguish", "افتراق"),
        "THRESHOLD_ERROR": ("egfr", "hba1c", "mg/dl", "mmhg", "cut-off", "cutoff", "threshold", "≥", "≤"),
        "SEQUENCE_ERROR": ("next step", "first step", "algorithm", "sequence", "order of"),
    }
    for err, words in keyword_map.items():
        if any(w in text for w in words):
            bump(err, 0.4, "wording of the failed items points this way")

    # 3. Performance shape.
    lvl = profile.level_pass_rate
    low = [v for k, v in lvl.items() if k <= 2]
    high = [v for k, v in lvl.items() if k >= 4]
    if low and high and statistics.mean(low) >= 0.75 and statistics.mean(high) <= 0.4:
        bump("CONCEPT_ERROR", 0.9, "recall is fine but clinical application fails")
    if high and low and statistics.mean(high) >= 0.7 and statistics.mean(low) <= 0.4:
        bump("FACTUAL_ERROR", 0.7, "reasoning is fine but the raw fact is not retrievable")
    if profile.distinct_failed_cards >= 2 and profile.failure_rate >= HIGH_FAILURE_RATE:
        bump("CONCEPT_ERROR", 0.5, "several different formulations of the same unit fail")
    if not scores:
        bump("FACTUAL_ERROR", 0.3, "no stronger signal available yet")

    total = sum(scores.values()) or 1.0
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {
            "error_type": err,
            "confidence": round(min(0.95, score / total + 0.15 * min(score, 2.0)), 2),
            "evidence": "; ".join(dict.fromkeys(reasons[err])),
            "target_level": ERROR_TO_LEVEL.get(err, 2),
        }
        for err, score in ranked[:3]
    ]


def _signatures(profile: UnitProfile, reviews: list[Review], cards: dict[str, Card]) -> list[str]:
    sigs: list[str] = []
    if profile.attempts >= 2 and profile.successes == 0:
        sigs.append("KNOWLEDGE_GAP")
    if profile.failures >= REPEATED_FAILURE_THRESHOLD:
        sigs.append("REPEATED_FAILURE")
    if profile.lapses_after_success >= 2:
        sigs.append("UNSTABLE_RETENTION")

    # false confidence: an "Easy" rating followed later by a lapse on the same card
    per_card: dict[str, list[Review]] = {}
    for rv in reviews:
        per_card.setdefault(rv.card_id, []).append(rv)
    for card_reviews in per_card.values():
        seen_easy = False
        for rv in card_reviews:
            if rv.rating >= 4:
                seen_easy = True
            elif rv.failed and seen_easy:
                sigs.append("FALSE_CONFIDENCE")
                break
        if "FALSE_CONFIDENCE" in sigs:
            break

    lvl = profile.level_pass_rate
    low = [v for k, v in lvl.items() if k <= 2]
    high = [v for k, v in lvl.items() if k >= 4]
    if low and high:
        if statistics.mean(low) >= 0.75 and statistics.mean(high) <= 0.4:
            sigs.append("MEMORISED_NOT_UNDERSTOOD")
        if statistics.mean(high) >= 0.75 and statistics.mean(low) <= 0.4:
            sigs.append("UNDERSTOOD_NOT_RETRIEVABLE")
    return list(dict.fromkeys(sigs))


def build_profile(store: Store) -> WeaknessProfile:
    """Compute the Cumulative Weakness Profile across the whole collection."""
    units: list[UnitProfile] = []
    all_cards = {c.id: c for c in store.list_cards(include_retired=True)}

    for ku in store.list_kus():
        ku_cards = [c for c in all_cards.values() if c.ku_id == ku.id]
        reviews = store.reviews_for_ku(ku.id)
        p = UnitProfile(
            ku_id=ku.id,
            topic=ku.topic,
            subtopic=ku.subtopic,
            label=ku.label,
            importance=int(ku.importance or 3),
            status=ku.status,
            distinct_cards=len(ku_cards),
        )

        if reviews:
            p.attempts = len(reviews)
            p.failures = sum(1 for r in reviews if r.failed)
            p.successes = p.attempts - p.failures
            p.failure_rate = round(p.failures / p.attempts, 3)
            p.last_reviewed_days = round(_days_ago(reviews[-1].reviewed_at), 2)
            p.last_rating = reviews[-1].rating
            p.distinct_failed_cards = len({r.card_id for r in reviews if r.failed})

            streak = best = 0
            had_success = False
            for rv in reviews:
                if rv.failed:
                    streak += 1
                    best = max(best, streak)
                    if had_success:
                        p.lapses_after_success += 1
                else:
                    streak = 0
                    had_success = True
            p.repeated_failure_count = best

            diff = [r.difficulty for r in reviews if r.difficulty is not None]
            p.mean_difficulty = round(statistics.mean(diff), 2) if diff else None
            stab = [r.stability for r in reviews if r.stability is not None]
            retr = [r.retrievability for r in reviews if r.retrievability is not None]
            durs = [r.duration_ms for r in reviews if r.duration_ms]
            p.mean_stability = round(statistics.mean(stab), 2) if stab else None
            p.min_retrievability = round(min(retr), 3) if retr else None
            p.mean_answer_seconds = round(statistics.mean(durs) / 1000.0, 1) if durs else None

            lstats = _level_stats(all_cards, reviews)
            p.levels_attempted = sorted(lstats)
            p.level_pass_rate = {lvl: round(s / a, 2) for lvl, (a, s) in lstats.items() if a}

        p.signatures = _signatures(p, reviews, all_cards)
        failed_cards = [all_cards[r.card_id] for r in reviews if r.failed and r.card_id in all_cards]
        if p.attempts:
            p.error_hypotheses = _hypothesise(ku, p, failed_cards)

        p.gap_score, p.gap_factors = _gap_score(p)

        # Severity: how badly broken × how clinically important × how fresh.
        volume = math.log1p(p.attempts)
        recency_weight = 1.0
        if p.last_reviewed_days is not None:
            recency_weight = 1.0 if p.last_reviewed_days <= 14 else max(0.4, 14.0 / p.last_reviewed_days)
        repeat_boost = 1.0 + 0.25 * max(0, p.repeated_failure_count - 1)
        p.severity = round(p.failure_rate * volume * repeat_boost * (p.importance / 3.0), 3)
        p.priority = round(p.severity * recency_weight * (1.6 if "KNOWLEDGE_GAP" in p.signatures else 1.0), 3)

        ev: list[str] = []
        if p.attempts:
            ev.append(f"{p.failures}/{p.attempts} failures (rate {p.failure_rate:.0%})")
        if p.repeated_failure_count >= 2:
            ev.append(f"lapse streak of {p.repeated_failure_count}")
        if p.distinct_failed_cards >= 2:
            ev.append(f"{p.distinct_failed_cards} different formulations failed")
        if p.min_retrievability is not None:
            ev.append(f"min retrievability {p.min_retrievability:.2f}")
        if p.mean_stability is not None:
            ev.append(f"mean stability {p.mean_stability:.1f}d")
        for sig in p.signatures:
            ev.append(f"signature: {sig}")
        p.evidence = ev

        units.append(p)

    patterns = _topic_patterns(units)
    return WeaknessProfile(
        units=units,
        patterns=patterns,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _gap_score(p: UnitProfile) -> tuple[float, dict[str, float]]:
    """Knowledge Gap Score (0-100).

        frequency × severity × recency × retrieval difficulty × low stability

    Every factor is normalised to 0-1 so the product stays interpretable and the
    resulting ranking is a real priority list, not a raw error count.
    """
    if not p.attempts:
        return 0.0, {}

    # 1. How often does it fail (rate, weighted by how many attempts back it up)
    confidence = min(1.0, p.attempts / 6.0)
    frequency = round(p.failure_rate * (0.5 + 0.5 * confidence), 3)

    # 2. How much does it matter clinically, and how deep is the failure
    depth = min(1.0, 0.4 + 0.2 * p.repeated_failure_count + 0.2 * p.distinct_failed_cards)
    severity = round((p.importance / 5.0) * depth, 3)

    # 3. Is it a live problem or an old one
    days = p.last_reviewed_days if p.last_reviewed_days is not None else 60.0
    recency = round(max(0.25, min(1.0, 14.0 / (days + 1.0))), 3)

    # 4. How hard is retrieval right now (FSRS difficulty, else the failure shape)
    if p.mean_difficulty is not None:
        retrieval = round(min(1.0, p.mean_difficulty / 10.0), 3)
    else:
        retrieval = round(min(1.0, 0.3 + 0.7 * p.failure_rate), 3)

    # 5. How fragile is the memory (FSRS stability, 21 days = solid)
    if p.mean_stability is not None:
        low_stability = round(max(0.1, min(1.0, 21.0 / (p.mean_stability + 3.0))), 3)
    else:
        low_stability = 0.7

    score = frequency * severity * recency * retrieval * low_stability * 100
    factors = {
        "frequency": frequency,
        "severity": severity,
        "recency": recency,
        "retrieval_difficulty": retrieval,
        "low_stability": low_stability,
    }
    return round(score, 2), factors


def _topic_patterns(units: list[UnitProfile]) -> list[TopicPattern]:
    """Aggregate across units so we say 'you keep failing SGLT2i initiation
    thresholds' instead of 'you failed 4 cards'."""
    by_topic: dict[str, list[UnitProfile]] = {}
    for u in units:
        by_topic.setdefault(u.topic or "Uncategorised", []).append(u)

    patterns: list[TopicPattern] = []
    for topic, group in by_topic.items():
        attempts = sum(u.attempts for u in group)
        if not attempts:
            continue
        failures = sum(u.failures for u in group)
        failing = [u for u in group if u.is_weak and u.attempts]
        if len(failing) < RECURRENT_CONCEPT_MIN_UNITS and failures / attempts < HIGH_FAILURE_RATE:
            continue

        err_scores: dict[str, float] = {}
        for u in failing:
            for h in u.error_hypotheses:
                err_scores[h["error_type"]] = err_scores.get(h["error_type"], 0.0) + h["confidence"]
        dominant = max(err_scores, key=err_scores.get) if err_scores else None

        subtopics = [u.subtopic or u.label for u in failing][:3]
        focus = ", ".join(dict.fromkeys(subtopics))
        if dominant:
            human = ERROR_TYPES[dominant]["label"].lower()
            narrative = (
                f"You repeatedly fail {human} questions in {topic}"
                + (f" — especially {focus}." if focus else ".")
            )
        else:
            narrative = f"{topic} is unstable across {len(failing)} knowledge units."

        patterns.append(
            TopicPattern(
                topic=topic,
                units_involved=len(group),
                failing_units=len(failing),
                attempts=attempts,
                failures=failures,
                failure_rate=round(failures / attempts, 3),
                dominant_error=dominant,
                severity=round(sum(u.severity for u in failing), 3),
                narrative=narrative,
                ku_ids=[u.ku_id for u in failing],
            )
        )
    return sorted(patterns, key=lambda p: p.severity, reverse=True)


def persist_hypotheses(store: Store, profile: WeaknessProfile, min_confidence: float = 0.3) -> int:
    """Write heuristic diagnoses into the store (Claude can add better ones later)."""
    saved = 0
    from .models import Diagnosis

    for unit in profile.weak_units:
        existing = {d.error_type for d in store.list_diagnoses(unit.ku_id, unresolved_only=True)}
        for h in unit.error_hypotheses:
            if h["confidence"] < min_confidence or h["error_type"] in existing:
                continue
            store.add_diagnosis(
                Diagnosis(
                    ku_id=unit.ku_id,
                    error_type=h["error_type"],
                    confidence=h["confidence"],
                    evidence=h["evidence"] or "; ".join(unit.evidence),
                    engine="heuristic",
                )
            )
            saved += 1
    return saved
