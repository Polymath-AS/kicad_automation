"""Behavioral checks for accounting and report comparison; no CAD edits."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


audit = module("audit", "tools/analyze_session.py")
drc = module("drc", "skills/kicad-drc/scripts/summarize_checks.py")


class UsageTests(unittest.TestCase):
    def sample(self):
        usage = dict(input_tokens=100, cached_input_tokens=80, output_tokens=10,
                     reasoning_output_tokens=3, total_tokens=110)
        return {"type": "token_usage_record", "timestamp": "2026-01-01T00:00:00Z",
                "payload": {"response_id": "r1", "usage": usage, "thread_token_usage": usage}}

    def run_rows(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "sample.jsonl"
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            return audit.analyze(p)[0]

    def test_duplicate_and_mirror_not_double_counted(self):
        r = self.sample()
        mirror = {"type": "event_msg", "timestamp": r["timestamp"], "payload": {
            "type": "token_count", "info": {"total_token_usage": r["payload"]["usage"]}}}
        s = self.run_rows([r, mirror, copy.deepcopy(r)])
        self.assertEqual(s["totals"]["total_tokens"], 110)
        self.assertEqual(s["totals"]["uncached_input_tokens"], 20)
        self.assertEqual(s["totals"]["non_reasoning_output_tokens"], 7)
        self.assertEqual(s["duplicate_usage_records_skipped"], 1)
        self.assertTrue(s["sum_matches_last_thread"])

    def test_conflicting_duplicate_rejected(self):
        r = self.sample()
        altered = copy.deepcopy(r)
        altered["payload"]["usage"]["input_tokens"] = 200
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.run_rows([r, altered])

    def test_missing_usage_rejected(self):
        with self.assertRaisesRegex(ValueError, "No token_usage_record"):
            self.run_rows([{"type": "compacted", "timestamp": "2026-01-01", "payload": {}}])


class ReportTests(unittest.TestCase):
    def board(self, items):
        return {"source": "b.kicad_pcb", "violations": items, "unconnected_items": [], "schematic_parity": []}

    def violation(self, identity):
        return {"type": "clearance", "severity": "error", "description": "Too close",
                "items": [{"uuid": identity, "pos": {"x": 1, "y": 2}}]}

    def test_equal_counts_can_hide_regression(self):
        a, b = self.violation("a"), self.violation("b")
        s = drc.summarize(self.board([b]), self.board([a]))
        self.assertEqual(s["delta"]["added"], 1)
        self.assertEqual(s["delta"]["resolved"], 1)

    def test_multiset_preserves_duplicate_count(self):
        a = self.violation("a")
        s = drc.summarize(self.board([a]), self.board([a, a]))
        self.assertEqual(s["delta"]["resolved"], 1)
        self.assertEqual(s["delta"]["unchanged"], 1)

    def test_malformed_report_not_clean(self):
        with self.assertRaises(ValueError):
            drc.summarize({"source": "b.kicad_pcb", "violations": []})

    def test_erc_sheet_aggregation(self):
        s = drc.summarize({"source": "b.kicad_sch", "sheets": [
            {"path": "/power", "violations": [self.violation("a")]},
            {"path": "/analog", "violations": [self.violation("b")]}]})
        self.assertEqual(s["by_category"]["erc"], 2)

    def test_cross_source_baseline_rejected(self):
        before = self.board([])
        before["source"] = "different.kicad_pcb"
        with self.assertRaises(ValueError):
            drc.summarize(self.board([]), before)


if __name__ == "__main__":
    unittest.main()
