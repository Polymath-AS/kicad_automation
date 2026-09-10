#!/usr/bin/env python3
"""MCP-backed callbacks for verified constrained footprint promotion.

The placement planner remains backend-neutral.  This adapter binds its small
position delta to the supported KiCad 10 IPC operations and restores every
changed footprint explicitly, including after a successful save.  That makes
placement promotion safe for a live document without pretending that
``pcb_revert`` can restore an already-saved source.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping

try:
    from kicad_live_adapter import McpLiveAdapter, _embedded_json, _parse_text_result
    from kicad_promotion import PlacementPromotion
except ImportError:
    from scripts.kicad_live_adapter import McpLiveAdapter, _embedded_json, _parse_text_result
    from scripts.kicad_promotion import PlacementPromotion


_FOOTPRINT_RE = re.compile(
    r"^-\s+(?P<reference>\S+)\s+\([^)]*\)\s+@\s+"
    r"\((?P<x>-?\d+(?:\.\d+)?),\s*(?P<y>-?\d+(?:\.\d+)?)\)\s+mm"
    r"(?:\s+layer=(?P<layer>\S+))?(?:\s+id=(?P<uuid>\S+))?"
)


def parse_live_footprints(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse the stable footprint listing emitted by MCP Pro."""
    footprints: list[dict[str, Any]] = []
    for line in _parse_text_result(response).splitlines():
        match = _FOOTPRINT_RE.match(line.strip())
        if match is None:
            continue
        item: dict[str, Any] = {
            "reference": match.group("reference"),
            "position": {"x_mm": float(match.group("x")), "y_mm": float(match.group("y"))},
        }
        if match.group("uuid"):
            item["uuid"] = match.group("uuid")
        if match.group("layer"):
            item["layer"] = match.group("layer")
        footprints.append(item)
    return footprints


def _drc_violations(value: Any) -> list[Mapping[str, Any]]:
    """Collect structured DRC violations without depending on one verdict envelope."""
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        violations = value.get("violations")
        if isinstance(violations, list):
            found.extend(item for item in violations if isinstance(item, Mapping))
        elif isinstance(violations, Mapping):
            for items in violations.values():
                if isinstance(items, list):
                    found.extend(item for item in items if isinstance(item, Mapping))
        for item in value.values():
            if item is not violations:
                found.extend(_drc_violations(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_drc_violations(item))
    return found


def _drc_signature(value: Any) -> Counter[tuple[str, str, str, tuple[str, ...]]]:
    """Compare DRC identity, not coordinates that legitimately move with a footprint."""
    signature: Counter[tuple[str, str, str, tuple[str, ...]]] = Counter()
    for violation in _drc_violations(value):
        references = violation.get("references", ())
        if isinstance(references, str):
            references = (references,)
        elif not isinstance(references, (list, tuple, set)):
            references = ()
        key = (
            str(violation.get("type", violation.get("category", ""))),
            str(violation.get("rule", "")),
            str(violation.get("description", "")),
            tuple(sorted(str(item) for item in references)),
        )
        signature[key] += 1
    return signature


class McpPlacementPromotion:
    """Bind the shared placement transaction to live KiCad IPC."""

    def __init__(self, adapter: McpLiveAdapter):
        self.adapter = adapter

    def read_board(self) -> dict[str, Any]:
        return {"footprints": parse_live_footprints(self.adapter.call("pcb_get_footprints"))}

    def snapshot(self) -> dict[str, Any]:
        return self.read_board()

    def apply_delta(self, delta: Mapping[str, Any]) -> dict[str, Any]:
        moved = 0
        for change in delta.get("changed_footprints", ()):
            position = change.get("position", change)
            self.adapter.checked_mutation("pcb_move_footprint", {
                "reference": change.get("reference"),
                "x_mm": position.get("x_mm", position.get("x")),
                "y_mm": position.get("y_mm", position.get("y")),
                "rotation_deg": change.get("rotation", 0.0),
            })
            moved += 1
        return {"moved_footprints": moved}

    def restore(self, snapshot: Mapping[str, Any]) -> None:
        for item in snapshot.get("footprints", ()):
            position = item.get("position", item)
            self.adapter.checked_mutation("pcb_move_footprint", {
                "reference": item.get("reference"),
                "x_mm": position.get("x_mm", position.get("x")),
                "y_mm": position.get("y_mm", position.get("y")),
                "rotation_deg": item.get("rotation", 0.0),
            })

    def save(self) -> bool:
        text = _parse_text_result(self.adapter.checked_mutation("pcb_save"))
        return "success" in text.casefold() or "saved" in text.casefold()

    def reopen(self) -> bool:
        self.adapter.checked_mutation("pcb_revert")
        return True

    def validate(self, baseline: Counter[tuple[str, str, str, tuple[str, ...]]] | None = None) -> bool:
        response = self.adapter.call("run_drc", {"save_report": False})
        result = response.get("result", response)
        if isinstance(result, Mapping) and result.get("isError"):
            return False
        if baseline is None:
            return True
        current = _drc_signature(_embedded_json(response))
        # Existing findings are allowed; a new identity or increased count is not.
        return all(current[key] <= baseline[key] for key in current)

    def promotion(self) -> PlacementPromotion:
        baseline = _drc_signature(_embedded_json(self.adapter.call("run_drc", {"save_report": False})))
        return PlacementPromotion(
            read_board=self.read_board,
            snapshot=self.snapshot,
            apply_delta=self.apply_delta,
            restore=self.restore,
            save=self.save,
            reopen=self.reopen,
            validate=lambda: self.validate(baseline),
        )


__all__ = ["McpPlacementPromotion", "parse_live_footprints"]
