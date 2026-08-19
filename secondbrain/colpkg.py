"""Import an AnkiDroid export (.colpkg / .apkg / .anki2) straight from the phone.

This is the no-account fallback for the mobile loop: in AnkiDroid,
*Settings ▸ Advanced ▸ Export collection* (with scheduling) produces a file that
Chrome can upload here. We open the SQLite collection inside it and read the
review log, matching notes through their SecondBrainID field.

Modern Anki packages store the database as ``collection.anki21b`` compressed
with zstd; legacy ones store plain SQLite. Both are handled.
"""

from __future__ import annotations

import io
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .ankiweb import _store_rows
from .store import Store

SQLITE_MAGIC = b"SQLite format 3\x00"
CANDIDATES = ("collection.anki21b", "collection.anki21", "collection.anki2")


class CollectionFileError(RuntimeError):
    pass


def _decompress_zstd(raw: bytes) -> bytes:
    try:
        import zstandard
    except ImportError as exc:  # pragma: no cover
        raise CollectionFileError(
            "This export uses the new compressed format. Install `zstandard` "
            "(pip install zstandard), or in AnkiDroid choose the legacy .apkg export."
        ) from exc
    dctx = zstandard.ZstdDecompressor()
    with dctx.stream_reader(io.BytesIO(raw)) as reader:
        return reader.read()


def extract_collection(data: bytes) -> bytes:
    """Return raw SQLite bytes from an uploaded .colpkg/.apkg/.anki2 payload."""
    if data[: len(SQLITE_MAGIC)] == SQLITE_MAGIC:
        return data

    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise CollectionFileError(
            "Unrecognised file. Upload the .colpkg or .apkg produced by AnkiDroid."
        )

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        chosen = next((c for c in CANDIDATES if c in names), None)
        if not chosen:
            raise CollectionFileError(
                "No collection database inside the package (expected collection.anki21b/anki21/anki2)."
            )
        raw = zf.read(chosen)

    if raw[: len(SQLITE_MAGIC)] != SQLITE_MAGIC:
        raw = _decompress_zstd(raw)
    if raw[: len(SQLITE_MAGIC)] != SQLITE_MAGIC:
        raise CollectionFileError("Could not read the collection database inside the package.")
    return raw


def import_collection(store: Store, data: bytes, origin: str = "ankidroid") -> dict:
    """Read the review log out of an AnkiDroid export and store it."""
    raw = extract_collection(data)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "collection.anki2"
        path.write_bytes(raw)
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            note_fields = {
                nid: flds.split("\x1f")
                for nid, flds in con.execute(
                    "SELECT id, flds FROM notes WHERE tags LIKE '%SecondBrain%'"
                )
            }
            if not note_fields:  # older exports may not carry our tag on every note
                note_fields = {
                    nid: flds.split("\x1f") for nid, flds in con.execute("SELECT id, flds FROM notes")
                }
            rows = con.execute(
                """SELECT r.id, r.cid, r.ease, r.ivl, r.lastIvl, r.time, r.type, c.nid, c.data
                   FROM revlog r JOIN cards c ON c.id = r.cid
                   ORDER BY r.id"""
            ).fetchall()
            total_reviews = con.execute("SELECT count() FROM revlog").fetchone()[0]
            total_notes = con.execute("SELECT count() FROM notes").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise CollectionFileError(f"Could not read the collection: {exc}") from exc
        finally:
            con.close()

    new = _store_rows(store, rows, note_fields, origin=origin)
    matched = sum(1 for r in rows if r[2])
    return {
        "notes_in_file": total_notes,
        "reviews_in_file": total_reviews,
        "rows_considered": matched,
        "new_reviews": new,
    }
