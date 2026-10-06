"""Compact graph-tooltip summaries, using only recorded price observations."""
import unittest

from app.pricing.history import sparkline


def history(values, last_at="2026-02-03T12:34:56+00:00"):
    points = [{"price": value, "at": "2026-01-01T00:00:00+00:00", "currency": "USD"}
              for value in values]
    if points:
        points[-1]["at"] = last_at
    return points


class SparklineTooltipTests(unittest.TestCase):
    def test_no_history_and_single_point_have_no_percentage(self):
        self.assertEqual(sparkline([])["label"], "Data points: 0\nChange: N/A\nLast update: Unknown")
        self.assertEqual(sparkline(history([5], None))["label"], "Data points: 1\nChange: N/A\nLast update: Unknown")

    def test_unchanged_and_zero_baseline_are_explicit(self):
        for values in ([3, 3, 3], [3, 5, 3], [0, 0]):
            self.assertIn("Change: 0.00%\n", sparkline(history(values))["label"])
        self.assertIn("Change: N/A (low is zero)\n", sparkline(history([0, 1]))["label"])

    def test_last_observation_date_uses_utc_and_handles_unknown_dates(self):
        for date in (None, "not-a-date"):
            with self.subTest(date=date):
                self.assertTrue(sparkline(history([1, 2], date))["label"].endswith("Last update: Unknown"))
        self.assertTrue(sparkline(history([1, 2], "2026-02-03T01:00:00+02:00"))["label"].endswith("Last update: 2026/02/02"))

    def test_summary_uses_only_the_ten_displayed_valid_points(self):
        chart = sparkline(history([1000] + [100] * 9 + [90]))
        self.assertEqual(chart["label"], "Data points: 10\nChange: -10.00% from high\nLast update: 2026/02/03")
        invalid = history([float("nan"), float("inf"), -1])
        self.assertEqual(sparkline(invalid)["label"], "Data points: 0\nChange: N/A\nLast update: Unknown")
        self.assertIn("Change: N/A\n", sparkline(history([1e-320, 2]))["label"])

    def test_tooltip_uses_saved_extreme_and_short_date(self):
        for values, change in [([100, 120, 90], "-25.00% from high"),
                               ([10, 5, 20], "+300.00% from low")]:
            with self.subTest(prices=values):
                chart = sparkline(history(values))
                self.assertEqual(chart["label"],
                                 f"Data points: 3\nChange: {change}\nLast update: 2026/02/03")


if __name__ == "__main__":
    unittest.main()
