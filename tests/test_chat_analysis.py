"""Tests for NotebookLM chat analysis."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from secondbrain.chat_analysis import (
    CHAT_MAX_CHARS,
    analysis_prompt,
    clip_chat,
    list_open_gaps,
    normalize_kind,
    normalize_verdict,
    parse_analysis,
    save_analysis,
)
from secondbrain.store import Store


SAMPLE_JSON = """
{
  "topic": "Unit A",
  "where": "ch 11 p.42",
  "summary": "The chat mixed up the initiation cut-off.",
  "claims": [
    {"text": "Start at 15", "verdict": "contradicted", "where": "Table 11.2", "note": "cut-off is 20"},
    {"text": "Hold if volume depleted", "verdict": "supported", "where": "p.43"}
  ],
  "gaps": [
    {"label": "initiation threshold", "why": "used 15 instead of 20", "where": "Table 11.2", "kind": "number"}
  ],
  "cards": [
    {"q": "What is the cut-off?", "a": "20", "kind": "number"}
  ]
}
"""


class PromptTests(unittest.TestCase):
    def test_prompt_contains_chat_and_rules(self):
        prompt = analysis_prompt("User: start at 15?\nNotebookLM: check the table", focus='focus "cut-off"')
        self.assertIn("ONLY the sources", prompt)
        self.assertIn("start at 15", prompt)
        self.assertIn("focus 'cut-off'", prompt)
        self.assertIn("supported|unsupported|unclear|contradicted", prompt)

    def test_clip_chat(self):
        short, truncated = clip_chat("hello")
        self.assertEqual(short, "hello")
        self.assertFalse(truncated)
        long = "a" * (CHAT_MAX_CHARS + 500)
        clipped, truncated = clip_chat(long)
        self.assertTrue(truncated)
        self.assertLessEqual(len(clipped), CHAT_MAX_CHARS + 10)
        self.assertIn("…", clipped)

    def test_prompt_notes_truncation(self):
        prompt = analysis_prompt("x" * (CHAT_MAX_CHARS + 100))
        self.assertIn("truncated", prompt.lower())


class ParseTests(unittest.TestCase):
    def test_empty(self):
        parsed = parse_analysis("")
        self.assertFalse(parsed.ok)
        self.assertIn("Nothing was pasted", parsed.raw_error)

    def test_full_json(self):
        parsed = parse_analysis(SAMPLE_JSON)
        self.assertTrue(parsed.ok)
        self.assertEqual(parsed.topic, "Unit A")
        self.assertEqual(len(parsed.claims), 2)
        self.assertEqual(parsed.claims[0].verdict, "contradicted")
        self.assertEqual(parsed.claims[0].verdict_label, "Contradicted by the source")
        self.assertEqual(parsed.gaps[0].kind, "number")
        self.assertEqual(parsed.cards[0]["a"], "20")

    def test_fenced_and_prose(self):
        raw = "Sure.\n```json\n" + SAMPLE_JSON + "\n```\nHope this helps."
        parsed = parse_analysis(raw)
        self.assertTrue(parsed.ok)
        self.assertEqual(len(parsed.gaps), 1)

    def test_alias_keys(self):
        raw = '{"knowledge_gaps":[{"gap":"dose","reason":"mixed mg/mcg","type":"THRESHOLD_ERROR"}],"flashcards":[{"question":"Q","answer":"A"}]}'
        parsed = parse_analysis(raw)
        self.assertTrue(parsed.ok)
        self.assertEqual(parsed.gaps[0].kind, "number")
        self.assertEqual(parsed.cards[0]["q"], "Q")

    def test_persian_verdict(self):
        raw = '{"claims":[{"text":"X","verdict":"خلاف"}]}'
        parsed = parse_analysis(raw)
        self.assertEqual(parsed.claims[0].verdict, "contradicted")

    def test_cards_only_fallback(self):
        parsed = parse_analysis("Q: What is X?\nA: Y")
        self.assertTrue(parsed.ok)
        self.assertEqual(parsed.cards[0]["q"], "What is X?")
        self.assertTrue(parsed.summary)

    def test_garbage(self):
        parsed = parse_analysis("not analysis, just a paragraph.")
        self.assertFalse(parsed.ok)


class NormalizeTests(unittest.TestCase):
    def test_verdict_aliases(self):
        self.assertEqual(normalize_verdict("yes"), "supported")
        self.assertEqual(normalize_verdict("تأیید"), "supported")
        self.assertEqual(normalize_verdict("nope"), "unclear")

    def test_kind_aliases(self):
        self.assertEqual(normalize_kind("THRESHOLD_ERROR"), "number")
        self.assertEqual(normalize_kind("dose"), "number")
        self.assertEqual(normalize_kind("weird"), "fact")


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_creates_cards_and_diagnoses(self):
        parsed = parse_analysis(SAMPLE_JSON)
        result = save_analysis(self.store, parsed)
        self.assertEqual(result["cards_saved"], 1)
        self.assertEqual(result["gaps"], 1)
        self.assertEqual(result["claims"], 2)
        ku = self.store.get_ku(result["ku_id"])
        self.assertIsNotNone(ku)
        self.assertEqual(ku.status, "WEAK")
        cards = self.store.list_cards(ku_id=result["ku_id"])
        self.assertEqual(cards[0].error_target, "THRESHOLD_ERROR")
        self.assertIn("chat_analysis", cards[0].tags)
        diags = self.store.list_diagnoses(result["ku_id"], unresolved_only=True)
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].engine, "notebooklm_chat")

        spots = list_open_gaps(self.store)
        self.assertEqual(len(spots), 1)
        self.assertEqual(spots[0].origin, "chat")
        self.assertIn("15 instead of 20", spots[0].summary)

    def test_save_rejects_empty(self):
        result = save_analysis(self.store, parse_analysis(""))
        self.assertEqual(result["cards_saved"], 0)
        self.assertIn("error", result)


class LayoutTests(unittest.TestCase):
    def test_no_pages_dir_advanced_kept(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "pages").exists())
        advanced = list((root / "advanced").glob("*.py"))
        self.assertGreaterEqual(len(advanced), 8)

    def test_app_has_three_sections(self):
        src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        self.assertIn("Cards", src)
        self.assertIn("Weaknesses", src)
        self.assertIn("Chat analysis", src)
        self.assertIn("chat_analysis", src)
        self.assertIn("advanced/", src)


if __name__ == "__main__":
    unittest.main()
