"""Fail if project files contain identifiers that must stay out of this repo."""

import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "node_modules", ".wrangler", "__pycache__", ".venv"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".woff", ".woff2", ".pyc"}


def load_terms():
    """Terms come from PRIVACY_TERMS (comma-separated) or an uncommitted
    .privacy-terms file, so the list itself never ships in the repo."""
    raw = os.environ.get("PRIVACY_TERMS", "")
    if raw.strip():
        items = raw.split(",")
    else:
        path = ROOT / ".privacy-terms"
        items = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    terms = []
    for item in items:
        item = item.split("#", 1)[0].strip().lower()
        if item:
            terms.append(item)
    return terms


NEEDLES = load_terms()
SKIP_FILES = {".privacy-terms"}


class PrivacyTests(unittest.TestCase):
    @unittest.skipUnless(NEEDLES, "no .privacy-terms file or PRIVACY_TERMS set")
    def test_worktree_has_no_forbidden_substrings(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts) or path.name in SKIP_FILES:
                continue
            if path.suffix.lower() in BINARY_SUFFIXES or path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for needle in NEEDLES:
                if needle in text:
                    hits.append(f"{path.relative_to(ROOT)} contains {needle!r}")
        self.assertEqual(hits, [])

    def test_access_config_is_read_from_env(self):
        auth = (ROOT / "site" / "lib" / "auth.js").read_text(encoding="utf-8")
        middleware = (ROOT / "site" / "functions" / "_middleware.js").read_text(encoding="utf-8")
        self.assertNotIn("globalThis", auth)
        self.assertIn("ctx.env", middleware)
        self.assertIn("verifyAccess(ctx.request, ctx.env", middleware)

    def test_example_snapshot_is_labeled(self):
        path = ROOT / "site" / "public" / "example-state.json"
        self.assertTrue(path.is_file(), "generate example-state.json before shipping")
        import json
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(payload.get("_example"))
        self.assertIn("EXAMPLE", payload.get("_comment", ""))
        titles = []
        for bot in payload["bots"]:
            for task in bot.get("tasks") or []:
                titles.append(task.get("title") or "")
            for task in bot.get("history") or []:
                titles.append(task.get("title") or "")
        self.assertTrue(titles)
        self.assertTrue(all("示例" in title for title in titles))
        self.assertGreater(payload["accuracy"]["sample_count"], 0)
