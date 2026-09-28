from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_unequal_replacements_count_surplus_as_insertions_or_deletions(self):
        for expected, actual, inserted, deleted in [
            ("abc", "axyc", 1, 0),
            ("axyc", "abc", 0, 1),
            ("甲乙丙", "甲丁戊丙", 1, 0),
        ]:
            with self.subTest(expected=expected, actual=actual):
                stats = asr.edit_stats(expected, actual)
                self.assertEqual((stats.inserted_chars, stats.deleted_chars), (inserted, deleted))
                self.assertEqual(stats.replaced_expected_chars, stats.replaced_actual_chars)
                self.assertEqual(asr.publish_gate(stats), "fail_extra_or_missing")

    def test_separate_replacement_surpluses_do_not_cancel_each_other(self):
        stats = asr.edit_stats("abMIDDLEyz", "axyMIDDLEw")
        self.assertEqual((stats.inserted_chars, stats.deleted_chars), (1, 1))
        self.assertEqual(asr.publish_gate(stats), "fail_extra_or_missing")

    def test_report_does_not_let_tolerant_aliases_override_strict_failure(self):
        expected, actual = "开始执行任务", "开始然后执行任务"
        strict = asr.edit_stats(asr.normalize_for_compare(expected), asr.normalize_for_compare(actual))
        tolerant = asr.edit_stats(asr.normalize_for_compare(expected, True), asr.normalize_for_compare(actual, True))
        self.assertEqual(asr.publish_gate(tolerant), "pass_exact")
        report = asr.render_report(Path("audio.wav"), Path("script.md"), actual, [], expected,
                                   0.9, 1.0, [], strict, tolerant, "synthetic", "none")
        self.assertIn("当前不通过发布硬门槛", report)
        self.assertNotIn("当前通过发布硬门槛", report)

    def test_cli_json_and_stdout_expose_strict_authoritative_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = root / "script.txt"
            expected.write_text("开始执行任务", encoding="utf-8")
            output = root / "output"
            argv = ["asr_compare", "--audio", str(root / "voice.wav"),
                    "--expected", str(expected), "--out-dir", str(output)]
            with patch.object(sys, "argv", argv), \
                 patch.object(asr, "transcribe_faster_whisper", return_value=("开始然后执行任务", [])), \
                 contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(asr.main(), 0)
            report = json.loads((output / "voice.asr_compare.json").read_text(encoding="utf-8"))
            self.assertEqual(report["publish_gate"], "fail_extra_or_missing")
            self.assertEqual(report["publish_gate"], report["publish_gate_strict"])
            self.assertEqual(report["publish_gate_tolerant"], "pass_exact")
            self.assertIn("PUBLISH_GATE=fail_extra_or_missing", stdout.getvalue())


class FeedbackTests(unittest.TestCase):
    def test_ratio_formats_decimal_percentages(self):
        self.assertEqual(feedback.ratio("0.38"), "0.38")
        self.assertEqual(feedback.ratio(""), "")


if __name__ == "__main__":
    unittest.main()
