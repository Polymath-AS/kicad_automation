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
    r"(?:\s+layer=(?P<layer>\S+))?(?:\s+(?:rot|rotation)=(?P<rotation>-?\d+(?:\.\d+)?))?"
    r"(?:\s+id=(?P<uuid>\S+))?"
)

_FULL_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


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
            # A display-truncated ID (for example ``681681d4...``) is not a
            # safe native deletion/mutation identity.
            if _FULL_UUID_RE.fullmatch(match.group("uuid")):
                item["uuid"] = match.group("uuid")
                item["uuid_source"] = "native"
            else:
                item["uuid_display"] = match.group("uuid")
        if match.group("layer"):
            item["layer"] = match.group("layer")
        if match.group("rotation") is not None:
            item["rotation"] = float(match.group("rotation"))
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
    seen: set[str] = set()
    for violation in _drc_violations(value):
        fingerprint = repr(sorted((str(key), repr(val)) for key, val in violation.items()))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
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
                **({"rotation_deg": change["rotation"]} if "rotation" in change else {}),
            })
            moved += 1
        return {"moved_footprints": moved}

    def restore(self, snapshot: Mapping[str, Any]) -> None:
        for item in snapshot.get("footprints", ()):
            position = item.get("position", item)
            arguments = {
                "reference": item.get("reference"),
                "x_mm": position.get("x_mm", position.get("x")),
                "y_mm": position.get("y_mm", position.get("y")),
            }
            if "rotation" in item:
                arguments["rotation_deg"] = item["rotation"]
            self.adapter.checked_mutation("pcb_move_footprint", arguments)

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
        payload = _embedded_json(response)
        current = _drc_signature(payload)
        if not current and not (isinstance(payload, Mapping) and any(
            key in payload for key in ("violations", "metadata", "evidence")
        )):
            return False
        if baseline is None:
            return True
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
