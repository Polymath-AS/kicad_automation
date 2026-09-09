#!/usr/bin/env python3
"""Reviewed live-IPC promotion with revision checks and rollback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

try:
    from kicad_contracts import DocumentState, OperationResult, stable_uuid
except ImportError:  # package import from repository root
    from scripts.kicad_contracts import DocumentState, OperationResult, stable_uuid


@dataclass(frozen=True)
class CopperDelta:
    """A narrow, geometry-aware delta extracted from a candidate board."""

    add_segments: tuple[Mapping[str, Any], ...] = ()
    remove_uuids: tuple[str, ...] = ()
    changed_footprints: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "add_segments": [dict(item) for item in self.add_segments],
            "remove_uuids": list(self.remove_uuids),
            "changed_footprints": [dict(item) for item in self.changed_footprints],
        }


def geometry_delta(source: Mapping[str, Any], candidate: Mapping[str, Any]) -> CopperDelta:
    """Compute additions/removals while rejecting unrelated footprint changes."""
    source_tracks = {str(item.get("uuid") or stable_uuid("track", item)): item
                     for item in source.get("tracks", ()) or () if isinstance(item, Mapping)}
    candidate_tracks = {str(item.get("uuid") or stable_uuid("track", item)): item
                        for item in candidate.get("tracks", ()) or () if isinstance(item, Mapping)}
    add = tuple(item for ident, item in candidate_tracks.items() if ident not in source_tracks)
    removed = tuple(ident for ident in source_tracks if ident not in candidate_tracks)
    source_fp = {str(item.get("uuid") or item.get("reference")): item
                 for item in source.get("footprints", ()) or () if isinstance(item, Mapping)}
    candidate_fp = {str(item.get("uuid") or item.get("reference")): item
                    for item in candidate.get("footprints", ()) or () if isinstance(item, Mapping)}
    changed = tuple(candidate_fp[ident] for ident in source_fp.keys() & candidate_fp.keys()
                    if candidate_fp[ident] != source_fp[ident])
    return CopperDelta(add, removed, changed)


class LivePromotion:
    """Promote a reviewed candidate through an adapter's IPC mutation boundary."""

    def __init__(self, *, read_board: Callable[[], Mapping[str, Any]], snapshot: Callable[[], Any],
                 apply_delta: Callable[[CopperDelta], Mapping[str, Any] | None], restore: Callable[[Any], None],
                 save: Callable[[], bool], validate: Callable[[], bool], state: DocumentState | None = None):
        self.read_board = read_board
        self.snapshot = snapshot
        self.apply_delta = apply_delta
        self.restore = restore
        self.save = save
        self.validate = validate
        self.state = state or DocumentState()

    def promote(self, candidate: Mapping[str, Any], *, expected_revision: int | None = None,
                expected_source_hash: str | None = None) -> dict[str, Any]:
        if expected_revision is not None and expected_revision != self.state.document_revision:
            return OperationResult("failure", "routing_promote", self.state,
                                   error=f"stale document revision: expected {expected_revision}, current {self.state.document_revision}").as_dict()
        source = self.read_board()
        if expected_source_hash is not None:
            import hashlib
            digest = hashlib.sha256(repr(sorted(source.items())).encode()).hexdigest()
            if digest != expected_source_hash:
                return OperationResult("failure", "routing_promote", self.state,
                                       error="source board changed since candidate routing").as_dict()
        delta = geometry_delta(source, candidate)
        if delta.changed_footprints:
            return OperationResult("failure", "routing_promote", self.state,
                                   verified_effects={"delta": delta.as_dict()},
                                   error="candidate changes footprint placement; promotion requires a placement review").as_dict()
        if delta.remove_uuids:
            return OperationResult("failure", "routing_promote", self.state,
                                   verified_effects={"delta": delta.as_dict()},
                                   error="candidate removes existing copper; explicit reviewed removal is required").as_dict()
        before = self.snapshot()
        try:
            effects = self.apply_delta(delta) or {}
            if not self.validate() or not self.save() or not self.validate():
                raise RuntimeError("promotion postcondition validation or save failed")
            self.state = DocumentState(False, True, self.state.document_revision + 1)
            return OperationResult("success", "routing_promote", self.state,
                                   verified_effects={"delta": delta.as_dict(), **dict(effects)}).as_dict()
        except Exception as exc:
            self.restore(before)
            restored = bool(self.validate())
            return OperationResult("failure", "routing_promote", self.state,
                                   verified_effects={"rolled_back": True, "restored_valid": restored,
                                                     "delta": delta.as_dict()}, error=str(exc)).as_dict()
