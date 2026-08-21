"""Analyse a pasted chat against the doctor's NotebookLM sources.

The doctor pastes a conversation (NotebookLM itself, Telegram, a case
discussion, a study chat). We write a short prompt they paste into
NotebookLM. NotebookLM, grounded in *their* sources, returns:

  - each claim checked against the source (supported / unsupported /
    unclear / contradicted)
  - knowledge gaps the chat revealed
  - flashcards that close those gaps

No Anki, no jargon — the UI talks in plain language; this module only
parses, stores, and hands back structured findings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .models import Card, Diagnosis, KnowledgeUnit, Source
from .simple import KIND_TO_ERROR, WeakSpot, _ERROR_PLAIN
from .store import Store

# Keep the prompt pasteable from a phone clipboard.
CHAT_MAX_CHARS = 8000

VERDICTS = ("supported", "unsupported", "unclear", "contradicted")

VERDICT_LABEL: dict[str, str] = {
    "supported": "Supported by the source",
    "unsupported": "Not in the source",
    "unclear": "Unclear",
    "contradicted": "Contradicted by the source",
}

_VERDICT_ALIASES: dict[str, str] = {
    "supported": "supported",
    "true": "supported",
    "yes": "supported",
    "ok": "supported",
    "correct": "supported",
    "confirmed": "supported",
    "تایید": "supported",
    "تأیید": "supported",
    "unsupported": "unsupported",
    "false": "unsupported",
    "no": "unsupported",
    "missing": "unsupported",
    "not_in_source": "unsupported",
    "not in source": "unsupported",
    "absent": "unsupported",
    "بدون منبع": "unsupported",
    "unclear": "unclear",
    "unknown": "unclear",
    "uncertain": "unclear",
    "ambiguous": "unclear",
    "نامشخص": "unclear",
    "مبهم": "unclear",
    "contradicted": "contradicted",
    "contradicts": "contradicted",
    "contradiction": "contradicted",
    "conflict": "contradicted",
    "conflicting": "contradicted",
    "wrong": "contradicted",
    "رد": "contradicted",
    "نقض": "contradicted",
    "خلاف": "contradicted",
}

_KIND_ALIASES: dict[str, str] = {
    "threshold": "number",
    "numeric": "number",
    "dose": "number",
    "diff": "difference",
    "versus": "difference",
    "vs": "difference",
    "management": "decision",
    "next_step": "decision",
    "contra": "exception",
    "contraindication": "exception",
}

_ERROR_TO_KIND: dict[str, str] = {err: kind for kind, err in KIND_TO_ERROR.items()}


# ---------------------------------------------------------------------------
# clipping
# ---------------------------------------------------------------------------

def clip_chat(text: str, limit: int = CHAT_MAX_CHARS) -> tuple[str, bool]:
    """Return (text, truncated?). Keeps the head and the tail when clipping."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text, False
    keep = max(200, (limit - 20) // 2)
    return text[:keep] + "\n…\n" + text[-keep:], True


# ---------------------------------------------------------------------------
# prompt — pasted into NotebookLM
# ---------------------------------------------------------------------------

def analysis_prompt(chat: str, focus: str = "") -> str:
    """Short prompt the doctor pastes into NotebookLM with the chat.

    NotebookLM must use only the sources already loaded in that notebook.
    """
    body, truncated = clip_chat(chat)
    focus_line = (focus or "").replace('"', "'").strip()
    focus_block = f"Focus: {focus_line}\n" if focus_line else ""
    truncated_note = (
        "[NOTE: transcript was truncated; analyse only what is present.]\n"
        if truncated
        else ""
    )
    return f"""You are analysing a doctor's chat against ONLY the sources in this notebook — no outside knowledge.
{truncated_note}{focus_block}
CHAT:
\"\"\"
{body}
\"\"\"

Return ONLY valid JSON:
{{"topic":"...","where":"chapter/section/page","summary":"2-3 sentences in the chat's language","claims":[{{"text":"...","verdict":"supported|unsupported|unclear|contradicted","where":"...","note":"..."}}],"gaps":[{{"label":"...","why":"...","where":"...","kind":"fact|number|difference|decision|exception"}}],"cards":[{{"q":"...","a":"...","kind":"fact"}}]}}

Rules:
- "supported" only if the source explicitly backs the claim.
- "contradicted" if the source says the opposite.
- "unsupported" if the chat asserts it but the source is silent.
- List every clinically important gap the chat revealed.
- Make 4-8 flashcards covering the gaps and any contradicted claims.
- Do not add any text before or after the JSON."""


# ---------------------------------------------------------------------------
# result object
# ---------------------------------------------------------------------------

@dataclass
class Claim:
    text: str
    verdict: str = "unclear"
    where: str = ""
    note: str = ""

    @property
    def verdict_label(self) -> str:
        return VERDICT_LABEL.get(self.verdict, VERDICT_LABEL["unclear"])


@dataclass
class Gap:
    label: str
    why: str = ""
    where: str = ""
    kind: str = "fact"


@dataclass
class ChatAnalysis:
    topic: str = ""
    where: str = ""
    summary: str = ""
    claims: list[Claim] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    cards: list[dict[str, str]] = field(default_factory=list)
    raw_error: str = ""

    @property
    def ok(self) -> bool:
        return not self.raw_error and bool(
            self.claims or self.gaps or self.cards or self.summary
        )


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def parse_analysis(text: str) -> ChatAnalysis:
    """Parse a NotebookLM reply: JSON (preferred) or a cards-only paste."""
    text = (text or "").strip()
    if not text:
        return ChatAnalysis(raw_error="Nothing was pasted.")

    result = _try_json(text)
    if result is not None:
        return result

    # Cards-only fallback (JSON / markdown table / Q: A:) — reuse simple parser.
    from .simple import parse_reply

    cards = parse_reply(text)
    if cards.ok:
        return ChatAnalysis(
            topic=cards.topic,
            where=cards.where,
            summary="Cards only were extracted from the reply.",
            cards=list(cards.cards),
        )

    return ChatAnalysis(
        raw_error=(
            "Could not recognise that paste.\n\n"
            "Expected JSON with topic / claims / gaps / cards, "
            "or a card paste (JSON / table / Q: A:)."
        )
    )


def normalize_verdict(value: str) -> str:
    raw = (value or "").strip()
    key = raw.lower()
    if key in _VERDICT_ALIASES:
        return _VERDICT_ALIASES[key]
    if raw in _VERDICT_ALIASES:
        return _VERDICT_ALIASES[raw]
    return "unclear"


def normalize_kind(value: str) -> str:
    raw = (value or "fact").strip()
    lower = raw.lower()
    if lower in KIND_TO_ERROR:
        return lower
    if lower in _KIND_ALIASES:
        return _KIND_ALIASES[lower]
    upper = raw.upper()
    if upper in _ERROR_TO_KIND:
        return _ERROR_TO_KIND[upper]
    return "fact"


def _try_json(text: str) -> ChatAnalysis | None:
    candidates = [text]
    for m in re.finditer(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL):
        candidates.insert(0, m.group(1))
    start = text.find("{")
    if start >= 0:
        candidates.insert(0, text[start:])

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            # Brace-match the first object when the model wrapped it in prose.
            obj = _first_object(candidate)
            if obj is None:
                continue
        if not isinstance(obj, dict):
            continue
        parsed = _from_obj(obj)
        if parsed is not None:
            return parsed
    return None


def _first_object(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                except (json.JSONDecodeError, ValueError):
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def _from_obj(obj: dict) -> ChatAnalysis | None:
    claims_raw = obj.get("claims") or obj.get("findings") or []
    gaps_raw = obj.get("gaps") or obj.get("knowledge_gaps") or []
    cards_raw = obj.get("cards") or obj.get("flashcards") or []
    summary = str(obj.get("summary") or obj.get("analysis") or "").strip()
    topic = str(obj.get("topic") or "").strip()
    where = str(obj.get("where") or "").strip()

    claims = [_claim_from(c) for c in claims_raw] if isinstance(claims_raw, list) else []
    claims = [c for c in claims if c is not None]
    gaps = [_gap_from(g) for g in gaps_raw] if isinstance(gaps_raw, list) else []
    gaps = [g for g in gaps if g is not None]
    cards = [_card_from(c) for c in cards_raw] if isinstance(cards_raw, list) else []
    cards = [c for c in cards if c is not None]

    if not (claims or gaps or cards or summary):
        return None
    return ChatAnalysis(
        topic=topic,
        where=where,
        summary=summary,
        claims=claims,
        gaps=gaps,
        cards=cards,
    )


def _claim_from(raw) -> Claim | None:
    if isinstance(raw, str):
        text = raw.strip()
        return Claim(text=text) if text else None
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or raw.get("claim") or raw.get("statement") or "").strip()
    if not text:
        return None
    return Claim(
        text=text,
        verdict=normalize_verdict(str(raw.get("verdict") or raw.get("status") or "")),
        where=str(raw.get("where") or raw.get("source") or "").strip(),
        note=str(raw.get("note") or raw.get("why") or "").strip(),
    )


def _gap_from(raw) -> Gap | None:
    if isinstance(raw, str):
        label = raw.strip()
        return Gap(label=label) if label else None
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or raw.get("gap") or raw.get("topic") or "").strip()
    why = str(raw.get("why") or raw.get("reason") or raw.get("note") or "").strip()
    if not label:
        label = why
    if not label:
        return None
    return Gap(
        label=label,
        why=why,
        where=str(raw.get("where") or raw.get("source") or "").strip(),
        kind=normalize_kind(str(raw.get("kind") or raw.get("error_kind") or raw.get("type") or "fact")),
    )


