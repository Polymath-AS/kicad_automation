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
    from kicad_live_adapter import LiveToolError, McpLiveAdapter, _embedded_json, _parse_text_result
except ImportError:
    from scripts.kicad_live_adapter import LiveToolError, McpLiveAdapter, _embedded_json, _parse_text_result


_TRACK_RE = re.compile(
    r"\((?P<x1>-?\d+(?:\.\d+)?)\s*,\s*(?P<y1>-?\d+(?:\.\d+)?)\)"
    r"\s*->\s*\((?P<x2>-?\d+(?:\.\d+)?)\s*,\s*(?P<y2>-?\d+(?:\.\d+)?)\)"
    r"\s*mm\s+layer=(?P<layer>\S+)\s+width=(?P<width>-?\d+(?:\.\d+)?)\s+mm"
    r"\s+net=(?P<net>.+?)(?:\s+id=(?P<uuid>[0-9a-fA-F-]{36}))?$"
)


def _layer(value: str) -> str:
    return {"BL_F_Cu": "F.Cu", "BL_B_Cu": "B.Cu", "F_Cu": "F.Cu", "B_Cu": "B.Cu"}.get(value, value)


def _records(response: Mapping[str, Any], *keys: str) -> list[Mapping[str, Any]] | None:
    """Extract structured IPC records when the upstream surface provides them."""
    try:
        payload = _embedded_json(response)
    except Exception:
        return None
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
            return value
    return None


