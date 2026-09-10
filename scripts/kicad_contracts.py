#!/usr/bin/env python3
"""Shared contracts for the KiCad automation MCP adapter.

The upstream MCP server owns the KiCad document.  This module deliberately does
not parse or write KiCad files; it provides the small, deterministic contracts
needed at the boundary: capability discovery, truthful operation envelopes,
revision checks, stable object identifiers and request schemas.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
import hashlib
from pathlib import Path, PureWindowsPath
import re
from typing import Any, Callable, Iterable, Literal, Mapping
import uuid


Backend = Literal["live_ipc", "file_backed", "cli", "unavailable"]
OperationStatus = Literal["success", "partial", "failure"]


class RevisionConflict(RuntimeError):
    """Raised before a mutation when its document revision is stale."""


class ConstraintError(ValueError):
    """Raised when a request cannot satisfy a hard design constraint."""


class OperationFailure(RuntimeError):
    """Raised by a transaction callback to request an atomic rollback."""


@dataclass(frozen=True)
class ToolMetadata:
    """Stable discoverability metadata independent of write permission."""

    name: str
    backend: Backend
    available: bool
    writable: bool = False
    reason: str | None = None
    requires_experimental: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "backend": self.backend,
            "availability": "available" if self.available else "unavailable",
            "writable": self.writable,
            **({"reason": self.reason} if self.reason else {}),
        }


# This is intentionally a superset.  A client can cache one catalog while the
# server reports unavailable tools, rather than making profile changes look like
# API changes.  The catalog is also useful in offline contract tests.
STABLE_TOOL_CATALOG: tuple[ToolMetadata, ...] = (
    ToolMetadata("kicad_get_server_info", "live_ipc", True),
    ToolMetadata("kicad_get_project_info", "live_ipc", True),
    ToolMetadata("kicad_get_version", "live_ipc", True),
    ToolMetadata("kicad_create_new_project", "file_backed", True, True),
    ToolMetadata("pcb_get_board_summary", "live_ipc", True),
    ToolMetadata("pcb_get_footprints", "live_ipc", True),
    ToolMetadata("pcb_get_nets", "live_ipc", True),
    ToolMetadata("pcb_get_pads", "live_ipc", True),
    ToolMetadata("pcb_get_tracks", "live_ipc", True),
    ToolMetadata("pcb_get_shapes", "live_ipc", True),
    ToolMetadata("pcb_get_ratsnest", "live_ipc", True),
    ToolMetadata("pcb_sync_from_schematic", "live_ipc", True, True),
    ToolMetadata("pcb_move_footprint", "live_ipc", True, True),
    ToolMetadata("pcb_move_component", "live_ipc", True, True),
    ToolMetadata("pcb_route_trace", "live_ipc", True, True),
    ToolMetadata("route_from_pad_to_pad", "live_ipc", True, True,
                 "upstream exposes this helper only in experimental write mode", True),
    ToolMetadata("pcb_delete_items", "live_ipc", True, True),
    ToolMetadata("pcb_save", "live_ipc", True, True),
    ToolMetadata("pcb_set_board_outline", "live_ipc", True, True),
    ToolMetadata("pcb_set_design_rules", "live_ipc", True, True),
    ToolMetadata("sch_build_circuit", "file_backed", True, True),
    ToolMetadata("sch_add_no_connect", "file_backed", True, True),
    ToolMetadata("sch_get_symbols", "file_backed", True),
    ToolMetadata("sch_get_pin_positions", "file_backed", True),
    ToolMetadata("sch_analyze_net_compilation", "file_backed", True),
    ToolMetadata("run_erc", "cli", True),
    ToolMetadata("run_drc", "cli", True),
    ToolMetadata("get_unconnected_nets", "live_ipc", True),
)


def stable_tool_catalog(
    *,
    live_ipc: bool = True,
    file_backed: bool = True,
    cli: bool = True,
    writable: bool = True,
    operating_mode: str = "write",
) -> list[dict[str, Any]]:
    """Return every supported tool with stable backend/availability metadata."""
    enabled = {"live_ipc": live_ipc, "file_backed": file_backed, "cli": cli}
    result: list[dict[str, Any]] = []
    for tool in STABLE_TOOL_CATALOG:
        available = (tool.available and enabled.get(tool.backend, False)
                     and (not tool.requires_experimental or operating_mode == "experimental"))
        reason = tool.reason
        if not available and reason is None:
            reason = f"{tool.backend} backend is unavailable"
        item = ToolMetadata(
            tool.name,
            tool.backend,
            available,
            tool.writable and writable,
            reason,
        )
        result.append(item.as_dict())
    return result


def annotate_tools(tools: Iterable[Mapping[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    """Add stable metadata to an upstream ``tools/list`` response.

    Existing upstream schema fields are preserved.  Tools omitted by an upstream
    profile are appended as discoverable unavailable entries, which keeps write
    permission separate from catalog visibility.
    """
    kwargs.setdefault("operating_mode", os.environ.get("KICAD_MCP_OPERATING_MODE", "write"))
    metadata = {item["name"]: item for item in stable_tool_catalog(**kwargs)}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in tools:
        item = dict(raw)
        name = str(item.get("name", ""))
        if name in metadata:
            item["backend"] = metadata[name]["backend"]
            item["availability"] = metadata[name]["availability"]
            item["writable"] = metadata[name]["writable"]
        elif name:
            # Preserve discoverability for upstream additions while still
            # returning the same metadata shape.  Exact backend assignments are
            # reserved for the stable catalog above.
            backend: Backend = (
                "cli" if name.startswith(("run_", "validate_")) else
                "file_backed" if name.startswith("sch_") else
                "live_ipc" if name.startswith(("pcb_", "kicad_")) else
                "unavailable"
            )
            item.setdefault("backend", backend)
            item.setdefault("availability", "available")
            annotations = item.get("annotations")
            if not isinstance(annotations, Mapping):
                annotations = {}
            item.setdefault("writable", not bool(annotations.get("readOnlyHint", False)))
        result.append(item)
        seen.add(name)
    for name, item in metadata.items():
        if name not in seen:
            result.append({"name": name, "description": item.get("reason", ""), **item})
    return result


@dataclass(frozen=True)
class DocumentState:
    dirty: bool = False
    saved: bool = True
    document_revision: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "dirty": self.dirty,
            "saved": self.saved,
            "document_revision": self.document_revision,
        }


@dataclass
class OperationResult:
    """Truthful result envelope shared by all mutating operations."""

    status: OperationStatus
    operation: str
    state: DocumentState
    verified_effects: dict[str, Any] = field(default_factory=dict)
    backend: Backend = "live_ipc"
    blockers: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.status == "success"

    @property
    def partial(self) -> bool:
        return self.status == "partial"

    @property
    def is_error(self) -> bool:
        return self.status == "failure"

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "success": self.success,
            "partial": self.partial,
            "isError": self.is_error,
            "operation": self.operation,
            "backend": self.backend,
            "verified_effects": deepcopy(self.verified_effects),
            **self.state.as_dict(),
        }
        if self.blockers:
            result["blockers"] = deepcopy(self.blockers)
        if self.error:
            result["error"] = self.error
        return result


def operation_result(
    operation: str,
    *,
    state: DocumentState,
    verified_effects: Mapping[str, Any] | None = None,
    status: OperationStatus = "success",
    backend: Backend = "live_ipc",
    blockers: Iterable[Mapping[str, Any]] = (),
    error: str | None = None,
) -> dict[str, Any]:
    return OperationResult(
        status=status,
        operation=operation,
        state=state,
        verified_effects=dict(verified_effects or {}),
        backend=backend,
        blockers=[dict(item) for item in blockers],
        error=error,
    ).as_dict()


def transactional_delete(
    operation: str,
    identifiers: Iterable[str],
    *,
    snapshot: Callable[[], Any],
    delete: Callable[[list[str]], Mapping[str, Any] | None],
    verify: Callable[[list[str]], bool],
    restore: Callable[[Any], None],
    state: DocumentState,
    backend: Backend = "live_ipc",
) -> dict[str, Any]:
    """Delete exact UUIDs and never report contradictory transport/domain status."""
    ids = [str(value) for value in identifiers]
    if not ids:
        return operation_result(operation, state=state, status="failure", backend=backend,
                                error="at least one item UUID is required")
    before = snapshot()
    try:
        effects = delete(ids) or {}
        if not verify(ids):
            raise OperationFailure("delete postcondition verification failed")
        return operation_result(operation, state=DocumentState(True, False, state.document_revision + 1),
                                verified_effects={"deleted_uuids": ids, **dict(effects)}, backend=backend)
    except Exception as exc:
        restore(before)
        return operation_result(operation, state=state, status="failure", backend=backend,
                                verified_effects={"rolled_back": True, "deleted_uuids": []}, error=str(exc))


class RevisionStore:
    """Revision/dirty state with an atomic callback transaction.

    ``document`` is an adapter-owned snapshot (usually structured MCP data), not
    a KiCad file.  A caller supplies live-IPC apply/save callbacks when its
    backend supports them.  Revision validation always happens before apply.
    """

    def __init__(self, document: Any = None, *, revision: int = 0):
        self.document = deepcopy(document)
        self._saved_document = deepcopy(document)
        self._state = DocumentState(False, True, revision)

    @property
    def state(self) -> DocumentState:
        return self._state

    def check_revision(self, expected_revision: int | None) -> None:
        if expected_revision is not None and expected_revision != self._state.document_revision:
            raise RevisionConflict(
                f"stale document revision: expected {expected_revision}, "
                f"current {self._state.document_revision}"
            )

    def save(self, *, verify: Callable[[Any], bool] | None = None) -> DocumentState:
        if verify is not None and not verify(self.document):
            raise OperationFailure("save postcondition verification failed")
        self._saved_document = deepcopy(self.document)
        self._state = DocumentState(False, True, self._state.document_revision)
        return self._state

    def reload(self, *, saved: bool = True) -> Any:
        self.document = deepcopy(self._saved_document if saved else self.document)
        self._state = DocumentState(False, True, self._state.document_revision)
        return deepcopy(self.document)

    def transact(
        self,
        operation: str,
        callback: Callable[[Any], Mapping[str, Any] | None],
        *,
        expected_revision: int | None = None,
        save: bool = False,
        verify: Callable[[Any, Mapping[str, Any] | None], bool] | None = None,
        backend: Backend = "live_ipc",
    ) -> dict[str, Any]:
        before = deepcopy(self.document)
        before_state = self._state
        try:
            # Check inside the envelope-producing boundary so stale writes are
            # a structured domain failure and the callback is never invoked.
            self.check_revision(expected_revision)
            effects = callback(self.document)
            if verify is not None and not verify(self.document, effects):
                raise OperationFailure("mutation postcondition verification failed")
            new_revision = before_state.document_revision + 1
            self._state = DocumentState(True, False, new_revision)
            if save:
                self.save()
            return operation_result(
                operation,
                state=self._state,
                verified_effects=effects,
                backend=backend,
            )
        except Exception as exc:
            self.document = before
            self._state = before_state
            return operation_result(
                operation,
                state=self._state,
                status="failure",
                backend=backend,
                error=str(exc),
            )


def stable_uuid(kind: str, identity: str | Mapping[str, Any]) -> str:
    """Return a deterministic UUID for an inspected KiCad object."""
    if isinstance(identity, Mapping):
        identity = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"kicad-automation:{kind}:{identity}"))


def with_stable_uuid(kind: str, item: Mapping[str, Any], *, identity: str | None = None) -> dict[str, Any]:
    result = dict(item)
    if result.get("uuid"):
        result.setdefault("uuid_source", "native")
    elif result.get("id"):
        # Some KiCad inspection surfaces call the native identity ``id``.
        # Preserve it verbatim instead of hashing an array position or object
        # representation into a replacement UUID.
        result["uuid"] = str(result["id"])
        result["uuid_source"] = "native"
    else:
        identity = identity or str(
            result.get("id")
            or result.get("reference")
            or result.get("number")
            or json.dumps(result, sort_keys=True, separators=(",", ":"))
        )
        result["uuid"] = stable_uuid(kind, identity)
        result["uuid_source"] = "derived"
    return result


def decorate_inspection(kind: str, items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Attach stable UUIDs to shape/track/pad/violation inspection records."""
    return [with_stable_uuid(kind, item) for item in items]


