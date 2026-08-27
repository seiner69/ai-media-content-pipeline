from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


daily = load_module("daily_pipeline", "scripts/run_daily_pipeline.py")
asr = load_module("asr_compare", "scripts/asr_compare.py")
feedback = load_module("record_feedback", "scripts/record_feedback.py")


class DailyPipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "keywords": {
                "ai_core": ["AI", "Agent"],
                "creator": ["video"],
                "ordinary_people": ["creator"],
                "conflict": ["risk"],
                "visual": ["report"],
            },
            "scoring": {
                "ai_relevance": 25,
                "audience_relevance": 20,
                "conflict": 15,
                "visual_evidence": 15,
                "format_fit": 15,
                "timeliness": 10,
            },
        }

    def test_parse_hot_value_understands_units(self):
        self.assertEqual(daily.parse_hot_value("1.5万"), 15000)
        self.assertEqual(daily.parse_hot_value("2,000"), 2000)
        self.assertEqual(daily.parse_hot_value(None), 0)

    def test_dedupe_keeps_the_first_normalized_title(self):
        first = daily.Topic("demo", 1, "same title", "https://example.com/a", 1)
        duplicate = daily.Topic("demo", 2, "Same   Title", "https://example.com/b", 9)
        items = daily.dedupe([first, duplicate])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://example.com/a")

    def test_scoring_rewards_relevant_evidence(self):
        topic = daily.Topic(
            "demo",
            1,
            "AI Agent risk report for video creator",
            "https://example.com/topic",
            100,
        )
        scored = daily.score_topic(topic, self.config)
        self.assertGreater(scored.score, 50)
        self.assertIn("AI", scored.tags)


class AsrGateTests(unittest.TestCase):
    def test_normalization_removes_layout_punctuation(self):
        self.assertEqual(asr.normalize_for_compare("你好， AI！"), "你好ai")

    def test_publish_gate_blocks_missing_or_added_text(self):
        clean = asr.edit_stats("abcdef", "abcdef")
        changed = asr.edit_stats("abcdef", "abcxef")
        self.assertEqual(asr.publish_gate(clean), "pass_exact")
        self.assertEqual(asr.publish_gate(changed), "review_typo_only")


class FeedbackTests(unittest.TestCase):
    def test_ratio_formats_decimal_percentages(self):
        self.assertEqual(feedback.ratio("0.38"), "0.38")
        self.assertEqual(feedback.ratio(""), "")


if __name__ == "__main__":
    unittest.main()
