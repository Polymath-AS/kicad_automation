import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidationContractTests(unittest.TestCase):
    def test_reports_default_to_host_mounted_workspace(self):
        script = (ROOT / "scripts" / "validate-kicad.sh").read_text(encoding="utf-8")
        self.assertIn(
            "out=${KICAD_VALIDATION_REPORT_DIR:-/workspace/.kicad-automation/reports}",
            script,
        )
        self.assertIn("workspace_relative_report_dir", script)
        self.assertIn("summarize-kicad-report.py", script)
        self.assertIn("summary:$summary", script)
        self.assertNotIn("out=/runtime/reports", script)

    def test_workspace_automation_outputs_are_gitignored(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".kicad-automation/", gitignore.splitlines())


if __name__ == "__main__":
    unittest.main()