def normalize_footprint_id(value: str) -> str:
    """Preserve a library-qualified KiCad footprint identifier."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("footprint identifier must be a non-empty string")
    value = value.strip()
    # KiCad library identifiers are ``Library:Footprint``.  Do not add a fake
    # library when the source genuinely has a legacy unqualified identifier.
    return value


def preserve_footprint_id(source: Mapping[str, Any], target: dict[str, Any]) -> str | None:
    value = source.get("footprint_id") or source.get("footprint") or source.get("lib_id")
    if value is None:
        return None
    qualified = normalize_footprint_id(str(value))
    target["footprint_id"] = qualified
    target["footprint"] = qualified
    return qualified


def preserve_footprint_ids(
    schematic_symbols: Iterable[Mapping[str, Any]],
    pcb_footprints: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Return qualified symbol/PCB footprint parity diagnostics without rewriting files."""
    symbols = {str(item.get("reference")): item for item in schematic_symbols}
    mismatches: list[dict[str, Any]] = []
    preserved: list[str] = []
    for footprint in pcb_footprints:
        reference = str(footprint.get("reference"))
        source = symbols.get(reference)
        if source is None:
            continue
        expected = source.get("footprint_id") or source.get("footprint") or source.get("lib_id")
        actual = footprint.get("footprint_id") or footprint.get("footprint")
        if expected and actual == expected:
            preserved.append(reference)
        elif expected:
            mismatches.append({"reference": reference, "expected": str(expected), "actual": actual,
                               "uuid": stable_uuid("footprint", reference)})
    return {"parity": not mismatches, "preserved": preserved, "mismatches": mismatches}