def _card_from(raw) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    q = str(raw.get("q") or raw.get("question") or "").strip()
    a = str(raw.get("a") or raw.get("answer") or "").strip()
    if not q or not a:
        return None
    return {"q": q, "a": a, "kind": normalize_kind(str(raw.get("kind") or "fact"))}


# ---------------------------------------------------------------------------
# persist
# ---------------------------------------------------------------------------

def save_analysis(store: Store, parsed: ChatAnalysis) -> dict:
    """Persist one analysis as a KnowledgeUnit + cards + diagnoses.

    Returns ``{"ku_id", "cards_saved", "gaps", "claims"}``.
    """
    if not parsed.ok:
        return {
            "ku_id": "",
            "cards_saved": 0,
            "gaps": 0,
            "claims": 0,
            "error": parsed.raw_error,
        }

    topic = parsed.topic or "Chat analysis"
    source_title = f"NotebookLM — chat — {topic}"
    source = store.find_source_by_title(source_title)
    if not source:
        source = Source(
            title=source_title,
            kind="notebooklm",
            citation="Imported via chat analysis",
        )
        store.upsert_source(source)

    n_gaps = len(parsed.gaps)
    n_claims = len(parsed.claims)
    statement = parsed.summary or (
        f"Chat analysis: {n_gaps} gaps, {n_claims} claims, {len(parsed.cards)} cards"
    )
    ku = KnowledgeUnit(
        topic=topic,
        subtopic="chat analysis",
        statement=statement,
        source_id=source.id,
        chapter=parsed.where or "",
        section="",
        location="",
        status="WEAK" if parsed.gaps else "LEARNING",
        common_mistakes="; ".join(g.label for g in parsed.gaps[:4]),
    )
    store.upsert_ku(ku)

    saved = 0
    for c in parsed.cards:
        kind = c.get("kind", "fact")
        card = Card(
            ku_id=ku.id,
            question=c["q"],
            answer=c["a"],
            card_type="BASIC",
            error_target=KIND_TO_ERROR.get(kind, "FACTUAL_ERROR"),
            tags=[f"simple::{kind}", "notebooklm", "chat_analysis"],
        )
        store.upsert_card(card)
        saved += 1

    for gap in parsed.gaps:
        store.add_diagnosis(
            Diagnosis(
                ku_id=ku.id,
                error_type=KIND_TO_ERROR.get(gap.kind, "FACTUAL_ERROR"),
                confidence=0.7,
                evidence=gap.why or gap.label,
                engine="notebooklm_chat",
            )
        )

    store.log_event(
        "chat_analysis",
        {
            "ku_id": ku.id,
            "cards": saved,
            "gaps": n_gaps,
            "claims": n_claims,
        },
    )
    return {
        "ku_id": ku.id,
        "cards_saved": saved,
        "gaps": n_gaps,
        "claims": n_claims,
    }


def list_open_gaps(store: Store, limit: int = 5) -> list[WeakSpot]:
    """Unresolved gaps that came from chat analysis, as plain-language WeakSpots."""
    spots: list[WeakSpot] = []
    titles = store.source_titles()
    for diagnosis in store.list_diagnoses(unresolved_only=True):
        if diagnosis.engine != "notebooklm_chat":
            continue
        ku = store.get_ku(diagnosis.ku_id)
        label = ku.label if ku else "Gap from chat"
        where_parts: list[str] = []
        if ku:
            source_title = titles.get(ku.source_id, "")
            for part in (source_title, ku.chapter, ku.section, ku.location):
                if part:
                    where_parts.append(part)
        plain = _ERROR_PLAIN.get(diagnosis.error_type, "Found in chat analysis")
        why = diagnosis.evidence or plain
        spots.append(
            WeakSpot(
                label=label,
                summary=why,
                source_hint=" · ".join(where_parts) if where_parts else "No source recorded",
                time_estimate="about 5 min",
                ku_id=diagnosis.ku_id,
                error_types=[diagnosis.error_type],
                origin="chat",
            )
        )
        if len(spots) >= limit:
            break
    return spots
