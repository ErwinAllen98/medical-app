"""Layer 3: automatic transfer to Anki.

Preferred path is AnkiConnect (no copy-paste). When Anki is not reachable — for
example when the hub runs on a server — we fall back to a .apkg file built with
genanki, which keeps the same note type, tags and knowledge-unit traceability.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from .config import EXPORT_DIR, Settings
from .models import Card, Review
from .store import Store

NOTE_FIELDS = ["Question", "Answer", "Explanation", "Source", "KnowledgeUnit", "SecondBrainID"]

CARD_TEMPLATE_FRONT = "{{Question}}"
CARD_TEMPLATE_BACK = """{{FrontSide}}
<hr id=answer>
<div class="answer">{{Answer}}</div>
<div class="explanation">{{Explanation}}</div>
<div class="source">{{Source}}</div>
"""
CARD_CSS = """
.card { font-family: -apple-system, Segoe UI, Roboto, sans-serif; font-size: 20px;
        text-align: left; color: #1f2933; background: #fbfaf7; padding: 16px; }
.answer { font-weight: 600; margin-top: 8px; }
.explanation { font-size: 16px; color: #4b5563; margin-top: 12px; }
.source { font-size: 13px; color: #8a8f98; margin-top: 16px; font-style: italic; }
"""


class AnkiError(RuntimeError):
    pass


@dataclass
class SyncReport:
    added: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = None  # type: ignore[assignment]
    apkg_path: str | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_fields(store: Store, card: Card) -> dict[str, str]:
    ku = store.get_ku(card.ku_id)
    source_title = store.source_titles().get(ku.source_id, "") if ku else ""
    source = ku.source_locator(source_title) if ku else ""

    question = html.escape(card.question)
    if card.card_type == "MCQ" and card.options:
        opts = "".join(
            f"<li>{html.escape(o)}</li>" for o in card.options
        )
        question += f"<ol type='A' class='options'>{opts}</ol>"

    answer = html.escape(card.answer)
    if card.card_type == "MCQ" and card.correct_option is not None and card.options:
        letter = chr(ord("A") + card.correct_option)
        answer = f"{letter}. {answer}"

    return {
        "Question": question,
        "Answer": answer,
        "Explanation": html.escape(card.explanation or ""),
        "Source": html.escape(source),
        "KnowledgeUnit": html.escape(ku.statement if ku else ""),
        "SecondBrainID": card.id,
    }


# ---------------------------------------------------------------------------
# AnkiConnect
# ---------------------------------------------------------------------------

class AnkiConnect:
    def __init__(self, url: str | None = None, timeout: int = 20) -> None:
        settings = Settings.load()
        self.url = url or settings.anki_connect_url
        self.timeout = timeout

    def invoke(self, action: str, **params):
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise AnkiError("requests is not installed.") from exc
        try:
            resp = requests.post(
                self.url,
                json={"action": action, "version": 6, "params": params},
                timeout=self.timeout,
            )
        except Exception as exc:
            raise AnkiError(
                f"Cannot reach AnkiConnect at {self.url}. Is Anki running with the AnkiConnect add-on?"
            ) from exc
        if resp.status_code >= 400:
            raise AnkiError(f"AnkiConnect HTTP {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()
        if payload.get("error"):
            raise AnkiError(str(payload["error"]))
        return payload.get("result")

    # -- health --------------------------------------------------------
    def available(self) -> bool:
        try:
            self.invoke("version")
            return True
        except AnkiError:
            return False

    # -- setup ---------------------------------------------------------
    def ensure_deck(self, deck: str) -> None:
        self.invoke("createDeck", deck=deck)

    def ensure_model(self, model: str) -> None:
        if model in (self.invoke("modelNames") or []):
            return
        self.invoke(
            "createModel",
            modelName=model,
            inOrderFields=NOTE_FIELDS,
            css=CARD_CSS,
            cardTemplates=[
                {"Name": "Recall", "Front": CARD_TEMPLATE_FRONT, "Back": CARD_TEMPLATE_BACK}
            ],
        )

    # -- notes ---------------------------------------------------------
    def add_note(self, deck: str, model: str, fields: dict, tags: list[str]) -> int:
        return self.invoke(
            "addNote",
            note={
                "deckName": deck,
                "modelName": model,
                "fields": fields,
                "tags": tags,
                "options": {"allowDuplicate": False, "duplicateScope": "deck"},
            },
        )

    def find_notes(self, query: str) -> list[int]:
        return self.invoke("findNotes", query=query) or []

    def notes_info(self, note_ids: list[int]) -> list[dict]:
        return self.invoke("notesInfo", notes=note_ids) or []

    def cards_of_notes(self, note_ids: list[int]) -> list[int]:
        if not note_ids:
            return []
        query = " OR ".join(f"nid:{nid}" for nid in note_ids)
        return self.invoke("findCards", query=query) or []

    def cards_info(self, card_ids: list[int]) -> list[dict]:
        if not card_ids:
            return []
        return self.invoke("cardsInfo", cards=card_ids) or []

    def reviews_of_cards(self, card_ids: list[int]) -> dict:
        if not card_ids:
            return {}
        return self.invoke("getReviewsOfCards", cards=[str(c) for c in card_ids]) or {}


# ---------------------------------------------------------------------------
# Push: Second Brain -> Anki
# ---------------------------------------------------------------------------

def push_cards(store: Store, cards: list[Card] | None = None, deck: str | None = None) -> SyncReport:
    settings = Settings.load()
    deck = deck or settings.anki_deck
    client = AnkiConnect()
    report = SyncReport()

    if not client.available():
        raise AnkiError(
            f"AnkiConnect is not reachable at {client.url}. "
            "Open Anki with the AnkiConnect add-on, or use the .apkg export instead."
        )

    client.ensure_deck(deck)
    client.ensure_model(settings.anki_model)

    for card in cards if cards is not None else store.cards_without_anki():
        if card.anki_note_id:
            report.skipped += 1
            continue
        try:
            note_id = client.add_note(
                deck, settings.anki_model, render_fields(store, card), card.tags
            )
            if note_id:
                store.set_anki_note_id(card.id, int(note_id))
                report.added += 1
            else:
                report.skipped += 1
        except AnkiError as exc:
            msg = str(exc)
            if "duplicate" in msg.lower():
                report.skipped += 1
            else:
                report.failed += 1
                report.errors.append(f"{card.id}: {msg}")

    store.log_event("anki_push", {"added": report.added, "skipped": report.skipped,
                                  "failed": report.failed, "deck": deck})
    return report


def export_apkg(store: Store, cards: list[Card] | None = None, deck: str | None = None,
                path: str | Path | None = None) -> str:
    """Offline fallback: build a .apkg the doctor imports once."""
    try:
        import genanki
    except ImportError as exc:  # pragma: no cover
        raise AnkiError("genanki is not installed (pip install genanki).") from exc

    settings = Settings.load()
    deck_name = deck or settings.anki_deck
    cards = cards if cards is not None else store.list_cards()
    if not cards:
        raise AnkiError("There is nothing to export yet.")

    model = genanki.Model(
        1607392319,
        settings.anki_model,
        fields=[{"name": f} for f in NOTE_FIELDS],
        templates=[{"name": "Recall", "qfmt": CARD_TEMPLATE_FRONT, "afmt": CARD_TEMPLATE_BACK}],
        css=CARD_CSS,
    )
    anki_deck = genanki.Deck(abs(hash(deck_name)) % (10**10), deck_name)
    for card in cards:
        fields = render_fields(store, card)
        anki_deck.add_note(
            genanki.Note(model=model, fields=[fields[f] for f in NOTE_FIELDS], tags=card.tags)
        )

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(path or EXPORT_DIR / "second_brain.apkg")
    genanki.Package(anki_deck).write_to_file(out)
    store.log_event("apkg_export", {"cards": len(cards), "path": str(out)})
    return str(out)


# ---------------------------------------------------------------------------
# Pull: Anki/FSRS review history -> Second Brain
# ---------------------------------------------------------------------------

_RATING_STATE = {0: "new", 1: "learning", 2: "review", 3: "relearning"}


def pull_reviews(store: Store) -> int:
    """Fetch the review log for every card we pushed, and store it."""
    client = AnkiConnect()
    if not client.available():
        raise AnkiError("AnkiConnect is not reachable — cannot pull review history.")

    tracked = [c for c in store.list_cards(include_retired=True) if c.anki_note_id]
    if not tracked:
        return 0
    by_note = {c.anki_note_id: c for c in tracked}

    card_ids = client.cards_of_notes(list(by_note))
    info = {int(ci["cardId"]): ci for ci in client.cards_info(card_ids)}
    logs = client.reviews_of_cards(card_ids)

    new_reviews: list[Review] = []
    for anki_card_id, entries in (logs or {}).items():
        meta = info.get(int(anki_card_id), {})
        note_id = int(meta.get("note", 0))
        card = by_note.get(note_id)
        if not card:
            continue
        for entry in entries or []:
            reviewed_at = _ms_to_iso(entry.get("id"))
            ease = int(entry.get("ease") or 0)
            if ease <= 0:
                continue  # manual reschedule
            new_reviews.append(
                Review(
                    card_id=card.id,
                    anki_note_id=note_id,
                    reviewed_at=reviewed_at,
                    rating=min(4, ease),
                    state=_RATING_STATE.get(int(entry.get("type") or 0), ""),
                    elapsed_days=float(entry.get("lastInterval") or 0),
                    scheduled_days=float(entry.get("interval") or 0),
                    duration_ms=int(entry.get("time") or 0),
                    origin="ankiconnect",
                )
            )

    _attach_fsrs_memory(info, by_note, new_reviews)
    added = store.add_reviews(new_reviews)
    store.log_event("anki_pull", {"fetched": len(new_reviews), "new": added})
    return added


def _attach_fsrs_memory(info: dict, by_note: dict, reviews: list[Review]) -> None:
    """Copy FSRS stability/difficulty from cardsInfo onto the latest review of each card."""
    latest: dict[str, Review] = {}
    for rv in reviews:
        cur = latest.get(rv.card_id)
        if not cur or rv.reviewed_at > cur.reviewed_at:
            latest[rv.card_id] = rv

    for meta in info.values():
        card = by_note.get(int(meta.get("note", 0)))
        if not card or card.id not in latest:
            continue
        data = meta.get("fsrs") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {}
        memory = data.get("memoryState") or data
        rv = latest[card.id]
        rv.stability = _as_float(memory.get("stability") or memory.get("s"))
        rv.difficulty = _as_float(memory.get("difficulty") or memory.get("d"))
        rv.retrievability = _as_float(data.get("retrievability"))


def _as_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _ms_to_iso(ms) -> str:
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