def resolve_pin(symbols: Iterable[Mapping[str, Any]], reference: str, pin: str) -> dict[str, Any]:
    """Resolve a canonical ``reference.pin`` terminal without coordinate math."""
    for symbol in symbols:
        if str(symbol.get("reference")) != str(reference):
            continue
        pins = symbol.get("pins", ())
        for item in pins:
            if isinstance(item, Mapping) and str(item.get("number")) == str(pin):
                return {"reference": str(reference), "pin": str(pin), **dict(item)}
            if isinstance(item, Mapping) and str(item.get("name")) == str(pin):
                return {"reference": str(reference), "pin": str(item.get("number", pin)), **dict(item)}
    raise ValueError(f"pin {reference}.{pin} was not found")


def canonical_pin_name(pin: Mapping[str, Any]) -> str:
    """Return the stable symbol-data name, including USB shield ``SH`` pins."""
    return str(pin.get("name") or pin.get("number") or "")


def erc_coordinate_mm(value: Any, *, unit: str = "mm") -> float:
    """Normalize a coordinate using an explicit unit, never an implicit 1/100 scale."""
    number = float(value)
    if unit.lower() in {"nm", "nanometre", "nanometer"}:
        return number / 1_000_000.0
    if unit.lower() in {"mil", "mils"}:
        return number * 0.0254
    if unit.lower() in {"centimil", "centimils"}:
        return number * 0.000254
    if unit.lower() != "mm":
        raise ValueError(f"unsupported coordinate unit: {unit}")
    return number


