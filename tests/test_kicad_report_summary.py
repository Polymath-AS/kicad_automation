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


summary = load_module("summarize_kicad_report", "scripts/summarize_kicad_report.py")


class KicadReportSummaryTests(unittest.TestCase):
    def test_combines_drc_categories_and_extracts_references(self):
        report = {
            "violations": [
                {
                    "type": "hole_clearance",
                    "severity": "error",
                    "description": "Too close",
                    "items": [{"description": "Pad A12 [GND] of J1 on F.Cu", "uuid": "a"}],
                }
            ],
            "unconnected_items": [
                {
                    "type": "unconnected_items",
                    "severity": "warning",
                    "description": "Missing connection",
                    "items": [{"description": "Pad 1 [+3V3] of C5 on F.Cu", "uuid": "b"}],
                }
            ],
            "schematic_parity": [],
        }
        result = summary.summarize(report)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["by_severity"], {"error": 1, "warning": 1})
        self.assertEqual(result["by_type"], {"hole_clearance": 1, "unconnected_items": 1})
        self.assertEqual(result["references"], ["C5", "J1"])

    def test_aggregates_erc_sheets_and_limits_details(self):
        violation = {
            "type": "pin_not_connected",
            "severity": "error",
            "description": "Pin not connected",
            "items": [{"description": "Symbol U2 Pin 15 [Input]", "pos": {"x": 1, "y": 2}}],
        }
        result = summary.summarize(
            {"sheets": [{"path": "/power", "violations": [violation, violation]}]},
            limit=1,
        )
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["references"], ["U2"])
        self.assertEqual(result["top_findings"][0]["sheet"], "/power")
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
