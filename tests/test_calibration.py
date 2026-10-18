import unittest

from support import calibration


def rec(bot, task_type, ratio, revisions=0):
    return {
        "bot": bot,
        "task_type": task_type,
        "ratio": ratio,
        "revisions": revisions,
        "estimate": 100,
        "actual": 100 * ratio,
    }


class CalibrationMathTests(unittest.TestCase):
    def test_percentile_even_count(self):
        self.assertEqual(calibration.percentile([4, 1, 3, 2], 50), 2.5)
        self.assertEqual(calibration.percentile([1, 2, 3, 4], 25), 1.75)
        self.assertEqual(calibration.percentile([1, 2, 3, 4], 75), 3.25)
        self.assertEqual(calibration.percentile([2], 50), 2)

    def test_percentile_rejects_empty(self):
        with self.assertRaises(ValueError):
            calibration.percentile([], 50)

    def test_summarize_ratio_and_overrun(self):
        summary = calibration.summarize([
            {"ratio": ratio, "revisions": rev}
            for ratio, rev in ((1, 0), (2, 1), (3, 2), (4, 3))
        ])
        self.assertEqual(summary["n"], 4)
        self.assertEqual(summary["median_ratio"], 2.5)
        self.assertEqual(summary["p25_ratio"], 1.75)
        self.assertEqual(summary["p75_ratio"], 3.25)
        self.assertEqual(summary["mean_ratio"], 2.5)
        self.assertEqual(summary["spread"], 1.5)
        self.assertEqual(summary["overrun_rate"], 0.75)
        self.assertEqual(summary["median_revisions"], 1.5)

    def test_confident_bot_type_range(self):
        records = [rec("Coder", "coding", ratio) for ratio in (1, 2, 3, 4)]
        accuracy = calibration.build_accuracy(records, 90, 3)
        suggestion = calibration.suggest_duration(100, accuracy, "Coder", "coding", 3)
        self.assertEqual(suggestion["basis"], "bot+type")
        self.assertFalse(suggestion["low_confidence"])
        self.assertEqual(suggestion["reason"], "ok")
        self.assertEqual(suggestion["minutes"], 250)
        self.assertEqual(suggestion["low_minutes"], 175)
        self.assertEqual(suggestion["high_minutes"], 325)
        self.assertLessEqual(suggestion["low_minutes"], suggestion["minutes"])
        self.assertGreaterEqual(suggestion["high_minutes"], suggestion["minutes"])

    def test_thin_bucket_falls_through_to_type(self):
        records = [rec("Coder", "coding", 1.5), rec("Coder", "coding", 1.5)]
        records += [rec("Ops", "coding", ratio) for ratio in (1, 2, 3, 4)]
        accuracy = calibration.build_accuracy(records, 90, 3)
        basis, row, low = calibration.select_basis(accuracy, "Coder", "coding", 3)
        self.assertEqual(basis, "type")
        self.assertFalse(low)
        self.assertEqual(row["n"], 6)
        bot_only = calibration.suggest_duration(100, accuracy, "Ops", "", 3)
        self.assertEqual(bot_only["basis"], "bot")

    def test_low_sample_shrinks_toward_one(self):
        accuracy = calibration.build_accuracy([rec("Coder", "coding", 2)], 90, 3)
        suggestion = calibration.suggest_duration(90, accuracy, "Coder", "coding", 3)
        self.assertEqual(suggestion["basis"], "bot+type")
        self.assertTrue(suggestion["low_confidence"])
        self.assertEqual(suggestion["reason"], "low_sample")
        self.assertEqual(suggestion["applied_ratio"], 1.333)
        self.assertEqual(suggestion["minutes"], 120)
        self.assertEqual(suggestion["low_minutes"], 90)
        self.assertEqual(suggestion["high_minutes"], 180)
        text = calibration.format_suggestion(suggestion, "zh")
        self.assertIn("样本偏少", text)
        self.assertIn("2.00×", text)
        self.assertIn("收缩后 1.33×", text)

    def test_no_history_uses_a_wide_reference_range(self):
        suggestion = calibration.suggest_duration(100, calibration.build_accuracy([], 90, 3), "Coder", "coding", 3)
        self.assertEqual(suggestion["basis"], "none")
        self.assertEqual(suggestion["reason"], "no_history")
        self.assertEqual(suggestion["minutes"], 100)
        self.assertEqual(suggestion["low_minutes"], 50)
        self.assertEqual(suggestion["high_minutes"], 200)
        self.assertEqual(
            calibration.format_suggestion(suggestion, "zh"),
            "校准：样本不足，暂用原始预估 1.7 小时（参考区间 50 分钟–3.3 小时）。",
        )
        self.assertIn("not enough history", calibration.format_suggestion(suggestion, "en").lower())

    def test_missing_estimate(self):
        suggestion = calibration.suggest_duration(None, None, "Coder", "", 3)
        self.assertIsNone(suggestion["minutes"])
        self.assertEqual(suggestion["reason"], "missing_estimate")
        self.assertIn("--estimate", calibration.format_suggestion(suggestion, "en"))

    def test_record_from_task_skips_cancelled_and_strips_type(self):
        self.assertIsNone(calibration.record_from_task("Coder", {
            "state": "cancelled", "estimate_minutes": 10, "actual_minutes": 12,
        }))
        self.assertIsNone(calibration.record_from_task("Coder", {
            "state": "done", "estimate_minutes": 0, "actual_minutes": 12,
        }))
        record = calibration.record_from_task("Coder", {
            "state": "done",
            "estimate_minutes": 10,
            "actual_minutes": 15,
            "eta_revisions": 2,
            "task_type": " ops ",
        })
        self.assertEqual(record["ratio"], 1.5)
        self.assertEqual(record["task_type"], "ops")
        self.assertEqual(record["revisions"], 2)

    def test_outcome_line(self):
        line = calibration.format_outcome({
            "estimate_minutes": 120,
            "actual_minutes": 150,
            "eta_revisions": 1,
        }, "zh")
        self.assertIn("1.25×", line)
        self.assertIn("修订 1 次", line)
        self.assertIsNone(calibration.format_outcome({"state": "done"}, "en"))