def parse_live_tracks(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse structured KiCad tracks, with a loss-minimizing text fallback."""
    structured = _records(response, "tracks", "segments", "track_segments")
    if structured is not None:
        tracks: list[dict[str, Any]] = []
        for item in structured:
            start = item.get("start", item.get("from"))
            end = item.get("end", item.get("to"))
            if not isinstance(start, Mapping) or not isinstance(end, Mapping):
                continue
            track = {
                "start": {"x_mm": float(start.get("x_mm", start.get("x"))),
                           "y_mm": float(start.get("y_mm", start.get("y")))},
                "end": {"x_mm": float(end.get("x_mm", end.get("x"))),
                         "y_mm": float(end.get("y_mm", end.get("y")))},
                "layer": _layer(str(item.get("layer", "F.Cu"))),
                "width_mm": float(item.get("width_mm", item.get("width", 0.0))),
                "net": item.get("net", item.get("net_name", "")),
            }
            if item.get("uuid") or item.get("id"):
                track["uuid"] = str(item.get("uuid") or item.get("id"))
            tracks.append(track)
        return tracks
    text = _parse_text_result(response)
    tracks: list[dict[str, Any]] = []
    for match in _TRACK_RE.finditer(text):
        net = re.sub(r"\s+id=\S+$", "", match.group("net").strip())
        item = {
            "start": {"x_mm": float(match.group("x1")), "y_mm": float(match.group("y1"))},
            "end": {"x_mm": float(match.group("x2")), "y_mm": float(match.group("y2"))},
            "layer": _layer(match.group("layer")),
            "width_mm": float(match.group("width")),
            "net": net,
        }
        if match.group("uuid"):
            item["uuid"] = match.group("uuid")
        tracks.append(item)
    return tracks


def parse_live_vias(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse via records; unsupported textual data is explicitly empty."""
    structured = _records(response, "vias", "via")
    if structured is None:
        return []
    result: list[dict[str, Any]] = []
    for item in structured:
        position = item.get("position", item)
        if not isinstance(position, Mapping):
            continue
        via = {
            "position": {"x_mm": float(position.get("x_mm", position.get("x"))),
                          "y_mm": float(position.get("y_mm", position.get("y")))},
            "net": item.get("net", item.get("net_name", "")),
            "layers": tuple(str(layer) for layer in item.get("layers", ())),
            "diameter_mm": float(item.get("diameter_mm", item.get("diameter", 0.0))),
            "drill_mm": float(item.get("drill_mm", item.get("drill", 0.0))),
        }
        if item.get("uuid") or item.get("id"):
            via["uuid"] = str(item.get("uuid") or item.get("id"))
        result.append(via)
    return result


def _violation_records(value: Any) -> list[Mapping[str, Any]]:
    """Collect one complete violation record per finding from MCP envelopes."""
    if isinstance(value, Mapping):
        direct = value.get("violations")
        if isinstance(direct, list):
            return [item for item in direct if isinstance(item, Mapping)]
        if isinstance(direct, Mapping):
            result: list[Mapping[str, Any]] = []
            for items in direct.values():
                if isinstance(items, list):
                    result.extend(item for item in items if isinstance(item, Mapping))
            if result:
                return result
        result = []
        for child in value.values():
            result.extend(_violation_records(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_violation_records(child))
        return result
    return []


class McpCopperPromotion:
    """Bind the generic transaction to the pinned live PCB IPC surface."""

    def __init__(self, adapter: McpLiveAdapter, *, restore_saved: Any | None = None):
        self.adapter = adapter
        self._restore_saved = restore_saved
        self._save_completed = False

    def read_board(self) -> dict[str, Any]:
        vias: list[dict[str, Any]] = []
        try:
            vias = parse_live_vias(self.adapter.call("pcb_get_vias"))
        except LiveToolError:
            # KiCad 10.0.4 deployments may not expose a separate via listing;
            # retain an explicit empty/unsupported representation rather than
            # inventing identities.
            vias = []
        return {"tracks": parse_live_tracks(self.adapter.call("pcb_get_tracks")), "vias": vias}

    def snapshot(self) -> dict[str, Any]:
        return self.read_board()

    def apply_delta(self, delta: CopperDelta) -> dict[str, Any]:
        # Preflight the complete delta before the first IPC write.  A via
        # rejection after track creation would violate atomicity.
        if delta.add_vias or delta.changed_segments or delta.changed_vias or delta.remove_uuids:
            raise ValueError("pinned adapter only supports additive track promotion with verified readback")
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
        return {"added_tracks": len(delta.add_segments)}

    def save(self) -> bool:
        text = _parse_text_result(self.adapter.checked_mutation("pcb_save"))
        ok = "success" in text.casefold() or "saved" in text.casefold()
        if ok:
            self._save_completed = True
        return ok

    def reopen(self) -> bool:
        # pcb_revert reloads the last saved document through KiCad IPC.
        self.adapter.checked_mutation("pcb_revert")
        return True

    def restore(self, _snapshot: Mapping[str, Any]) -> None:
        # A failed pre-save mutation is discarded by pcb_revert.  Once a save
        # has succeeded, callers must provide an explicit saved-source restore
        # callback; silently claiming rollback would be unsafe.
        if self._save_completed:
            if self._restore_saved is None:
                raise RuntimeError("saved-source copper restoration is unavailable on pinned IPC surface")
            self._restore_saved(_snapshot)
            return
        self.reopen()

    def validate(self, baseline: Mapping[str, int] | None = None) -> bool:
        response = self.adapter.call("run_drc", {"save_report": False})
        payload = _embedded_json(response)
        if not isinstance(payload, Mapping):
            return False
        violations = _violation_records(payload)
        if not violations:
            # A valid clean report contains an explicit empty list; a missing
            # report is malformed and must not be treated as clean.
            if isinstance(payload, Mapping) and any(key in payload for key in ("violations", "metadata", "evidence")):
                violations = []
            else:
                return False
        if not isinstance(violations, list):
            return False
        current: dict[str, int] = {}
        for violation in violations:
            if not isinstance(violation, Mapping):
                return False
            key = json.dumps({k: violation.get(k) for k in ("type", "rule", "description", "references")},
                             sort_keys=True, default=str)
            current[key] = current.get(key, 0) + 1
        if baseline is None:
            return True
        return all(count <= baseline.get(key, 0) for key, count in current.items())

    def promotion(self) -> LivePromotion:
        self._save_completed = False
        raw = _embedded_json(self.adapter.call("run_drc", {"save_report": False}))
        baseline: dict[str, int] = {}
        if isinstance(raw, Mapping):
            for violation in _violation_records(raw):
                key = json.dumps({k: violation.get(k) for k in ("type", "rule", "description", "references")},
                                 sort_keys=True, default=str)
                baseline[key] = baseline.get(key, 0) + 1
        return LivePromotion(
            read_board=self.read_board,
            snapshot=self.snapshot,
            apply_delta=self.apply_delta,
            restore=self.restore,
            save=self.save,
            reopen=self.reopen,
            validate=lambda: self.validate(baseline),
        )


__all__ = ["McpCopperPromotion", "parse_live_tracks", "parse_live_vias"]
