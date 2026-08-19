"""Layer 12: Notion as the long-term repository of MASTERED knowledge.

Only mastered knowledge units are written, and each page records not just what
is known, but the weakness history and how it was repaired — that history is
part of the Second Brain.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import EXPORT_DIR, Settings
from .mastery import evaluate
from .store import Store

NOTION_VERSION = "2022-06-28"


class NotionError(RuntimeError):
    pass


@dataclass
class KnowledgePage:
    ku_id: str
    title: str
    properties: dict
    markdown: str


def _weakness_history(store: Store, ku_id: str) -> tuple[str, str]:
    """(what I struggled with, how it was resolved)"""
    diagnoses = store.list_diagnoses(ku_id)
    if not diagnoses:
        return "No recorded failure — learned cleanly.", ""
    seen: dict[str, str] = {}
    for d in diagnoses:
        seen.setdefault(d.error_type, d.evidence or "")
    struggled = "; ".join(
        f"{err}" + (f" ({ev[:160]})" if ev else "") for err, ev in seen.items()
    )
    plans = store.list_plans(status="DONE") + store.list_plans(status="OPEN")
    steps = [p for p in plans if p.ku_id == ku_id]
    resolved = ""
    if steps:
        plan = steps[0]
        resolved = f"Targeted re-study of {plan.where.splitlines()[0]}; then re-tested at level {plan.next_level}."
    reviews = store.reviews_for_ku(ku_id)
    if reviews:
        fails = sum(1 for r in reviews if r.failed)
        resolved += f" Repaired after {fails} recorded failure(s) across {len(reviews)} reviews."
    return struggled, resolved.strip()


def build_page(store: Store, ku_id: str) -> KnowledgePage | None:
    ku = store.get_ku(ku_id)
    if not ku:
        return None
    source_title = store.source_titles().get(ku.source_id, ku.source_id)
    cards = store.list_cards(ku_id, include_retired=True)
    report = evaluate(store, ku_id)
    struggled, resolved = _weakness_history(store, ku_id)
    related = [store.get_ku(r) for r in store.related_kus(ku_id)]
    related_labels = [r.label for r in related if r]
    anki_tags = sorted({t for c in cards for t in c.tags if t.startswith(("KU::", "topic::"))})
    anki_ids = [str(c.anki_note_id) for c in cards if c.anki_note_id]

    properties = {
        "Topic": ku.topic,
        "Subtopic": ku.subtopic,
        "Status": ku.status,
        "Mastered": ku.mastered_at or "",
        "Source": source_title,
        "Source location": ku.source_locator(source_title),
        "Importance": ku.importance,
        "Mastery score": report.score if report else 0,
        "Anki tags": ", ".join(anki_tags),
        "Anki note IDs": ", ".join(anki_ids),
    }

    md = [
        f"# {ku.label}",
        "",
        "## Core knowledge",
        ku.statement or "—",
        "",
        "## Clinical significance",
        ku.clinical_significance or "—",
    ]
    if ku.thresholds:
        md += ["", "## Important thresholds", ku.thresholds]
    if ku.exceptions:
        md += ["", "## Exceptions", ku.exceptions]
    if ku.algorithm:
        md += ["", "## Clinical algorithm", ku.algorithm]
    if ku.common_mistakes:
        md += ["", "## Common mistakes", ku.common_mistakes]
    md += [
        "",
        "## My historical weakness",
        struggled,
        "",
        "## How it was resolved",
        resolved or "—",
        "",
        "## Source",
        f"{source_title} · {ku.chapter} · {ku.section} · {ku.location}".strip(" ·"),
        "",
        "## Related knowledge units",
        ", ".join(related_labels) or "—",
        "",
        "## Anki",
        f"Tags: {', '.join(anki_tags) or '—'}  \nNote IDs: {', '.join(anki_ids) or '—'}",
        "",
        f"*Date mastered: {ku.mastered_at or '—'}*",
    ]

    return KnowledgePage(ku_id=ku.id, title=ku.label, properties=properties, markdown="\n".join(md))


# ---------------------------------------------------------------------------
# Notion API
# ---------------------------------------------------------------------------

def _rich(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text[:2000]}}]


def _blocks_from_markdown(md: str) -> list[dict]:
    blocks: list[dict] = []
    for line in md.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("# "):
            continue  # the page title carries this
        if line.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                           "heading_2": {"rich_text": _rich(line[3:])}})
        elif line.startswith("*") and line.endswith("*"):
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": _rich(line.strip("*"))}})
        else:
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": _rich(line)}})
    return blocks[:95]


def _notion_properties(page: KnowledgePage, schema: dict) -> dict:
    """Map our properties onto whatever the target database actually has."""
    out: dict = {}
    for name, definition in schema.items():
        ptype = definition.get("type")
        if ptype == "title":
            out[name] = {"title": _rich(page.title)}
            continue
        value = page.properties.get(name)
        if value in (None, ""):
            continue
        if ptype == "rich_text":
            out[name] = {"rich_text": _rich(str(value))}
        elif ptype == "number":
            try:
                out[name] = {"number": float(value)}
            except (TypeError, ValueError):
                pass
        elif ptype == "select":
            out[name] = {"select": {"name": str(value)[:100]}}
        elif ptype == "multi_select":
            items = [v.strip()[:100] for v in str(value).split(",") if v.strip()]
            out[name] = {"multi_select": [{"name": v} for v in items[:20]]}
        elif ptype == "url":
            out[name] = {"url": str(value)}
    return out


class NotionClient:
    def __init__(self, token: str | None = None, database_id: str | None = None) -> None:
        settings = Settings.load()
        self.token = token or settings.notion_token
        self.database_id = database_id or settings.notion_database_id

    @property
    def configured(self) -> bool:
        return bool(self.token and self.database_id)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, payload: dict | None = None) -> dict:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise NotionError("requests is not installed.") from exc
        resp = requests.request(method, url, headers=self._headers(), json=payload, timeout=60)
        if resp.status_code >= 400:
            raise NotionError(f"Notion API {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def database_schema(self) -> dict:
        data = self._request("GET", f"https://api.notion.com/v1/databases/{self.database_id}")
        return data.get("properties", {})

    def create_page(self, page: KnowledgePage, schema: dict | None = None) -> dict:
        schema = schema if schema is not None else self.database_schema()
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": _notion_properties(page, schema),
            "children": _blocks_from_markdown(page.markdown),
        }
        return self._request("POST", "https://api.notion.com/v1/pages", payload)


def push_mastered(store: Store, ku_ids: list[str] | None = None) -> dict:
    """Send mastered knowledge units to Notion; returns a report."""
    client = NotionClient()
    if not client.configured:
        raise NotionError("NOTION_TOKEN / NOTION_DATABASE_ID are not configured.")

    already = store.notion_exports()
    targets = ku_ids or [ku.id for ku in store.list_kus(status="MASTERED")]
    schema = client.database_schema()
    sent, skipped, errors = 0, 0, []

    for ku_id in targets:
        if ku_id in already:
            skipped += 1
            continue
        page = build_page(store, ku_id)
        if not page:
            continue
        try:
            result = client.create_page(page, schema)
            store.record_notion_export(ku_id, result.get("id", ""), result.get("url", ""))
            sent += 1
        except NotionError as exc:
            errors.append(f"{ku_id}: {exc}")

    store.log_event("notion_push", {"sent": sent, "skipped": skipped, "errors": len(errors)})
    return {"sent": sent, "skipped": skipped, "errors": errors}


def export_markdown(store: Store, ku_ids: list[str] | None = None) -> str:
    """Offline fallback: one Markdown file ready to paste/import into Notion."""
    targets = ku_ids or [ku.id for ku in store.list_kus(status="MASTERED")]
    parts = []
    for ku_id in targets:
        page = build_page(store, ku_id)
        if page:
            parts.append(page.markdown)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPORT_DIR / "notion_mastered.md"
    out.write_text("\n\n---\n\n".join(parts) or "# Nothing mastered yet", encoding="utf-8")
    return str(out)
