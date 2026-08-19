"""Flexible ingestion of Anki/FSRS review history without AnkiConnect.

Two paths:
  * ``import_csv``   — a CSV exported from Anki (File ▸ Export, or a DB query)
  * ``import_revlog``— rows already shaped like Anki's ``revlog`` table

Both map rows back to Second Brain cards through ``SecondBrainID`` (the field we
write into every note) or through the Anki note id we recorded when pushing.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from .models import Review
from .store import Store

# Accepted column aliases -> canonical name
ALIASES = {
    "card_id": {"secondbrainid", "second_brain_id", "sb_id", "card_id", "cardid"},
    "note_id": {"note_id", "noteid", "nid", "note"},
    "reviewed_at": {"reviewed_at", "date", "timestamp", "review_time", "id", "revlog_id"},
    "rating": {"rating", "ease", "button", "answer"},
    "scheduled_days": {"scheduled_days", "ivl", "interval", "new_interval"},
    "elapsed_days": {"elapsed_days", "lastivl", "last_interval", "last_ivl"},
    "duration_ms": {"duration_ms", "time", "taken_millis", "time_ms"},
    "state": {"state", "type"},
    "stability": {"stability", "s"},
    "difficulty": {"difficulty", "d"},
    "retrievability": {"retrievability", "r"},
}

_STATE_NAMES = {"0": "learning", "1": "learning", "2": "review", "3": "relearning"}


def _canonical(header: str) -> str | None:
    key = header.strip().lower().replace(" ", "_")
    for canon, names in ALIASES.items():
        if key in names:
            return canon
    return None


def _to_iso(value) -> str:
    text = str(value).strip()
    if not text:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if text.isdigit():
        num = int(text)
        if num > 10_000_000_000:  # epoch milliseconds (Anki revlog id)
            num //= 1000
        return datetime.fromtimestamp(num, tz=timezone.utc).isoformat(timespec="seconds")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")
    except ValueError:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _num(value, default=0.0):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def import_csv(store: Store, text: str, origin: str = "csv") -> dict:
    """Import review history from CSV text. Returns a small report."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)

    try:
        header = next(reader)
    except StopIteration:
        return {"parsed": 0, "matched": 0, "new": 0, "unmatched": [], "error": "empty file"}

    mapping = {i: _canonical(h) for i, h in enumerate(header)}
    if "rating" not in mapping.values():
        return {"parsed": 0, "matched": 0, "new": 0, "unmatched": [],
                "error": "no rating/ease column found"}

    by_sb_id = {c.id: c for c in store.list_cards(include_retired=True)}
    by_note = {c.anki_note_id: c for c in store.list_cards(include_retired=True) if c.anki_note_id}

    reviews: list[Review] = []
    unmatched: set[str] = set()
    parsed = 0

    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        parsed += 1
        data: dict[str, str] = {}
        for i, cell in enumerate(row):
            canon = mapping.get(i)
            if canon and canon not in data:
                data[canon] = cell

        card = by_sb_id.get((data.get("card_id") or "").strip())
        if not card:
            note_raw = (data.get("note_id") or "").strip()
            if note_raw.isdigit():
                card = by_note.get(int(note_raw))
        if not card:
            unmatched.add((data.get("card_id") or data.get("note_id") or "?").strip())
            continue

        rating = int(_num(data.get("rating"), 0))
        if rating <= 0:
            continue

        state_raw = str(data.get("state") or "").strip().lower()
        reviews.append(
            Review(
                card_id=card.id,
                anki_note_id=card.anki_note_id,
                reviewed_at=_to_iso(data.get("reviewed_at")),
                rating=min(4, rating),
                state=_STATE_NAMES.get(state_raw, state_raw),
                elapsed_days=_num(data.get("elapsed_days")),
                scheduled_days=_num(data.get("scheduled_days")),
                duration_ms=int(_num(data.get("duration_ms"))),
                stability=_num(data["stability"], None) if data.get("stability") else None,
                difficulty=_num(data["difficulty"], None) if data.get("difficulty") else None,
                retrievability=_num(data["retrievability"], None) if data.get("retrievability") else None,
                origin=origin,
            )
        )

    added = store.add_reviews(reviews)
    store.log_event("review_import", {"parsed": parsed, "matched": len(reviews), "new": added})
    return {
        "parsed": parsed,
        "matched": len(reviews),
        "new": added,
        "unmatched": sorted(unmatched)[:20],
        "error": None,
    }


CSV_TEMPLATE = (
    "SecondBrainID,reviewed_at,rating,scheduled_days,elapsed_days,duration_ms,stability\n"
    "card_xxxxxxxxxxxx,2026-08-01T20:14:00+00:00,1,0,7,18400,4.2\n"
)

ANKI_DB_QUERY = """-- Run in Anki ▸ Tools ▸ Debug Console (or a SQLite client on collection.anki2)
-- and export the result as CSV for the hub's importer.
SELECT
    n.flds       AS raw_fields,          -- SecondBrainID is the last field
    r.id         AS reviewed_at,         -- epoch ms
    r.ease       AS rating,
    r.ivl        AS scheduled_days,
    r.lastIvl    AS elapsed_days,
    r.time       AS duration_ms,
    r.type       AS state
FROM revlog r
JOIN cards c ON c.id = r.cid
JOIN notes n ON n.id = c.nid
WHERE n.tags LIKE '%SecondBrain%'
ORDER BY r.id;
"""


def fsrs_memory_state(store: Store, card_id: str) -> dict | None:
    """Recompute FSRS stability/difficulty locally from our own review log.

    Useful when the review history was imported from CSV without FSRS columns.
    """
    try:
        from fsrs import Card as FsrsCard, Rating, Scheduler
    except ImportError:
        return None

    reviews = store.list_reviews(card_id)
    if not reviews:
        return None

    scheduler = Scheduler()
    card = FsrsCard()
    rating_map = {1: Rating.Again, 2: Rating.Hard, 3: Rating.Good, 4: Rating.Easy}
    for rv in reviews:
        when = datetime.fromisoformat(rv.reviewed_at)
        if not when.tzinfo:
            when = when.replace(tzinfo=timezone.utc)
        card, _ = scheduler.review_card(card, rating_map.get(rv.rating, Rating.Good), when)

    retrievability = None
    try:
        retrievability = scheduler.get_card_retrievability(card)
    except Exception:
        pass
    return {
        "stability": getattr(card, "stability", None),
        "difficulty": getattr(card, "difficulty", None),
        "retrievability": retrievability,
        "due": str(getattr(card, "due", "")),
    }