def ratsnest_fallback(
    unconnected: Iterable[Mapping[str, Any]] = (),
    drc: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build actionable unconnected endpoints when live ratsnest is unavailable."""
    endpoints: list[dict[str, Any]] = []
    for item in unconnected:
        endpoint = dict(item)
        endpoint.setdefault("uuid", stable_uuid("unconnected", endpoint))
        endpoints.append(endpoint)
    if drc:
        for item in drc.get("unconnected_items", ()) or ():
            endpoint = dict(item)
            endpoint.setdefault("uuid", stable_uuid("unconnected", endpoint))
            if endpoint not in endpoints:
                endpoints.append(endpoint)
    return {
        "source": "get_unconnected_nets+drc",
        "fallback": True,
        "available": bool(endpoints),
        "limitations": ["fallback reports unconnected endpoints, not live ratsnest geometry"],
        "endpoints": endpoints,
    }


@dataclass(frozen=True)
class DrcExclusionFilter:
    uuids: frozenset[str] = frozenset()
    rules: frozenset[str] = frozenset()
    types: frozenset[str] = frozenset()
    references: frozenset[str] = frozenset()

    def matches(self, violation: Mapping[str, Any]) -> bool:
        items = violation.get("items", ()) or ()
        ids = {str(violation.get("uuid", ""))} | {
            str(item.get("uuid", "")) for item in items if isinstance(item, Mapping)
        }
        refs = set(str(ref) for ref in violation.get("references", ()) or ())
        refs.update(
            str(item.get("reference"))
            for item in items
            if isinstance(item, Mapping) and item.get("reference")
        )
        rule = str(violation.get("rule", violation.get("rule_id", "")))
        typ = str(violation.get("type", ""))
        return bool(
            (self.uuids and ids & self.uuids)
            or (self.rules and rule in self.rules)
            or (self.types and typ in self.types)
            or (self.references and refs & self.references)
        )


def select_drc_violations(
    violations: Iterable[Mapping[str, Any]],
    selector: DrcExclusionFilter,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Preview/apply only explicitly selected exclusions.

    An empty selector is rejected, and bulk operations must opt into a dry-run
    preview before they can be applied.
    """
    if not any((selector.uuids, selector.rules, selector.types, selector.references)):
        raise ValueError("at least one selective DRC exclusion filter is required")
    matches = [dict(v) for v in violations if selector.matches(v)]
    if len(matches) > 1 and not dry_run:
        raise ValueError("bulk DRC exclusions require a dry-run preview")
    selected = [with_stable_uuid("violation", v) for v in matches]
    preview_payload = json.dumps([item["uuid"] for item in selected], separators=(",", ":"))
    return {
        "status": "preview" if dry_run else "applied",
        "preview_id": hashlib.sha256(preview_payload.encode()).hexdigest()[:16],
        "matched": selected,
        "excluded_uuids": [item["uuid"] for item in selected],
        "count": len(matches),
    }


def execute_drc_exclusions(
    violations: Iterable[Mapping[str, Any]],
    selector: DrcExclusionFilter,
    *,
    preview: Mapping[str, Any],
    add_exclusions: Callable[[list[str]], Mapping[str, Any] | None],
    save: Callable[[], bool] | None = None,
    reopen: Callable[[], Any] | None = None,
    list_exclusions: Callable[[], Iterable[str]] | None = None,
    snapshot: Callable[[], Any] | None = None,
    restore: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    """Execute exactly the UUIDs shown by a mandatory dry-run preview."""
    current = select_drc_violations(violations, selector, dry_run=True)
    if preview.get("status") != "preview" or preview.get("preview_id") != current["preview_id"]:
        raise ValueError("DRC exclusion preview is stale; generate a new preview")
    ids = list(current["excluded_uuids"])
    if not ids:
        raise ValueError("DRC exclusion selector matched zero violations")
    before = snapshot() if snapshot is not None else None
    rolled_back = False

    def rollback() -> None:
        nonlocal rolled_back
        if before is not None and restore is not None:
            restore(before)
            rolled_back = True

    try:
        effects = dict(add_exclusions(ids) or {})
    except Exception as exc:
        rollback()
        return operation_result("drc_add_exclusions", state=DocumentState(), status="failure",
                                verified_effects={"selected_uuids": ids, "rolled_back": rolled_back},
                                error=str(exc))
    saved = False
    if save is not None:
        saved = bool(save())
        if not saved:
            rollback()
            return operation_result("drc_add_exclusions", state=DocumentState(), status="failure",
                                    verified_effects={"selected_uuids": ids, "rolled_back": rolled_back},
                                    error="DRC exclusion save postcondition failed")
    reopened = False
    readback_ok = True
    if reopen is not None:
        try:
            reopen()
            reopened = True
            if list_exclusions is not None:
                readback_ok = set(ids).issubset({str(item) for item in list_exclusions()})
        except Exception as exc:
            rollback()
            return operation_result("drc_add_exclusions", state=DocumentState(), status="failure",
                                    verified_effects={"selected_uuids": ids, "reopened": reopened,
                                                      "rolled_back": rolled_back},
                                    error=str(exc))
    if not readback_ok:
        rollback()
        return operation_result("drc_add_exclusions", state=DocumentState(), status="failure",
                                verified_effects={"selected_uuids": ids, "reopened": reopened,
                                                  "readback_verified": False, "rolled_back": rolled_back},
                                error="selected DRC exclusions were not present after reopen")
    return operation_result(
        "drc_add_exclusions", state=DocumentState(not saved, saved),
        verified_effects={"selected_uuids": ids, "preview_id": current["preview_id"],
                          "reopened": reopened, "readback_verified": readback_ok, **effects},
    )


def resolve_project_paths(root: Path, requested: str) -> dict[str, str]:
    """Resolve a project destination without duplicating ``name/name``."""
    windows_style = bool(re.match(r"^[A-Za-z]:[\\/]", requested) or requested.startswith("\\\\"))
    if windows_style and os.name != "nt":
        # Keep Windows path semantics testable on the Linux CI image.  A real
        # Windows process uses pathlib's native implementation below.
        base = PureWindowsPath(requested)
    else:
        requested_path = Path(requested)
        base = (root / requested_path).resolve() if not requested_path.is_absolute() else requested_path.resolve()
    if base.suffix in {".kicad_pcb", ".kicad_sch", ".kicad_pro"}:
        stem = base.with_suffix("")
        directory = stem.parent
        name = stem.name
    else:
        directory = base
        name = base.name
        # A caller requesting ``.../name`` means that directory, not
        # ``.../name/name``.  Creation tools can still choose another explicit name.
        stem = directory / name
    return {
        "directory": str(directory),
        "name": name,
        "project": str(stem.with_suffix(".kicad_pro")),
        "schematic": str(stem.with_suffix(".kicad_sch")),
        "board": str(stem.with_suffix(".kicad_pcb")),
    }


def precise_schematic_schema() -> dict[str, Any]:
    """JSON schema matching ``kicad-mcp-pro`` 3.34.0 nested builder inputs.

    ``library`` + ``symbol_name`` is the canonical identifier.  The upstream
    tool has historically documented ``lib_id`` in examples, but accepting it
    silently makes a request fail later and can replace a schematic first.  We
    therefore expose one precise contract and reject the legacy spelling before
    any mutation.
    """
    pin = {"type": "string", "pattern": r"^[^./\s]+\.[^./\s]+$"}
    number = {"type": "number"}
    symbol = {
        "type": "object", "additionalProperties": False,
        "required": ["library", "symbol_name", "reference", "value"],
        "properties": {
            "library": {"type": "string", "minLength": 1, "maxLength": 120},
            "symbol_name": {"type": "string", "minLength": 1, "maxLength": 240},
            "reference": {"type": "string", "pattern": r"^[A-Za-z#]+[0-9]+$"},
            "value": {"type": "string", "minLength": 1, "maxLength": 240},
            "footprint": {"type": "string", "maxLength": 240},
            "x_mm": number, "y_mm": number,
            "rotation": {"type": "integer", "enum": [0, 90, 180, 270]},
            "unit": {"type": "integer", "minimum": 1, "maximum": 64},
            "snap_to_grid": {"type": "boolean"},
            "properties": {"type": "object", "additionalProperties": {"type": "string"}},
        },
    }
    wire = {
        "type": "object", "additionalProperties": False,
        "required": ["x1_mm", "y1_mm", "x2_mm", "y2_mm"],
        "properties": {"x1_mm": number, "y1_mm": number, "x2_mm": number, "y2_mm": number,
                       "snap_to_grid": {"type": "boolean"}},
    }
    label = {
        "type": "object", "additionalProperties": False,
        "required": ["name", "x_mm", "y_mm"],
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 240},
            "x_mm": number, "y_mm": number,
            "rotation": {"type": "integer", "enum": [0, 90, 180, 270]},
            "snap_to_grid": {"type": "boolean"}, "global_label": {"type": "boolean"},
            "kind": {"type": "string", "enum": ["label", "global_label", "hierarchical_label"]},
            "shape": {"type": "string", "enum": ["input", "output", "bidirectional", "tri_state", "passive"]},
            "justify": {"type": "string"},
        },
    }
    power = {
        "type": "object", "additionalProperties": False,
        "required": ["name", "x_mm", "y_mm"],
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 120},
                       "x_mm": number, "y_mm": number,
                       "rotation": {"type": "integer", "enum": [0, 90, 180, 270]},
                       "snap_to_grid": {"type": "boolean"}},
    }
    net = {
        "type": "object", "additionalProperties": False, "required": ["name", "pins"],
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 240},
                       "pins": {"type": "array", "minItems": 1, "items": pin},
                       "scope": {"type": "string", "enum": ["global", "local", "hierarchical"]},
                       "shape": {"type": "string", "enum": ["input", "output", "bidirectional", "passive"]}},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "symbols": {"type": ["array", "null"], "items": symbol},
            "wires": {"type": ["array", "null"], "items": wire},
            "labels": {"type": ["array", "null"], "items": label},
            "power_symbols": {"type": ["array", "null"], "items": power},
            "nets": {"type": ["array", "null"], "items": net},
            "snap_to_grid": {"type": "boolean"}, "auto_layout": {"type": "boolean"},
            "unsafe_routed_wires": {"type": "boolean"},
            "max_paper": {"type": "string", "enum": ["A4", "A3", "A2", "A1", "A0"]},
        },
    }


