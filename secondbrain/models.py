"""Dataclasses for the Second Brain domain model."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _loads(value: Any, default: Any) -> Any:
    if value in (None, "", b""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Source:
    """An authoritative source uploaded to NotebookLM."""

    title: str
    kind: str = "guideline"  # guideline | textbook | review | lecture | pdf | slides
    citation: str = ""
    notes: str = ""
    id: str = field(default_factory=lambda: new_id("src"))
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def from_row(cls, row) -> "Source":
        return cls(**dict(row))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KnowledgeUnit:
    """The atomic unit of the Second Brain: one clinically meaningful piece of knowledge."""

    topic: str
    subtopic: str = ""
    statement: str = ""
    clinical_significance: str = ""
    thresholds: str = ""
    exceptions: str = ""
    algorithm: str = ""
    common_mistakes: str = ""
    source_id: str = ""
    chapter: str = ""
    section: str = ""
    location: str = ""  # page / table / figure / timestamp
    why_relevant: str = ""
    importance: int = 3  # 1..5 clinical importance
    status: str = "LEARNING"  # LEARNING | REPAIRING | CONSOLIDATING | MASTERED
    id: str = field(default_factory=lambda: new_id("ku"))
    created_at: str = field(default_factory=now_iso)
    mastered_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "KnowledgeUnit":
        return cls(**dict(row))

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def label(self) -> str:
        return f"{self.topic} › {self.subtopic}" if self.subtopic else self.topic

    def source_locator(self, source_title: str = "") -> str:
        bits = [source_title or self.source_id]
        for part in (self.chapter, self.section, self.location):
            if part:
                bits.append(part)
        return " · ".join(b for b in bits if b)


@dataclass
class Card:
    """A testable item derived from a knowledge unit (Anki card or MCQ)."""

    ku_id: str
    question: str
    answer: str
    card_type: str = "BASIC"  # BASIC | CLOZE | MCQ
    options: list[str] = field(default_factory=list)
    correct_option: int | None = None
    explanation: str = ""
    cognitive_level: int = 1  # 1..5, see taxonomy.COGNITIVE_LEVELS
    error_target: str = ""  # which error type this item probes
    tags: list[str] = field(default_factory=list)
    generation: int = 1  # learning cycle that produced this item
    anki_note_id: int | None = None
    retired: int = 0
    id: str = field(default_factory=lambda: new_id("card"))
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def from_row(cls, row) -> "Card":
        data = dict(row)
        data["options"] = _loads(data.pop("options_json", None), [])
        data["tags"] = _loads(data.pop("tags_json", None), [])
        return cls(**data)

    def to_row(self) -> dict:
        data = asdict(self)
        data["options_json"] = json.dumps(data.pop("options"), ensure_ascii=False)
        data["tags_json"] = json.dumps(data.pop("tags"), ensure_ascii=False)
        return data

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Review:
    """One review event coming back from Anki / FSRS."""

    card_id: str
    reviewed_at: str
    rating: int  # 1 Again, 2 Hard, 3 Good, 4 Easy
    anki_note_id: int | None = None
    state: str = ""
    elapsed_days: float = 0.0
    scheduled_days: float = 0.0
    duration_ms: int = 0
    stability: float | None = None
    difficulty: float | None = None
    retrievability: float | None = None
    origin: str = "ankiconnect"  # ankiconnect | csv | manual | simulated
    id: int | None = None

    @property
    def failed(self) -> bool:
        return self.rating <= 1

    @classmethod
    def from_row(cls, row) -> "Review":
        return cls(**dict(row))


@dataclass
class Diagnosis:
    """An error diagnosis attached to a knowledge unit."""

    ku_id: str
    error_type: str
    confidence: float = 0.5
    evidence: str = ""
    engine: str = "heuristic"  # heuristic | claude | manual
    resolved: int = 0
    resolved_at: str | None = None
    id: int | None = None
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def from_row(cls, row) -> "Diagnosis":
        return cls(**dict(row))


@dataclass
class ReviewTarget:
    """WHERE the fix lives inside the original source."""

    ku_id: str
    source_title: str
    chapter: str
    section: str
    location: str
    knowledge_unit: str
    why_relevant: str
    focus_points: list[str] = field(default_factory=list)
    ignore_for_now: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StudyPlan:
    """A targeted re-study instruction: WHAT -> WHERE -> WHY -> HOW."""

    ku_id: str
    what: str
    where: str
    why: str
    how: list[str] = field(default_factory=list)
    next_level: int = 1
    error_types: list[str] = field(default_factory=list)
    priority: float = 0.0
    status: str = "OPEN"  # OPEN | DONE
    id: int | None = None
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)
