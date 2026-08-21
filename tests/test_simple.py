"""Regression tests for the phone-first simple module."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from secondbrain.models import Card, KnowledgeUnit, Review, Source
from secondbrain.simple import (
    KIND_TO_ERROR,
    parse_reply,
    restudy_prompt,
    save_cards,
    study_prompt,
    weak_spots,
)
from secondbrain.store import Store


class StudyPromptTests(unittest.TestCase):
    def test_includes_topic_and_forbids_outside_knowledge(self):
        prompt = study_prompt('Topic "One"')
        self.assertIn("Topic 'One'", prompt)
        self.assertNotIn('"', study_prompt('Topic "One"').split("Topic:", 1)[1].split("\n", 1)[0])
        self.assertIn("ONLY the sources", prompt)
        self.assertIn("JSON", prompt)
        self.assertLessEqual(prompt.count("\n"), 15)


class ParseReplyTests(unittest.TestCase):
    def test_empty(self):
        parsed = parse_reply("  ")
        self.assertFalse(parsed.ok)
        self.assertIn("Nothing was pasted", parsed.raw_error)

    def test_json(self):
        raw = '{"topic":"Topic","where":"ch 11","cards":[{"q":"cut-off?","a":"<20","kind":"number"}]}'
        parsed = parse_reply(raw)
        self.assertTrue(parsed.ok)
        self.assertEqual(parsed.topic, "Topic")
        self.assertEqual(parsed.where, "ch 11")
        self.assertEqual(parsed.cards[0]["kind"], "number")
        self.assertEqual(KIND_TO_ERROR["number"], "THRESHOLD_ERROR")

    def test_fenced_json_with_prose(self):
        raw = "Here you go:\n```json\n{\"cards\":[{\"q\":\"Q1\",\"a\":\"A1\"}]}\n```\nbye"
        parsed = parse_reply(raw)
        self.assertTrue(parsed.ok)
        self.assertEqual(parsed.cards[0]["q"], "Q1")

    def test_markdown_table(self):
        raw = "| Question | Answer |\n|---|---|\n| What is X? | Y |\n| Z? | W |"
        parsed = parse_reply(raw)
        self.assertTrue(parsed.ok)
        self.assertEqual(len(parsed.cards), 2)
        self.assertEqual(parsed.cards[0]["a"], "Y")

    def test_qa_lines(self):
        raw = "Q: first?\nA: one\nQ: second?\nA: two"
        parsed = parse_reply(raw)
        self.assertTrue(parsed.ok)
        self.assertEqual([c["q"] for c in parsed.cards], ["first?", "second?"])

    def test_garbage(self):
        parsed = parse_reply("hello this is not cards")
        self.assertFalse(parsed.ok)


class SaveAndWeakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_cards_and_extra_tags(self):
        parsed = parse_reply('{"topic":"T","cards":[{"q":"Q","a":"A","kind":"decision"}]}')
        result = save_cards(self.store, parsed, extra_tags=["from-test"])
        self.assertEqual(result["cards_saved"], 1)
        cards = self.store.list_cards(ku_id=result["ku_id"])
        self.assertEqual(cards[0].error_target, "MANAGEMENT_ERROR")
        self.assertIn("from-test", cards[0].tags)
        self.assertIn("notebooklm", cards[0].tags)

    def test_weak_spots_empty(self):
        self.assertEqual(weak_spots(self.store), [])

    def test_weak_spots_from_failures(self):
        src = Source(title="Source")
        self.store.upsert_source(src)
        ku = KnowledgeUnit(topic="Unit", statement="thresholds", source_id=src.id, chapter="11")
        self.store.upsert_ku(ku)
        card = Card(ku_id=ku.id, question="cut-off?", answer="20", error_target="THRESHOLD_ERROR")
        self.store.upsert_card(card)
        for i, rating in enumerate([1, 1, 1, 1]):
            self.store.add_reviews(
                [
                    Review(
                        card_id=card.id,
                        reviewed_at=f"2026-01-0{i+1}T10:00:00+00:00",
                        rating=rating,
                        origin="test",
                    )
                ]
            )
        spots = weak_spots(self.store, limit=3)
        self.assertTrue(spots)
        self.assertIn("wrong", spots[0].summary)
        self.assertEqual(spots[0].origin, "anki")
        self.assertIn("11", spots[0].source_hint)

    def test_restudy_prompt(self):
        prompt = restudy_prompt("Unit", where="ch 11", error_types=["THRESHOLD_ERROR"])
        self.assertIn("Unit", prompt)
        self.assertIn("ONLY the sources", prompt)
        self.assertIn("numbers keep slipping", prompt)


if __name__ == "__main__":
    unittest.main()
