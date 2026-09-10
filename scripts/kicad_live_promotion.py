#!/usr/bin/env python3
"""MCP-backed callbacks for promoting a reviewed copper candidate.

The candidate router remains file-isolated.  This adapter is deliberately
small: it translates only the supported ``pcb_add_track``/``pcb_save``/
``pcb_revert`` IPC operations into the shared :class:`LivePromotion` contract.
It is useful for disposable integration fixtures and leaves policy decisions
(candidate validation, stale digest, and rollback) to that contract.
"""

from __future__ import annotations

import re
import json
from typing import Any, Mapping

try:
    from kicad_promotion import CopperDelta, LivePromotion
except ImportError:
    from scripts.kicad_promotion import CopperDelta, LivePromotion

try:
    from kicad_live_adapter import McpLiveAdapter, _embedded_json, _parse_text_result
except ImportError:
    from scripts.kicad_live_adapter import McpLiveAdapter, _embedded_json, _parse_text_result


_TRACK_RE = re.compile(
    r"\((?P<x1>-?\d+(?:\.\d+)?)\s*,\s*(?P<y1>-?\d+(?:\.\d+)?)\)"
    r"\s*->\s*\((?P<x2>-?\d+(?:\.\d+)?)\s*,\s*(?P<y2>-?\d+(?:\.\d+)?)\)"
    r"\s*mm\s+layer=(?P<layer>\S+)\s+width=(?P<width>-?\d+(?:\.\d+)?)\s+mm"
    r"\s+net=(?P<net>\S+)"
)


def _layer(value: str) -> str:
    return {"BL_F_Cu": "F.Cu", "BL_B_Cu": "B.Cu"}.get(value, value)


def parse_live_tracks(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse the stable human-readable track listing without relying on IDs."""
    text = _parse_text_result(response)
    tracks: list[dict[str, Any]] = []
    for match in _TRACK_RE.finditer(text):
        tracks.append({
            "start": {"x_mm": float(match.group("x1")), "y_mm": float(match.group("y1"))},
            "end": {"x_mm": float(match.group("x2")), "y_mm": float(match.group("y2"))},
            "layer": _layer(match.group("layer")),
            "width_mm": float(match.group("width")),
            "net": match.group("net"),
        })
    return tracks


class McpCopperPromotion:
    """Bind the generic transaction to the pinned live PCB IPC surface."""

    def __init__(self, adapter: McpLiveAdapter):
        self.adapter = adapter

    def read_board(self) -> dict[str, Any]:
        return {"tracks": parse_live_tracks(self.adapter.call("pcb_get_tracks")), "vias": []}

    def snapshot(self) -> dict[str, Any]:
        return self.read_board()

    def apply_delta(self, delta: CopperDelta) -> dict[str, Any]:
        for segment in delta.add_segments:
            start = segment.get("start", segment.get("from", {}))
            end = segment.get("end", segment.get("to", {}))
            self.adapter.checked_mutation("pcb_add_track", {
                "x1_mm": start.get("x_mm", start.get("x")),
                "y1_mm": start.get("y_mm", start.get("y")),
                "x2_mm": end.get("x_mm", end.get("x")),
                "y2_mm": end.get("y_mm", end.get("y")),
                "layer": segment.get("layer", "F_Cu").replace(".", "_"),
                "width_mm": segment.get("width_mm", segment.get("width", 0.25)),
                "net_name": segment.get("net", segment.get("net_name", "")),
            })
        if delta.add_vias:
            raise ValueError("the pinned adapter does not expose a safe via readback contract")
        return {"added_tracks": len(delta.add_segments)}

    def save(self) -> bool:
        text = _parse_text_result(self.adapter.checked_mutation("pcb_save"))
        return "success" in text.casefold() or "saved" in text.casefold()

    def reopen(self) -> bool:
        # pcb_revert reloads the last saved document through KiCad IPC.
        self.adapter.checked_mutation("pcb_revert")
        return True

    def restore(self, _snapshot: Mapping[str, Any]) -> None:
        # A failed pre-save mutation is discarded by pcb_revert.  Once a save
        # has succeeded, callers must provide an explicit saved-source restore
        # callback; silently claiming rollback would be unsafe.
        self.reopen()

    def validate(self) -> bool:
        response = self.adapter.call("run_drc", {"save_report": False})
        payload = _embedded_json(response)
        if isinstance(payload, Mapping):
            metadata = payload.get("metadata")
            if isinstance(metadata, Mapping) and isinstance(metadata.get("violations"), list):
                for violation in metadata["violations"]:
                    if not isinstance(violation, Mapping) or violation.get("type") != "unconnected_items":
                        continue
                    if "USB_D_P" in json.dumps(violation, sort_keys=True):
                        return False
                return True
        text = _parse_text_result(response)
        return "USB_D_P" not in text or "unconnected" not in text.casefold()

    def promotion(self) -> LivePromotion:
        return LivePromotion(
            read_board=self.read_board,
            snapshot=self.snapshot,
            apply_delta=self.apply_delta,
            restore=self.restore,
            save=self.save,
            reopen=self.reopen,
            validate=self.validate,
        )


__all__ = ["McpCopperPromotion", "parse_live_tracks"]
