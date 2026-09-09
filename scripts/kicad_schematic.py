#!/usr/bin/env python3
"""Typed schematic-side adapters for the file-backed KiCad 10 tool surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

try:
    from kicad_contracts import (
        DocumentState,
        OperationResult,
        canonical_pin_name,
        erc_coordinate_mm,
        resolve_pin,
        validate_schematic_request,
    )
except ImportError:  # package import from repository root
    from scripts.kicad_contracts import (
        DocumentState,
        OperationResult,
        canonical_pin_name,
        erc_coordinate_mm,
        resolve_pin,
        validate_schematic_request,
    )


@dataclass(frozen=True)
class NoConnectRequest:
    reference: str | None = None
    pin: str | None = None
    x_mm: float | None = None
    y_mm: float | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NoConnectRequest":
        if "reference" in value or "pin" in value:
            if not value.get("reference") or value.get("pin") is None:
                raise ValueError("reference and pin are required together")
            return cls(str(value["reference"]), str(value["pin"]))
        if "x_mm" not in value or "y_mm" not in value:
            raise ValueError("no-connect requires {reference, pin} or {x_mm, y_mm}")
        unit = str(value.get("unit", "mm"))
        return cls(x_mm=erc_coordinate_mm(value["x_mm"], unit=unit),
                   y_mm=erc_coordinate_mm(value["y_mm"], unit=unit))


def no_connect_pin_input(
    request: NoConnectRequest,
    symbols: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve ``J1.SH`` to the exact terminal position expected by MCP Pro."""
    if request.reference is None:
        return {"x_mm": float(request.x_mm), "y_mm": float(request.y_mm)}
    pin = resolve_pin(symbols, request.reference, str(request.pin))
    position = pin.get("position") or pin.get("pos")
    if not isinstance(position, Mapping):
        raise ValueError(f"pin {request.reference}.{request.pin} has no position")
    return {
        "reference": request.reference,
        "pin": str(request.pin),
        "canonical_pin": canonical_pin_name(pin),
        "x_mm": erc_coordinate_mm(position.get("x_mm", position.get("x", 0)),
                                    unit=str(position.get("unit", "mm"))),
        "y_mm": erc_coordinate_mm(position.get("y_mm", position.get("y", 0)),
                                    unit=str(position.get("unit", "mm"))),
    }


def add_no_connect(
    request: NoConnectRequest,
    symbols: Iterable[Mapping[str, Any]],
    mutate: Callable[[dict[str, Any]], Mapping[str, Any] | None],
    *,
    state: DocumentState | None = None,
    save: Callable[[], bool] | None = None,
    snapshot: Callable[[], Any] | None = None,
    restore: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    """Resolve and apply a no-connect with truthful save state."""
    current = state or DocumentState()
    before = snapshot() if snapshot is not None else None
    try:
        payload = no_connect_pin_input(request, symbols)
        effects = mutate(payload) or {}
        saved = False
        if save is not None:
            saved = bool(save())
            if not saved:
                raise RuntimeError("save postcondition failed")
        next_state = DocumentState(not saved, saved, current.document_revision + 1)
        return OperationResult("success", "sch_add_no_connect", next_state,
                               verified_effects={"pin": payload, **dict(effects)}, backend="file_backed").as_dict()
    except Exception as exc:
        if restore is not None and snapshot is not None:
            restore(before)
        return OperationResult("failure", "sch_add_no_connect", current,
                               backend="file_backed", error=str(exc)).as_dict()


def build_circuit(
    request: Mapping[str, Any],
    mutate: Callable[[Mapping[str, Any]], Mapping[str, Any] | None],
    *,
    state: DocumentState | None = None,
    save: Callable[[], bool] | None = None,
    expected_revision: int | None = None,
    snapshot: Callable[[], Any] | None = None,
    restore: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    """Validate the complete nested request before any schematic mutation."""
    current = state or DocumentState()
    before = snapshot() if snapshot is not None else None
    if expected_revision is not None and expected_revision != current.document_revision:
        return OperationResult("failure", "sch_build_circuit", current, backend="file_backed",
                               error=f"stale document revision: expected {expected_revision}, current {current.document_revision}").as_dict()
    try:
        validate_schematic_request(request)
        effects = mutate(request) or {}
        saved = bool(save()) if save else False
        if save is not None and not saved:
            raise RuntimeError("save postcondition failed")
        next_state = DocumentState(not saved, saved, current.document_revision + 1)
        return OperationResult("success", "sch_build_circuit", next_state,
                               verified_effects=effects, backend="file_backed").as_dict()
    except Exception as exc:
        if restore is not None and snapshot is not None:
            restore(before)
        return OperationResult("failure", "sch_build_circuit", current, backend="file_backed", error=str(exc)).as_dict()


def analyze_net_compilation(
    *,
    schematic: str | None = None,
    current_schematic: Callable[[], str] | None = None,
    analyze: Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Analyze the current schematic by default; explicit paths remain supported."""
    path = schematic
    if path is None:
        if current_schematic is None:
            raise ValueError("current schematic is unavailable; pass schematic explicitly")
        path = current_schematic()
    result = dict(analyze(path))
    result.setdefault("schematic", path)
    result.setdefault("source", "current" if schematic is None else "requested")
    return result
