#!/usr/bin/env python3
"""Disposable pinned-KiCad live constrained-placement regression."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.kicad_live_adapter import default_live_adapter
from scripts.kicad_live_placement import McpPlacementPromotion
from scripts.kicad_mcp_client import DEFAULT_TOKEN, DEFAULT_URL
from scripts.kicad_promotion import board_digest


def main() -> int:
    adapter = default_live_adapter(
        os.environ.get("KICAD_MCP_URL", DEFAULT_URL),
        os.environ.get("KICAD_MCP_AUTH_TOKEN", DEFAULT_TOKEN),
    )
    # AGENTS.md preflight: server/project/board are queried before mutation.
    adapter.call("kicad_get_server_info")
    adapter.call("kicad_get_project_info")
    adapter.call("pcb_get_board_summary")
    bridge = McpPlacementPromotion(adapter)
    before = bridge.read_board()
    candidate = json.loads(json.dumps(before))
    j1 = next(item for item in candidate["footprints"] if item["reference"] == "J1")
    j1["position"] = {"x_mm": 35.0, "y_mm": 30.0}
    result = bridge.promotion().promote(
        candidate,
        expected_source_hash=board_digest(before),
        candidate_validate=lambda board: any(
            item.get("reference") == "J1" and item.get("position", {}).get("x_mm") == 35.0
            for item in board["footprints"]
        ),
    )
    if result.get("status") != "success":
        raise AssertionError(result)
    after = bridge.read_board()
    moved = next(item for item in after["footprints"] if item["reference"] == "J1")
    assert moved["position"] == {"x_mm": 35.0, "y_mm": 30.0}
    assert result["saved"] is True and result["dirty"] is False
    assert result["verified_effects"]["readback_verified"] is True
    print(json.dumps({
        "status": result["status"],
        "saved": result["saved"],
        "dirty": result["dirty"],
        "readback_verified": result["verified_effects"]["readback_verified"],
        "reference": "J1",
        "position": moved["position"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
