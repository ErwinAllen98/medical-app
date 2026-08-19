"""SQLite persistence layer for the Second Brain."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .config import DB_PATH
from .models import (
    Card,
    Diagnosis,
    KnowledgeUnit,
    Review,
    Source,
    StudyPlan,
    now_iso,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT,
    citation TEXT,
    notes TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_units (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    subtopic TEXT,
    statement TEXT,
    clinical_significance TEXT,
    thresholds TEXT,
    exceptions TEXT,
    algorithm TEXT,
    common_mistakes TEXT,
    source_id TEXT,
    chapter TEXT,
    section TEXT,
    location TEXT,
    why_relevant TEXT,
    importance INTEGER DEFAULT 3,
    status TEXT DEFAULT 'UNSEEN',
    status_changed_at TEXT,
    created_at TEXT,
    mastered_at TEXT,
    FOREIGN KEY (source_id) REFERENCES sources (id)
);

CREATE TABLE IF NOT EXISTS ku_links (
    ku_id TEXT,
    related_ku_id TEXT,
    PRIMARY KEY (ku_id, related_ku_id)
);

CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    ku_id TEXT NOT NULL,
    question TEXT,
    answer TEXT,
    card_type TEXT,
    options_json TEXT,
    correct_option INTEGER,
    explanation TEXT,
    cognitive_level INTEGER DEFAULT 1,
    error_target TEXT,
    learning_objective TEXT,
    difficulty INTEGER DEFAULT 3,
    suspended INTEGER DEFAULT 0,
    tags_json TEXT,
    generation INTEGER DEFAULT 1,
    anki_note_id INTEGER,
    retired INTEGER DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (ku_id) REFERENCES knowledge_units (id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL,
    anki_note_id INTEGER,
    reviewed_at TEXT,
    rating INTEGER,
    state TEXT,
    elapsed_days REAL,
    scheduled_days REAL,
    duration_ms INTEGER,
    stability REAL,
    difficulty REAL,
    retrievability REAL,
    origin TEXT,
    UNIQUE (card_id, reviewed_at, rating)
);

CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ku_id TEXT NOT NULL,
    error_type TEXT,
    confidence REAL,
    evidence TEXT,
    engine TEXT,
    resolved INTEGER DEFAULT 0,
    resolved_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS study_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ku_id TEXT NOT NULL,
    what TEXT,
    where_ TEXT,
    why TEXT,
    how_json TEXT,
    what_to_study TEXT,
    how_much TEXT,
    methods_json TEXT,
    gemini_prompt TEXT,
    gap_score REAL,
    next_level INTEGER,
    error_types_json TEXT,
    priority REAL,
    status TEXT DEFAULT 'OPEN',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS notion_exports (
    ku_id TEXT PRIMARY KEY,
    page_id TEXT,
    page_url TEXT,
    exported_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT,
    payload_json TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_cards_ku ON cards (ku_id);
CREATE INDEX IF NOT EXISTS idx_reviews_card ON reviews (card_id);
CREATE INDEX IF NOT EXISTS idx_diag_ku ON diagnoses (ku_id);
"""


