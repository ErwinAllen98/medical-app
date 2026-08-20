"""AnkiWeb sync bridge — the phone-first path into Anki.

AnkiConnect needs desktop Anki on the same machine, which is useless from a
phone. This module instead drives a *real* Anki collection with the official
``anki`` library, syncs it with AnkiWeb, and lets AnkiDroid pick the cards up
with its normal sync button:

    hub  ──push──▶  local collection  ──sync──▶  AnkiWeb  ──▶  AnkiDroid
    hub  ◀──pull──  local collection  ◀──sync──  AnkiWeb  ◀──  AnkiDroid

Safety: a *full upload* would overwrite the collection stored on AnkiWeb, so it
never happens implicitly — the default resolution for a full-sync request is to
download the server's collection first.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import DATA_DIR, Settings
from .models import Card, Review
from .store import Store

COLLECTION_DIR = DATA_DIR / "ankiweb"
COLLECTION_PATH = COLLECTION_DIR / "collection.anki2"

NOTE_FIELDS = ["Question", "Answer", "Explanation", "Source", "KnowledgeUnit", "SecondBrainID"]

_QFMT = "{{Question}}"
_AFMT = """{{FrontSide}}
<hr id=answer>
<div class="answer">{{Answer}}</div>
<div class="explanation">{{Explanation}}</div>
<div class="source">{{Source}}</div>"""
_CSS = """.card { font-family: -apple-system, Roboto, sans-serif; font-size: 20px;
  text-align: left; color: #1f2933; background: #fbfaf7; padding: 14px; }
.answer { font-weight: 600; margin-top: 8px; }
.explanation { font-size: 16px; color: #4b5563; margin-top: 10px; }
.source { font-size: 13px; color: #8a8f98; margin-top: 14px; font-style: italic; }"""

# revlog.ease → our rating (1 Again … 4 Easy); 0 means "manual reschedule"
_REVLOG_TYPES = {0: "learning", 1: "review", 2: "relearning", 3: "filtered", 4: "manual", 5: "rescheduled"}


class AnkiWebError(RuntimeError):
    pass


@dataclass
class SyncResult:
    status: str = ""
    pushed: int = 0
    pulled: int = 0
    server_message: str = ""
    needs_choice: bool = False
    notes: list[str] = field(default_factory=list)


def library_available() -> bool:
    try:
        import anki  # noqa: F401

        return True
    except ImportError:
        return False


def _require_anki():
    try:
        from anki.collection import Collection

        return Collection
    except ImportError as exc:  # pragma: no cover
        raise AnkiWebError(
            "The `anki` package is not installed. Add it with `pip install anki`."
        ) from exc


class AnkiWebBridge:
    """Owns the local mirror collection and talks to AnkiWeb."""

    def __init__(self, settings: Settings | None = None, path: Path | None = None) -> None:
        self.settings = settings or Settings.load()
        self.path = Path(path or COLLECTION_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- basics -----------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.settings.ankiweb_username and self.settings.ankiweb_password)

    @property
    def collection_exists(self) -> bool:
        return self.path.exists()

    @contextmanager
    def open(self) -> Iterator["object"]:
        Collection = _require_anki()
        col = Collection(str(self.path))
        try:
            yield col
        finally:
            try:
                col.close()
            except Exception:
                pass

    def local_stats(self) -> dict:
        if not self.collection_exists:
            return {"notes": 0, "cards": 0, "reviews": 0, "second_brain_notes": 0, "decks": []}
        with self.open() as col:
            return {
                "notes": col.note_count(),
                "cards": col.card_count(),
                "reviews": col.db.scalar("select count() from revlog") or 0,
                "second_brain_notes": len(col.find_notes("tag:SecondBrain")),
                "decks": sorted(d.name for d in col.decks.all_names_and_ids()),
            }

    # -- authentication ---------------------------------------------------
    def _auth(self, col):
        if not self.configured:
            raise AnkiWebError(
                "ANKIWEB_USERNAME / ANKIWEB_PASSWORD are not configured in secrets."
            )
        try:
            return col.sync_login(
                self.settings.ankiweb_username,
                self.settings.ankiweb_password,
                self.settings.ankiweb_endpoint or None,
            )
        except Exception as exc:
            raise AnkiWebError(f"AnkiWeb login failed: {exc}") from exc

    # -- sync -------------------------------------------------------------
    def sync(self, allow_full_upload: bool = False) -> SyncResult:
        """Normal sync; resolves a full-sync request by DOWNLOADING by default."""
        import anki.sync_pb2 as sync_pb

        Required = sync_pb.SyncCollectionResponse.ChangesRequired
        result = SyncResult()

        with self.open() as col:
            auth = self._auth(col)
            try:
                out = col.sync_collection(auth, False)
            except Exception as exc:
                raise AnkiWebError(f"Sync failed: {exc}") from exc

            result.server_message = out.server_message or ""
            required = out.required

            if required == Required.NO_CHANGES:
                result.status = "up to date"
                return result
            if required == Required.NORMAL_SYNC:
                result.status = "synced"
                return result

            # A full sync is required (usually the very first time).
            upload = required == Required.FULL_UPLOAD
            if required == Required.FULL_SYNC:
                upload = False  # never guess in favour of overwriting the server
            if upload and not allow_full_upload:
                result.status = "full upload required"
                result.needs_choice = True
                result.notes.append(
                    "AnkiWeb asked for a FULL UPLOAD, which would replace the collection stored "
                    "on AnkiWeb. Confirm explicitly before doing that."
                )
                return result

            server_usn = out.server_media_usn if upload else None
            col.close_for_full_sync()
            try:
                col.full_upload_or_download(auth=auth, server_usn=server_usn, upload=upload)
            except Exception as exc:
                raise AnkiWebError(f"Full {'upload' if upload else 'download'} failed: {exc}") from exc
            result.status = "full upload" if upload else "full download"
            result.notes.append(
                "Uploaded the local collection to AnkiWeb."
                if upload
                else "Downloaded your AnkiWeb collection into the hub's local mirror."
            )
        return result

    # -- push -------------------------------------------------------------
    def _ensure_notetype(self, col):
        mm = col.models
        model = mm.by_name(self.settings.anki_model)
        if model:
            existing = set(mm.field_names(model))
            missing = [f for f in NOTE_FIELDS if f not in existing]
            for name in missing:
                mm.add_field(model, mm.new_field(name))
            if missing:
                mm.save(model)
            return mm.by_name(self.settings.anki_model)

        model = mm.new(self.settings.anki_model)
        for name in NOTE_FIELDS:
            mm.add_field(model, mm.new_field(name))
        template = mm.new_template("Recall")
        template["qfmt"] = _QFMT
        template["afmt"] = _AFMT
        mm.add_template(model, template)
        model["css"] = _CSS
        mm.add_dict(model)
        return mm.by_name(self.settings.anki_model)

    def push(self, store: Store, cards: list[Card] | None = None, deck: str | None = None) -> int:
        """Write pending cards into the local collection (sync sends them on)."""
        from .anki import render_fields

        deck_name = deck or self.settings.anki_deck
        pending = cards if cards is not None else store.cards_without_anki()
        if not pending:
            return 0

        added = 0
        with self.open() as col:
            model = self._ensure_notetype(col)
            deck_id = col.decks.id(deck_name)
            for card in pending:
                found = col.find_notes(f'"SecondBrainID:{card.id}"')
                if found:
                    store.set_anki_note_id(card.id, int(found[0]))
                    continue
                fields = render_fields(store, card)
                note = col.new_note(model)
                for name in NOTE_FIELDS:
                    note[name] = fields.get(name, "")
                note.tags = list(card.tags)
                col.add_note(note, deck_id)
                store.set_anki_note_id(card.id, int(note.id))
                added += 1
        store.log_event("ankiweb_push", {"added": added, "deck": deck_name})
        return added

    # -- pull -------------------------------------------------------------
    def pull(self, store: Store) -> int:
        """Read the review log out of the local mirror and store it."""
        if not self.collection_exists:
            return 0
        with self.open() as col:
            rows = col.db.all(
                """SELECT r.id, r.cid, r.ease, r.ivl, r.lastIvl, r.time, r.type, c.nid, c.data
                   FROM revlog r JOIN cards c ON c.id = r.cid
                   WHERE c.nid IN (SELECT id FROM notes WHERE tags LIKE '%SecondBrain%')
                   ORDER BY r.id"""
            )
            note_fields = {
                nid: flds.split("\x1f")
                for nid, flds in col.db.all(
                    "SELECT id, flds FROM notes WHERE tags LIKE '%SecondBrain%'"
                )
            }
        return _store_rows(store, rows, note_fields, origin="ankiweb")

    # -- convenience ------------------------------------------------------
    def round_trip(self, store: Store, push: bool = True, pull: bool = True,
                   allow_full_upload: bool = False) -> SyncResult:
        """Pull server state → push new cards → sync up → import review history."""
        result = self.sync(allow_full_upload=allow_full_upload)
        if result.needs_choice:
            return result

        if push:
            result.pushed = self.push(store)
            if result.pushed:
                second = self.sync(allow_full_upload=allow_full_upload)
                result.status = f"{result.status} → {second.status}"
                result.notes.extend(second.notes)
        if pull:
            result.pulled = self.pull(store)

        store.log_event("ankiweb_sync", {"status": result.status, "pushed": result.pushed,
                                         "pulled": result.pulled})
        return result

    def export_apkg(self, out_path: str | Path | None = None, deck: str | None = None,
                    with_scheduling: bool = True) -> str:
        """Export the Second Brain deck from the local mirror (AnkiDroid-importable)."""
        from anki.collection import DeckIdLimit
        from anki.decks import DeckId
        from anki.import_export_pb2 import ExportAnkiPackageOptions

        from .config import EXPORT_DIR

        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        out = Path(out_path or EXPORT_DIR / "second_brain_mobile.apkg")
        deck_name = deck or self.settings.anki_deck
        with self.open() as col:
            deck_id = col.decks.id_for_name(deck_name)
            options = ExportAnkiPackageOptions(
                with_scheduling=with_scheduling,
                with_deck_configs=False,
                with_media=False,
                legacy=True,
            )
            col.export_anki_package(
                out_path=str(out),
                options=options,
                limit=DeckIdLimit(DeckId(deck_id)) if deck_id else None,
            )
        return str(out)


# ---------------------------------------------------------------------------
# Shared revlog → Review mapping (also used by the .colpkg importer)
# ---------------------------------------------------------------------------

_SB_ID_PREFIX = "card_"


def sb_id_from_fields(fields: list[str]) -> str | None:
    for value in reversed(fields):
        text = (value or "").strip()
        if text.startswith(_SB_ID_PREFIX) and len(text) <= 32 and " " not in text:
            return text
    return None


def _fsrs_from_data(raw: str | None) -> tuple[float | None, float | None]:
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None, None
    stability = data.get("s")
    difficulty = data.get("d")
    try:
        stability = float(stability) if stability is not None else None
    except (TypeError, ValueError):
        stability = None
    try:
        difficulty = float(difficulty) if difficulty is not None else None
    except (TypeError, ValueError):
        difficulty = None
    return stability, difficulty


def _store_rows(store: Store, rows, note_fields: dict, origin: str) -> int:
    """rows: (revlog_id, cid, ease, ivl, lastIvl, time_ms, type, nid, card_data)"""
    known = {c.id for c in store.list_cards(include_retired=True)}
    reviews: list[Review] = []

    for rid, cid, ease, ivl, last_ivl, time_ms, rtype, nid, card_data in rows:
        if not ease:  # manual reschedule / set due date
            continue
        sb_id = sb_id_from_fields(note_fields.get(nid, []))
        if not sb_id or sb_id not in known:
            continue
        stability, difficulty = _fsrs_from_data(card_data)
        reviews.append(
            Review(
                card_id=sb_id,
                anki_note_id=int(nid),
                reviewed_at=datetime.fromtimestamp(int(rid) / 1000, tz=timezone.utc).isoformat(
                    timespec="seconds"
                ),
                rating=min(4, int(ease)),
                state=_REVLOG_TYPES.get(int(rtype or 0), ""),
                elapsed_days=float(abs(last_ivl or 0)) if (last_ivl or 0) > 0 else 0.0,
                scheduled_days=float(ivl or 0) if (ivl or 0) > 0 else 0.0,
                duration_ms=int(time_ms or 0),
                stability=stability,
                difficulty=difficulty,
                origin=origin,
            )
        )

    added = store.add_reviews(reviews)
    store.log_event("review_sync", {"origin": origin, "seen": len(reviews), "new": added})
    return added