def validate_schematic_request(request: Mapping[str, Any]) -> None:
    """Validate the complete builder request before touching a document."""
    schema = precise_schematic_schema()
    if not isinstance(request, Mapping) or set(request) - set(schema["properties"]):
        raise ValueError("schematic request contains unknown properties")
    symbols = request.get("symbols")
    if symbols is None:
        symbols = []
    if not isinstance(symbols, list):
        raise ValueError("symbols must be an array or null")
    refs: set[str] = set()
    for symbol in symbols:
        if not isinstance(symbol, Mapping) or set(symbol) - set(schema["properties"]["symbols"]["items"]["properties"]):
            raise ValueError("each symbol must use the documented library/symbol_name fields")
        for key in ("library", "symbol_name", "reference", "value"):
            if not isinstance(symbol.get(key), str) or not symbol[key].strip():
                raise ValueError(f"symbol.{key} is required")
        if symbol.get("rotation", 0) not in (0, 90, 180, 270):
            raise ValueError("symbol.rotation must be one of 0, 90, 180, 270")
        if symbol["reference"] in refs:
            raise ValueError(f"duplicate symbol reference: {symbol['reference']}")
        refs.add(symbol["reference"])
    for key in ("wires", "labels", "power_symbols"):
        values = request.get(key)
        if values is None:
            continue
        if not isinstance(values, list):
            raise ValueError(f"{key} must be an array or null")
        item_schema = schema["properties"][key]["items"]
        for item in values:
            if not isinstance(item, Mapping) or set(item) - set(item_schema["properties"]):
                raise ValueError(f"{key} contains an object with unknown properties")
            for field in item_schema.get("required", ()):
                if field not in item:
                    raise ValueError(f"{key} items require {field}")
    for net in request.get("nets", []) or []:
        if not isinstance(net, Mapping) or set(net) - set(schema["properties"]["nets"]["items"]["properties"]):
            raise ValueError("nets must contain documented name/pins objects")
        if not isinstance(net.get("name"), str) or not net["name"].strip() or not isinstance(net.get("pins"), list):
            raise ValueError("nets must contain {name, pins} objects")
        for address in net["pins"]:
            if not isinstance(address, str) or address.count(".") != 1:
                raise ValueError(f"invalid pin address: {address}")


