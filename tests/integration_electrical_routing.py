"""Pinned KiCadRoutingTools electrical fixture regression.

Run inside the routing image.  The source fixtures are read-only; each
operation is validated on an isolated candidate project.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import kicad_routing as routing


def main() -> int:
    workspace = Path("/workspace")
    jobs = Path("/jobs/electrical-fixtures")
    root = Path("/opt/KiCadRoutingTools")
    cases = {
        "diff": workspace / "routing-plans/krt-diff.json",
        "plane": workspace / "routing-plans/krt-plane.json",
    }
    reports = {}
    for name, plan_path in cases.items():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        result = routing.run_job(plan, workspace, jobs, root)
        assert result["status"] in {"candidate_clean", "needs_review"}, result
        assert result["source_unchanged"] and not result["applied"], result
        assert not result["comparison"]["regressed"], result
        candidate = Path(result["candidate"])
        text = candidate.read_text(encoding="utf-8")
        if name == "diff":
            assert len(re.findall(r"\(segment\b", text)) >= 2, result
            assert "USB_D_P" in text and "USB_D_N" in text, result
            log = Path(result["steps"][-1]["log"]).read_text(encoding="utf-8")
            assert '"routed_diff_pairs": ["USB_D"]' in log, result
            assert '"outcome": "coupled"' in log, result
        else:
            assert "(zone" in text and "GND" in text, result
            log = Path(result["steps"][-1]["log"]).read_text(encoding="utf-8")
            assert '"complete": true' in log and '"plane_nets": ["GND"]' in log, result
        reports[name] = {
            "status": result["status"], "job_id": result["job_id"],
            "comparison": result["comparison"], "candidate": result["candidate"],
        }
    print(json.dumps({"status": "pass", "cases": reports}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
