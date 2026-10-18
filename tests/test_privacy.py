"""Fail if project files contain identifiers that must stay out of this repo."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "node_modules", ".wrangler", "__pycache__", ".venv"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".woff", ".woff2", ".pyc"}


def _join(*parts):
    return "".join(parts)


NEEDLES = [
    "example-term-3",
    "example-term-1",
    "example-term-4",
    "example-term-5",
    "example-term-6",
    "example-term-7",
    "example-term-2",
    "example-term-8",
    "example-term-9",
]


class PrivacyTests(unittest.TestCase):
    def test_worktree_has_no_forbidden_substrings(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
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
