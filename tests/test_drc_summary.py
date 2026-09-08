import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


drc = load_module("drc_summary", "skills/kicad-drc/scripts/summarize_checks.py")


class ReportTests(unittest.TestCase):
    def board(self, items):
        return {"source": "b.kicad_pcb", "violations": items, "unconnected_items": [], "schematic_parity": []}

    def violation(self, identity):
        return {"type": "clearance", "severity": "error", "description": "Too close",
                "items": [{"uuid": identity, "pos": {"x": 1, "y": 2}}]}

    def test_equal_counts_can_hide_regression(self):
        summary = drc.summarize(self.board([self.violation("b")]), self.board([self.violation("a")]))
        self.assertEqual(summary["delta"]["added"], 1)
        self.assertEqual(summary["delta"]["resolved"], 1)

    def test_multiset_preserves_duplicate_count(self):
        item = self.violation("a")
        summary = drc.summarize(self.board([item]), self.board([item, item]))
        self.assertEqual(summary["delta"]["resolved"], 1)
        self.assertEqual(summary["delta"]["unchanged"], 1)

    def test_erc_sheet_aggregation(self):
        summary = drc.summarize({"source": "b.kicad_sch", "sheets": [
            {"path": "/power", "violations": [self.violation("a")]},
            {"path": "/analog", "violations": [self.violation("b")]}]})
        self.assertEqual(summary["by_category"]["erc"], 2)


if __name__ == "__main__":
    unittest.main()