def validate_hole_constraints(
    footprints: Iterable[Mapping[str, Any]],
    *,
    min_through_hole: float = 0.2,
    min_npth: float = 0.2,
) -> dict[str, Any]:
    """Check board-level drill floors without treating library-internal holes as violations."""
    violations: list[dict[str, Any]] = []
    internal: list[dict[str, Any]] = []
    for footprint in footprints:
        reference = str(footprint.get("reference", ""))
        for pad in footprint.get("pads", ()) or ():
            if not isinstance(pad, Mapping):
                continue
            drill = pad.get("drill")
            if drill is None:
                continue
            if isinstance(drill, Mapping):
                drill = min(float(drill.get("x", drill.get("diameter", 0))),
                            float(drill.get("y", drill.get("diameter", 0))))
            drill = float(drill)
            kind = str(pad.get("type", "through_hole"))
            is_npth = kind.lower() in {"np_thru_hole", "npth", "np_through_hole"} or bool(pad.get("npth"))
            minimum = min_npth if is_npth else min_through_hole
            if drill >= minimum:
                continue
            entry = {
                "reference": reference,
                "pad": str(pad.get("number", "")),
                "drill_mm": drill,
                "minimum_mm": minimum,
                "type": "npth" if is_npth else "through_hole",
                "uuid": str(pad.get("uuid") or stable_uuid("pad", {"reference": reference, **pad})),
            }
            if pad.get("library_internal") or pad.get("footprint_internal"):
                entry["classification"] = "footprint_internal_library_exception"
                internal.append(entry)
            else:
                entry["classification"] = "board_rule_violation"
                violations.append(entry)
    return {
        "status": "pass" if not violations else "violations",
        "violations": violations,
        "library_exceptions": internal,
        "minimums": {"through_hole_mm": min_through_hole, "npth_mm": min_npth},
    }
