import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from support import StateCase, stlib

NY = ZoneInfo("America/New_York")


class ParseTimeTests(StateCase):
    def test_empty_and_unknown(self):
        for value in ("", "  ", "待估", "未知", "-", "none", "unknown", None):
            self.assertIsNone(stlib.parse_time(value))

    def test_relative_units(self):
        self.assertEqual(stlib.parse_time("+30m"), self.start + timedelta(minutes=30))
        self.assertEqual(stlib.parse_time("+2h"), self.start + timedelta(hours=2))
        self.assertEqual(stlib.parse_time("+2 h"), self.start + timedelta(hours=2))
        self.assertEqual(stlib.parse_time("+1.5h"), self.start + timedelta(hours=1.5))
        self.assertEqual(stlib.parse_time("+1d"), self.start + timedelta(days=1))

    def test_clock_rolls_to_tomorrow_after_it_passes(self):
        self.assertEqual(stlib.parse_time("10:15"), self.start.replace(hour=10, minute=15))
        self.assertEqual(stlib.parse_time("08:00"), self.start.replace(hour=8, minute=0) + timedelta(days=1))

    def test_month_day_and_iso(self):
        self.assertEqual(
            stlib.parse_time("10-19 03:30"),
            datetime(2026, 10, 19, 3, 30, tzinfo=NY),
        )
        parsed = stlib.parse_time("2026-10-18 15:45")
        self.assertEqual(parsed, datetime(2026, 10, 18, 15, 45, tzinfo=NY))
        aware = stlib.parse_time("2026-10-18T15:00:00-04:00")
        self.assertEqual(aware, datetime(2026, 10, 18, 15, 0, tzinfo=NY))
        utc = stlib.parse_time("2026-10-18T19:00:00Z")
        self.assertEqual(utc, datetime(2026, 10, 18, 15, 0, tzinfo=NY))

    def test_invalid_times(self):
        for value in ("nope", "24:00", "12:60", "13-40 03:30", "2026-02-31 10:00"):
            with self.assertRaises(ValueError):
                stlib.parse_time(value)

    def test_duration_minutes(self):
        self.assertEqual(stlib.parse_duration_minutes("90"), 90)
        self.assertEqual(stlib.parse_duration_minutes("90m"), 90)
        self.assertEqual(stlib.parse_duration_minutes("+45m"), 45)
        self.assertEqual(stlib.parse_duration_minutes("2h"), 120)
        self.assertEqual(stlib.parse_duration_minutes("1.5h"), 90)
        self.assertEqual(stlib.parse_duration_minutes("1d"), 1440)
        self.assertIsNone(stlib.parse_duration_minutes("待估"))
        self.assertIsNone(stlib.parse_duration_minutes("0m"))
        with self.assertRaises(ValueError):
            stlib.parse_duration_minutes("soon")
