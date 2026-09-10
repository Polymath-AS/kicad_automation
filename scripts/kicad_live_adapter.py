#!/usr/bin/env python3
"""Small high-level adapters for the pinned KiCad MCP Pro surface.

The upstream server intentionally keeps ``sch_add_no_connect`` coordinate
based and reports KiCad 10 ratsnest limitations as text.  This adapter keeps
those transport details at one boundary: callers use named schematic pins and
receive structured fallback data, while the underlying MCP calls remain the
supported operations.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Callable, Mapping

try:
    from kicad_contracts import DrcExclusionFilter, DocumentState, OperationResult, ratsnest_fallback, select_drc_violations
except ImportError:  # package import from repository root
    from scripts.kicad_contracts import DrcExclusionFilter, DocumentState, OperationResult, ratsnest_fallback, select_drc_violations


class LiveToolError(RuntimeError):
    """A domain or transport failure returned by the MCP server."""


@dataclass(frozen=True)
class SchematicSymbol:
    reference: str
    library: str
    symbol_name: str
    x_mm: float
    y_mm: float
    rotation: int = 0
    unit: int = 1


_SYMBOL_RE = re.compile(
    r"^- (?P<reference>\S+) .*? (?P<lib>[A-Za-z0-9_]+):(?P<name>\S+) @ "
    r"\((?P<x>-?[0-9.]+), (?P<y>-?[0-9.]+)\) rot=(?P<rot>-?\d+) unit=(?P<unit>\d+)"
)
_PIN_RE = re.compile(r"^- Pin (?P<pin>\S+): \((?P<x>-?[0-9.]+), (?P<y>-?[0-9.]+)\) mm")


def _parse_text_result(response: Mapping[str, Any]) -> str:
    result = response.get("result", response)
    if isinstance(result, Mapping):
        if result.get("isError"):
            raise LiveToolError(str(result))
        structured = result.get("structuredContent")
        if isinstance(structured, Mapping):
            value = structured.get("result", structured)
            if isinstance(value, str):
                return value
        content = result.get("content")
        if isinstance(content, list):
            text = next((item.get("text") for item in content
                         if isinstance(item, Mapping) and isinstance(item.get("text"), str)), None)
            if text is not None:
                return text
    raise LiveToolError("MCP response did not contain a textual result")


def _embedded_json(response: Mapping[str, Any]) -> Any:
    result = response.get("result", response)
    if isinstance(result, Mapping):
        structured = result.get("structuredContent")
        if isinstance(structured, Mapping):
            value = structured.get("result", structured)
            if isinstance(value, (Mapping, list)):
                return value
    text = _parse_text_result(response)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Verdict tools put their machine-readable payload in the text field,
        # occasionally after a short human preamble.  Find the first object.
        start = text.find("{")
        if start >= 0:
            try:
                return json.loads(text[start:])
            except json.JSONDecodeError:
                pass
    return text


def parse_schematic_symbols(response: Mapping[str, Any]) -> list[SchematicSymbol]:
    """Parse the stable symbol inspection text emitted by MCP Pro 3.34.0."""
    text = _parse_text_result(response)
    symbols: list[SchematicSymbol] = []
    for line in text.splitlines():
        match = _SYMBOL_RE.match(line.strip())
        if match is None:
            continue
        symbols.append(SchematicSymbol(
            reference=match.group("reference"), library=match.group("lib"),
            symbol_name=match.group("name"), x_mm=float(match.group("x")),
            y_mm=float(match.group("y")), rotation=int(match.group("rot")),
            unit=int(match.group("unit")),
        ))
    return symbols


def parse_pin_positions(response: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    for line in _parse_text_result(response).splitlines():
        match = _PIN_RE.match(line.strip())
        if match:
            positions[match.group("pin")] = (float(match.group("x")), float(match.group("y")))
    return positions


def _finding_ids(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        result: set[str] = set()
        for key, item in value.items():
            if key in {"id", "uuid"} and isinstance(item, str):
                result.add(item)
            result.update(_finding_ids(item))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_finding_ids(item))
        return result
    return set()


def _fallback_unconnected_records(value: Any) -> list[Mapping[str, Any]]:
    """Normalize KiCad 10 get_unconnected_nets text/JSON into client records."""
    if isinstance(value, Mapping):
        for key in ("unconnected_nets", "nets", "endpoints", "items"):
            records = value.get(key)
            if isinstance(records, list):
                return [item for item in records if isinstance(item, Mapping)]
        return []
    if isinstance(value, str):
        records: list[Mapping[str, Any]] = []
        for line in value.splitlines():
            line = line.strip()
            if not line.startswith("-"):
                continue
            text = line[1:].strip()
            records.append({"description": text})
        return records
    return []


class McpLiveAdapter:
    """High-level calls over the repository MCP client request function."""

    def __init__(
        self,
        call: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
        revision: Callable[[], str] | None = None,
        save: Callable[[], bool] | None = None,
    ):
        self._call = call
        self._revision = revision
        self._save = save

    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        response = self._call(name, arguments or {})
        result = response.get("result", response)
        if isinstance(result, Mapping) and result.get("isError"):
            raise LiveToolError(_parse_text_result(response))
        return response

    def checked_mutation(self, name: str, arguments: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """Reject domain refusals that upstream incorrectly returns as transport success."""
        response = self.call(name, arguments)
        result = response.get("result", response)
        structured = result.get("structuredContent") if isinstance(result, Mapping) else None
        if isinstance(structured, Mapping) and structured.get("status") in {"failure", "partial"}:
            raise LiveToolError(f"{name} returned domain status {structured.get('status')}: {structured}")
        text = _parse_text_result(response).casefold()
        refusal_markers = ("refusing", "refused", "aborted", "failed", "failure", "could not")
        if any(marker in text for marker in refusal_markers):
            raise LiveToolError(f"{name} refused the mutation: {_parse_text_result(response)}")
        return response

    def resolve_pin(self, reference: str, pin: str) -> dict[str, Any]:
        symbols = [item for item in parse_schematic_symbols(self.call("sch_get_symbols"))
                   if item.reference == reference]
        if not symbols:
            raise LiveToolError(f"schematic symbol {reference} was not found")
        symbol = symbols[0]
        positions = parse_pin_positions(self.call("sch_get_pin_positions", {
            "library": symbol.library, "symbol_name": symbol.symbol_name,
            "x_mm": symbol.x_mm, "y_mm": symbol.y_mm,
            "rotation": symbol.rotation, "unit": symbol.unit,
        }))
        if pin not in positions:
            raise LiveToolError(f"pin {reference}.{pin} was not found in symbol data")
        x_mm, y_mm = positions[pin]
        return {"reference": reference, "pin": pin, "canonical_pin": pin,
                "x_mm": x_mm, "y_mm": y_mm,
                "library": symbol.library, "symbol_name": symbol.symbol_name}

    def current_revision(self) -> str | None:
        if self._revision is not None:
            return self._revision()
        return None

    def add_no_connect_by_pin(
        self,
        reference: str,
        pin: str,
        *,
        run_erc: bool = True,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        before_revision = self.current_revision()
        if expected_revision is not None and before_revision != expected_revision:
            return {
                "status": "failure", "operation": "sch_add_no_connect", "saved": False,
                "dirty": False, "document_revision": before_revision,
                "error": "stale document revision; mutation was rejected before write",
            }
        before = _embedded_json(self.call("run_erc", {"save_report": False})) if run_erc else None
        resolved = self.resolve_pin(reference, pin)
        result = self.checked_mutation("sch_add_no_connect", {
            "x_mm": resolved["x_mm"], "y_mm": resolved["y_mm"], "snap_to_grid": False,
        })
        after = _embedded_json(self.call("run_erc", {"save_report": False})) if run_erc else None
        after_revision = self.current_revision()
        saved = bool(self._save()) if self._save is not None else False
        if self._save is not None and not saved:
            return {
                "status": "failure", "operation": "sch_add_no_connect", "saved": False,
                "dirty": True, "document_revision": after_revision,
                "resolved_pin": resolved,
                "error": "schematic mutation was applied but its save postcondition failed",
            }
        before_ids = _finding_ids(before)
        after_ids = _finding_ids(after)
        return {
            "status": "success", "operation": "sch_add_no_connect", "saved": saved,
            "dirty": not saved, "document_revision": after_revision, "resolved_pin": resolved,
            "erc": {"before_finding_ids": sorted(before_ids), "after_finding_ids": sorted(after_ids),
                     "removed_finding_ids": sorted(before_ids - after_ids),
                     "unrelated_finding_ids": sorted(after_ids - before_ids)},
            "mcp_result": _parse_text_result(result),
        }

    def ratsnest(self) -> dict[str, Any]:
        try:
            native = self.call("pcb_get_ratsnest")
            native_text = _parse_text_result(native)
        except LiveToolError as exc:
            # KiCad 10 deployments vary between a textual limitation and a
            # transport-level "tool unavailable" response.  Both select the
            # same supported endpoint fallback.
            native_text = str(exc)
        if "not exposed" not in native_text.lower() and "unavailable" not in native_text.lower():
            return {"source": "native", "available": True, "limitations": [], "result": native_text}
        try:
            unconnected = _embedded_json(self.call("get_unconnected_nets"))
        except LiveToolError as exc:
            unconnected = {"error": str(exc)}
        try:
            drc = _embedded_json(self.call("run_drc", {"save_report": False}))
        except LiveToolError as exc:
            drc = {"error": str(exc)}
        # Verdict reports put the KiCad JSON report under evidence.  Preserve
        # the full source payload and extract only the actionable list here.
        drc_report: Mapping[str, Any] = {}
        if isinstance(drc, Mapping):
            evidence = drc.get("evidence", [])
            if isinstance(evidence, list):
                for item in evidence:
                    if isinstance(item, Mapping) and isinstance(item.get("violations"), Mapping):
                        drc_report = item["violations"]
                        break
        endpoint_items: list[Mapping[str, Any]] = []
        if isinstance(drc_report.get("unconnected_items"), list):
            endpoint_items.extend(item for item in drc_report["unconnected_items"] if isinstance(item, Mapping))
        endpoint_items.extend(_fallback_unconnected_records(unconnected))
        fallback = ratsnest_fallback(endpoint_items, drc_report)
        fallback["source_payload"] = {"get_unconnected_nets": unconnected, "run_drc": drc}
        fallback["native_message"] = native_text
        return fallback

    def preview_drc_exclusions(self, selector: DrcExclusionFilter) -> dict[str, Any]:
        """Preview selected live DRC violations without calling the unsafe upstream writer."""
        report = _embedded_json(self.call("run_drc", {"save_report": False}))
        violations: list[Mapping[str, Any]] = []
        if isinstance(report, Mapping):
            metadata = report.get("metadata")
            if isinstance(metadata, Mapping) and isinstance(metadata.get("violations"), list):
                violations = [item for item in metadata["violations"] if isinstance(item, Mapping)]
            if not violations and isinstance(report.get("violations"), list):
                violations = [item for item in report["violations"] if isinstance(item, Mapping)]
        return select_drc_violations(violations, selector, dry_run=True)

    def execute_drc_exclusions(self, preview: Mapping[str, Any]) -> dict[str, Any]:
        """Fail closed until the live upstream tool accepts selected UUIDs and a preview ID."""
        return OperationResult(
            "failure", "drc_add_exclusions", DocumentState(), backend="live_ipc",
            verified_effects={"preview_id": preview.get("preview_id"), "mutated": False},
            error="pinned kicad-mcp-pro 3.34.0 exposes only unsafe all-violation DRC exclusions",
        ).as_dict()


def default_live_adapter(url: str, token: str, timeout: int = 120) -> McpLiveAdapter:
    try:
        from kicad_mcp_client import request
    except ImportError:
        from scripts.kicad_mcp_client import request

    def call(name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return request(url, token, "tools/call", {"name": name, "arguments": dict(arguments)}, timeout)

    def revision() -> str:
        payload = {
            "project": call("kicad_get_project_info", {}),
            "board": call("pcb_get_board_summary", {}),
            "symbols": call("sch_get_symbols", {}),
            # ERC includes persisted no-connect markers and therefore closes
            # the revision gap left by summary-only live APIs.
            "erc": call("run_erc", {"save_report": False}),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    return McpLiveAdapter(call, revision=revision)


__all__ = [
    "DrcExclusionFilter", "LiveToolError", "McpLiveAdapter", "SchematicSymbol", "default_live_adapter",
    "parse_pin_positions", "parse_schematic_symbols",
]
