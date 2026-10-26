"""cli/stcount tests: run in a temp ST_ROOT, never push."""
import importlib.machinery, importlib.util, json, os, sys, tempfile, unittest
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cli")

_SAVED = {}


def setUpModule():
    for key in ("ST_ROOT", "ST_TZ", "STCOUNT_CLAUDE_GLOB"):
        _SAVED[key] = os.environ.get(key)


def tearDownModule():
    for key, value in _SAVED.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def load(root, glob_):
    os.environ["ST_ROOT"] = root; os.environ["ST_TZ"] = "America/New_York"; os.environ["STCOUNT_CLAUDE_GLOB"] = glob_
    ld = importlib.machinery.SourceFileLoader("stcount_t", os.path.join(HERE, "stcount.py"))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader("stcount_t", ld)); ld.exec_module(m)
    return m

def rec(mid, req, ts, i=1, o=10, cr=100, cw=5, typ="assistant"):
    return json.dumps({"type": typ, "timestamp": ts, "requestId": req, "message": {"id": mid, "usage": {
        "input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw}}}) + "\n"

class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.p = os.path.join(self.d, "proj", "a.jsonl"); os.makedirs(os.path.dirname(self.p))
        self.m = load(self.d, os.path.join(self.d, "proj", "**", "*.jsonl"))
    def w(self, s, mode="a"):
        with open(self.p, mode) as f: f.write(s)
    def cc(self): return json.load(open(os.path.join(self.d, ".token-usage.json")))["Claude Code"]

    def test_dedupe_and_week(self):
        self.w(rec("m1", "r1", "2026-10-19T03:00:00Z") * 3 + rec("m2", "r2", "2026-10-19T05:00:00Z") + rec("u", "x", "2026-10-19T05:00:00Z", typ="user"))
        n, _, _ = self.m.scan(); self.assertEqual(n, 2)
        c = self.cc()
        # 03:00Z = 23:00 New York on Sunday -> W42; 05:00Z = 01:00 Monday -> W43
        self.assertEqual([w["w"] for w in c["weeks"]], ["2026-W43", "2026-W42"])
        self.assertEqual(c["total"], {"in": 2, "out": 20, "cr": 200, "cw": 10})

    def test_incremental_partial_line(self):
        self.w(rec("m1", "r1", "2026-10-20T00:00:00Z")); self.m.scan()
        full = rec("m2", "r2", "2026-10-20T01:00:00Z"); self.w(full[:20])
        n, _, _ = self.m.scan(); self.assertEqual(n, 0)
        self.w(full[20:]); n, _, _ = self.m.scan(); self.assertEqual(n, 1)
        self.assertEqual(self.cc()["total"]["out"], 20)
        n, _, _ = self.m.scan(); self.assertEqual(n, 0)   # rescanning adds nothing

    def test_history_survives_deletion_and_rewrite(self):
        self.w(rec("m1", "r1", "2026-10-20T00:00:00Z")); self.m.scan()
        os.remove(self.p); self.m.scan(); self.assertEqual(self.cc()["total"]["out"], 10)
        self.w(rec("m1", "r1", "2026-10-20T00:00:00Z") + rec("m3", "r3", "2026-10-20T02:00:00Z"), "w")
        self.m.scan(); self.assertEqual(self.cc()["total"]["out"], 20)

    def test_dry_run_writes_nothing(self):
        self.w(rec("m1", "r1", "2026-10-20T00:00:00Z")); self.m.scan(dry=True)
        self.assertFalse(os.path.exists(os.path.join(self.d, ".token-usage.json")))

    def test_codex_ingest_idempotent_and_monotonic(self):
        wk = {}
        self.m.ingest_codex({"token_weeks": {"2026-W43": {"in": 5, "out": 7, "cr": 9}}}, wk)
        self.m.ingest_codex({"token_weeks": {"2026-W43": {"in": 5, "out": 7, "cr": 9}}}, wk)
        self.m.ingest_codex({"token_weeks": {"2026-W44": {"in": 1}}}, wk)   # an older week missing from the push keeps its total
        out = self.m.build(wk)["Codex"]
        self.assertEqual(out["total"], {"in": 6, "out": 7, "cr": 9, "cw": 0})
        with self.assertRaises(ValueError): self.m.ingest_codex({"token_weeks": {"bad": {}}}, wk)
        with self.assertRaises(ValueError): self.m.ingest_codex({"primary": {}}, wk)

class T2(T):
    def test_streaming_partial_output_max(self):
        self.w(rec("m1", "r1", "2026-10-20T00:00:00Z", o=3) + rec("m1", "r1", "2026-10-20T00:00:01Z", o=50)); self.m.scan()
        self.assertEqual(self.cc()["total"]["out"], 50)
        self.w(rec("m1", "r1", "2026-10-20T00:00:02Z", o=50)); self.m.scan()
        self.assertEqual(self.cc()["total"]["out"], 50)

    def test_bad_lines_do_not_stall(self):
        self.w("123\n" + json.dumps({"type": "assistant", "timestamp": "2026-10-20T00:00:00Z", "message": {"id": "z", "usage": {"output_tokens": "abc"}}}) + "\n" + rec("m9", "r9", "2026-10-20T00:00:00Z"))
        n, _, _ = self.m.scan(); self.assertEqual(n, 1)

    def test_old_messages_ignored_after_init(self):
        self.w(rec("m1", "r1", "2020-01-01T00:00:00Z")); self.m.scan()     # the first scan imports all history
        self.assertEqual(self.cc()["total"]["out"], 10)
        self.w(rec("m1", "r1", "2020-01-01T00:00:00Z") + rec("old2", "r", "2020-01-02T00:00:00Z"))
        self.m.scan(); self.assertEqual(self.cc()["total"]["out"], 10)

    def test_codex_bad_fields_rejected(self):
        wk = {}
        for bad in ({"token_weeks": {"2026-W43": {"in": -1}}}, {"token_weeks": {"2026-W43": {"in": "5"}}}, {"token_weeks": {"abcd-Wxy": {"in": 1}}},
                    {"token_weeks": {"2026-W60": {"in": 1}}},
                    {"token_weeks": {}, "since": 123}, {"token_weeks": {}, "since": "<img onerror=x>"}):
            with self.assertRaises(ValueError): self.m.ingest_codex(bad, wk)
        self.m.ingest_codex({"token_weeks": {}, "generated": "<b>"}, wk)
        self.assertTrue(self.m.iso_ok(wk["Codex"]["pushed"]))

    def test_records_without_ids_skipped(self):
        self.w(rec(None, None, "2026-10-20T00:00:00Z")); n, _, _ = self.m.scan()
        self.assertEqual(n, 0)

    def test_bad_timestamp_and_since_normalized(self):
        self.w(json.dumps({"type": "assistant", "timestamp": 5, "message": {"id": "q", "usage": {}}}) + "\n" + rec("m1", "r1", "2026-10-20T00:00:00Z"))
        n, _, _ = self.m.scan(); self.assertEqual(n, 1)
        wk = {}; self.m.ingest_codex({"token_weeks": {}, "since": "2026-10-20T04:00:00Z"}, wk)
        self.assertEqual(wk["Codex"]["since"], "2026-10-20T00:00:00-04:00")

    def test_file_mode_644(self):
        self.w(rec("m1", "r1", "2026-10-20T00:00:00Z")); self.m.scan()
        self.assertEqual(os.stat(os.path.join(self.d, ".token-usage.json")).st_mode & 0o777, 0o644)

if __name__ == "__main__":
    unittest.main(verbosity=1)