class Store:
    """Thin, dependency-free data access layer."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # -- plumbing ---------------------------------------------------------
    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    _MIGRATIONS = {
        "cards": {
            "learning_objective": "TEXT",
            "difficulty": "INTEGER DEFAULT 3",
            "suspended": "INTEGER DEFAULT 0",
        },
        "knowledge_units": {"status_changed_at": "TEXT"},
        "study_plans": {
            "what_to_study": "TEXT",
            "how_much": "TEXT",
            "methods_json": "TEXT",
            "gemini_prompt": "TEXT",
            "gap_score": "REAL",
        },
    }

    def _init_schema(self) -> None:
        with self.conn() as con:
            con.executescript(SCHEMA)
            for table, columns in self._MIGRATIONS.items():
                existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                for name, decl in columns.items():
                    if name not in existing:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    # -- sources ----------------------------------------------------------
    def upsert_source(self, source: Source) -> Source:
        with self.conn() as con:
            con.execute(
                """INSERT INTO sources (id, title, kind, citation, notes, created_at)
                   VALUES (:id, :title, :kind, :citation, :notes, :created_at)
                   ON CONFLICT(id) DO UPDATE SET
                       title=excluded.title, kind=excluded.kind,
                       citation=excluded.citation, notes=excluded.notes""",
                source.to_dict(),
            )
        return source

    def get_source(self, source_id: str) -> Source | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return Source.from_row(row) if row else None

    def find_source_by_title(self, title: str) -> Source | None:
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM sources WHERE lower(title) = lower(?)", (title.strip(),)
            ).fetchone()
        return Source.from_row(row) if row else None

    def list_sources(self) -> list[Source]:
        with self.conn() as con:
            rows = con.execute("SELECT * FROM sources ORDER BY created_at DESC").fetchall()
        return [Source.from_row(r) for r in rows]

    def source_titles(self) -> dict[str, str]:
        return {s.id: s.title for s in self.list_sources()}

    # -- knowledge units --------------------------------------------------
    def upsert_ku(self, ku: KnowledgeUnit) -> KnowledgeUnit:
        with self.conn() as con:
            con.execute(
                """INSERT INTO knowledge_units
                   (id, topic, subtopic, statement, clinical_significance, thresholds,
                    exceptions, algorithm, common_mistakes, source_id, chapter, section,
                    location, why_relevant, importance, status, status_changed_at,
                    created_at, mastered_at)
                   VALUES
                   (:id, :topic, :subtopic, :statement, :clinical_significance, :thresholds,
                    :exceptions, :algorithm, :common_mistakes, :source_id, :chapter, :section,
                    :location, :why_relevant, :importance, :status, :status_changed_at,
                    :created_at, :mastered_at)
                   ON CONFLICT(id) DO UPDATE SET
                       topic=excluded.topic, subtopic=excluded.subtopic,
                       statement=excluded.statement,
                       clinical_significance=excluded.clinical_significance,
                       thresholds=excluded.thresholds, exceptions=excluded.exceptions,
                       algorithm=excluded.algorithm, common_mistakes=excluded.common_mistakes,
                       source_id=excluded.source_id, chapter=excluded.chapter,
                       section=excluded.section, location=excluded.location,
                       why_relevant=excluded.why_relevant, importance=excluded.importance,
                       status=excluded.status, mastered_at=excluded.mastered_at,
                       status_changed_at=excluded.status_changed_at""",
                ku.to_dict(),
            )
        return ku

    def get_ku(self, ku_id: str) -> KnowledgeUnit | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM knowledge_units WHERE id = ?", (ku_id,)).fetchone()
        return KnowledgeUnit.from_row(row) if row else None

    def list_kus(self, status: str | None = None) -> list[KnowledgeUnit]:
        query = "SELECT * FROM knowledge_units"
        params: tuple = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY importance DESC, created_at DESC"
        with self.conn() as con:
            rows = con.execute(query, params).fetchall()
        return [KnowledgeUnit.from_row(r) for r in rows]

    def set_ku_status(self, ku_id: str, status: str) -> bool:
        """Set the lifecycle status. Returns True when it actually changed."""
        with self.conn() as con:
            row = con.execute("SELECT status FROM knowledge_units WHERE id = ?", (ku_id,)).fetchone()
            if not row:
                return False
            if row["status"] == status:
                return False
            mastered_at = now_iso() if status == "MASTERED" else None
            con.execute(
                """UPDATE knowledge_units
                   SET status = ?, status_changed_at = ?, mastered_at = COALESCE(?, mastered_at)
                   WHERE id = ?""",
                (status, now_iso(), mastered_at, ku_id),
            )
            con.execute(
                "INSERT INTO events (kind, payload_json, created_at) VALUES (?, ?, ?)",
                ("status_change",
                 json.dumps({"ku_id": ku_id, "from": row["status"], "to": status}, ensure_ascii=False),
                 now_iso()),
            )
        return True

    def link_kus(self, ku_id: str, related: Iterable[str]) -> None:
        with self.conn() as con:
            for other in related:
                if other and other != ku_id:
                    con.execute(
                        "INSERT OR IGNORE INTO ku_links (ku_id, related_ku_id) VALUES (?, ?)",
                        (ku_id, other),
                    )

    def related_kus(self, ku_id: str) -> list[str]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT related_ku_id FROM ku_links WHERE ku_id = ?", (ku_id,)
            ).fetchall()
        return [r[0] for r in rows]

    # -- cards ------------------------------------------------------------
    def upsert_card(self, card: Card) -> Card:
        with self.conn() as con:
            con.execute(
                """INSERT INTO cards
                   (id, ku_id, question, answer, card_type, options_json, correct_option,
                    explanation, cognitive_level, error_target, learning_objective, difficulty,
                    suspended, tags_json, generation, anki_note_id, retired, created_at)
                   VALUES
                   (:id, :ku_id, :question, :answer, :card_type, :options_json, :correct_option,
                    :explanation, :cognitive_level, :error_target, :learning_objective, :difficulty,
                    :suspended, :tags_json, :generation, :anki_note_id, :retired, :created_at)
                   ON CONFLICT(id) DO UPDATE SET
                       question=excluded.question, answer=excluded.answer,
                       card_type=excluded.card_type, options_json=excluded.options_json,
                       correct_option=excluded.correct_option, explanation=excluded.explanation,
                       cognitive_level=excluded.cognitive_level,
                       error_target=excluded.error_target,
                       learning_objective=excluded.learning_objective,
                       difficulty=excluded.difficulty, suspended=excluded.suspended,
                       tags_json=excluded.tags_json,
                       generation=excluded.generation, anki_note_id=excluded.anki_note_id,
                       retired=excluded.retired""",
                card.to_row(),
            )
        return card

    def get_card(self, card_id: str) -> Card | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return Card.from_row(row) if row else None

    def list_cards(self, ku_id: str | None = None, include_retired: bool = False) -> list[Card]:
        query = "SELECT * FROM cards"
        clauses, params = [], []
        if ku_id:
            clauses.append("ku_id = ?")
            params.append(ku_id)
        if not include_retired:
            clauses.append("retired = 0")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY generation, cognitive_level, created_at"
        with self.conn() as con:
            rows = con.execute(query, params).fetchall()
        return [Card.from_row(r) for r in rows]

    def cards_without_anki(self) -> list[Card]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM cards WHERE anki_note_id IS NULL AND retired = 0"
            ).fetchall()
        return [Card.from_row(r) for r in rows]

    def set_anki_note_id(self, card_id: str, note_id: int) -> None:
        with self.conn() as con:
            con.execute("UPDATE cards SET anki_note_id = ? WHERE id = ?", (note_id, card_id))

    def card_by_anki_note(self, note_id: int) -> Card | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM cards WHERE anki_note_id = ?", (note_id,)).fetchone()
        return Card.from_row(row) if row else None

    # -- reviews ----------------------------------------------------------
    def add_reviews(self, reviews: Iterable[Review]) -> int:
        added = 0
        with self.conn() as con:
            for rv in reviews:
                cur = con.execute(
                    """INSERT OR IGNORE INTO reviews
                       (card_id, anki_note_id, reviewed_at, rating, state, elapsed_days,
                        scheduled_days, duration_ms, stability, difficulty, retrievability, origin)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        rv.card_id, rv.anki_note_id, rv.reviewed_at, rv.rating, rv.state,
                        rv.elapsed_days, rv.scheduled_days, rv.duration_ms, rv.stability,
                        rv.difficulty, rv.retrievability, rv.origin,
                    ),
                )
                added += cur.rowcount
        return added

    def list_reviews(self, card_id: str | None = None) -> list[Review]:
        query = "SELECT * FROM reviews"
        params: tuple = ()
        if card_id:
            query += " WHERE card_id = ?"
            params = (card_id,)
        query += " ORDER BY reviewed_at"
        with self.conn() as con:
            rows = con.execute(query, params).fetchall()
        return [Review.from_row(r) for r in rows]

    def reviews_for_ku(self, ku_id: str) -> list[Review]:
        with self.conn() as con:
            rows = con.execute(
                """SELECT r.* FROM reviews r
                   JOIN cards c ON c.id = r.card_id
                   WHERE c.ku_id = ? ORDER BY r.reviewed_at""",
                (ku_id,),
            ).fetchall()
        return [Review.from_row(r) for r in rows]

    def review_count(self) -> int:
        with self.conn() as con:
            return con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

    # -- diagnoses --------------------------------------------------------
    def add_diagnosis(self, diagnosis: Diagnosis) -> None:
        with self.conn() as con:
            con.execute(
                """INSERT INTO diagnoses
                   (ku_id, error_type, confidence, evidence, engine, resolved, resolved_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    diagnosis.ku_id, diagnosis.error_type, diagnosis.confidence,
                    diagnosis.evidence, diagnosis.engine, diagnosis.resolved,
                    diagnosis.resolved_at, diagnosis.created_at,
                ),
            )

    def list_diagnoses(self, ku_id: str | None = None, unresolved_only: bool = False) -> list[Diagnosis]:
        query = "SELECT * FROM diagnoses"
        clauses, params = [], []
        if ku_id:
            clauses.append("ku_id = ?")
            params.append(ku_id)
        if unresolved_only:
            clauses.append("resolved = 0")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        with self.conn() as con:
            rows = con.execute(query, params).fetchall()
        return [Diagnosis.from_row(r) for r in rows]

    def resolve_diagnoses(self, ku_id: str) -> None:
        with self.conn() as con:
            con.execute(
                "UPDATE diagnoses SET resolved = 1, resolved_at = ? WHERE ku_id = ? AND resolved = 0",
                (now_iso(), ku_id),
            )

    # -- study plans ------------------------------------------------------
    def save_plan(self, plan: StudyPlan) -> None:
        with self.conn() as con:
            con.execute("DELETE FROM study_plans WHERE ku_id = ? AND status = 'OPEN'", (plan.ku_id,))
            con.execute(
                """INSERT INTO study_plans
                   (ku_id, what, where_, why, how_json, what_to_study, how_much, methods_json,
                    gemini_prompt, gap_score, next_level, error_types_json, priority, status,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.ku_id, plan.what, plan.where, plan.why,
                    json.dumps(plan.how, ensure_ascii=False), plan.what_to_study, plan.how_much,
                    json.dumps(plan.methods, ensure_ascii=False), plan.gemini_prompt,
                    plan.gap_score, plan.next_level,
                    json.dumps(plan.error_types, ensure_ascii=False), plan.priority,
                    plan.status, plan.created_at,
                ),
            )

    def list_plans(self, status: str = "OPEN") -> list[StudyPlan]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM study_plans WHERE status = ? ORDER BY priority DESC", (status,)
            ).fetchall()
        plans = []
        for r in rows:
            d = dict(r)
            plans.append(
                StudyPlan(
                    id=d["id"], ku_id=d["ku_id"], what=d["what"], where=d["where_"],
                    why=d["why"], how=json.loads(d["how_json"] or "[]"),
                    what_to_study=d.get("what_to_study") or "",
                    how_much=d.get("how_much") or "",
                    methods=json.loads(d.get("methods_json") or "[]"),
                    gemini_prompt=d.get("gemini_prompt") or "",
                    gap_score=d.get("gap_score") or 0.0,
                    next_level=d["next_level"],
                    error_types=json.loads(d["error_types_json"] or "[]"),
                    priority=d["priority"], status=d["status"], created_at=d["created_at"],
                )
            )
        return plans

    def complete_plan(self, plan_id: int) -> None:
        with self.conn() as con:
            con.execute("UPDATE study_plans SET status = 'DONE' WHERE id = ?", (plan_id,))

    # -- notion -----------------------------------------------------------
    def record_notion_export(self, ku_id: str, page_id: str, page_url: str = "") -> None:
        with self.conn() as con:
            con.execute(
                """INSERT INTO notion_exports (ku_id, page_id, page_url, exported_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(ku_id) DO UPDATE SET page_id=excluded.page_id,
                       page_url=excluded.page_url, exported_at=excluded.exported_at""",
                (ku_id, page_id, page_url, now_iso()),
            )

    def notion_exports(self) -> dict[str, dict]:
        with self.conn() as con:
            rows = con.execute("SELECT * FROM notion_exports").fetchall()
        return {r["ku_id"]: dict(r) for r in rows}

    # -- events -----------------------------------------------------------
    def log_event(self, kind: str, payload: dict) -> None:
        with self.conn() as con:
            con.execute(
                "INSERT INTO events (kind, payload_json, created_at) VALUES (?, ?, ?)",
                (kind, json.dumps(payload, ensure_ascii=False, default=str), now_iso()),
            )

    def recent_events(self, limit: int = 30) -> list[dict]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
            out.append(d)
        return out

    # -- misc -------------------------------------------------------------
    def stats(self) -> dict:
        with self.conn() as con:
            def one(sql: str, *p):
                return con.execute(sql, p).fetchone()[0]

            return {
                "sources": one("SELECT COUNT(*) FROM sources"),
                "knowledge_units": one("SELECT COUNT(*) FROM knowledge_units"),
                "mastered": one("SELECT COUNT(*) FROM knowledge_units WHERE status='MASTERED'"),
                "cards": one("SELECT COUNT(*) FROM cards WHERE retired=0"),
                "in_anki": one("SELECT COUNT(*) FROM cards WHERE anki_note_id IS NOT NULL"),
                "reviews": one("SELECT COUNT(*) FROM reviews"),
                "open_plans": one("SELECT COUNT(*) FROM study_plans WHERE status='OPEN'"),
                "notion_pages": one("SELECT COUNT(*) FROM notion_exports"),
                "weak": one("SELECT COUNT(*) FROM knowledge_units WHERE status IN ('WEAK','RELEARNING')"),
                "archived": one("SELECT COUNT(*) FROM knowledge_units WHERE status='ARCHIVED'"),
            }
