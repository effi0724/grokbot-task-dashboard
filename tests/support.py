"""Shared fixtures for the CLI tests. Not collected by unittest (name does not start with test)."""

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

import calibration  # noqa: E402
import stlib  # noqa: E402

ENV_KEYS = (
    "ST_ROOT",
    "ST_PUSH_URL",
    "ST_STATS_DAYS",
    "ST_HISTORY_DAYS",
    "ST_STATS_MAX",
    "ST_CALIBRATE_MIN",
    "ST_LANG",
    "ST_TZ",
    "ST_BOTS",
)


class StateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = {key: os.environ.get(key) for key in ENV_KEYS}
        os.environ["ST_ROOT"] = self.tmp.name
        os.environ["ST_PUSH_URL"] = ""
        os.environ["ST_LANG"] = "zh"
        os.environ["ST_STATS_DAYS"] = "90"
        os.environ["ST_HISTORY_DAYS"] = "7"
        os.environ["ST_STATS_MAX"] = "500"
        os.environ["ST_CALIBRATE_MIN"] = "3"
        os.environ["ST_TZ"] = "America/New_York"
        os.environ.pop("ST_BOTS", None)
        self.start = datetime(2026, 10, 18, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        self.frozen = self.start
        stlib.set_clock(lambda: self.frozen)

    def tearDown(self):
        stlib.set_clock(None)
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def advance(self, **kwargs):
        from datetime import timedelta
        self.frozen = self.frozen + timedelta(**kwargs)
