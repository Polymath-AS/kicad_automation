#!/usr/bin/env python3
"""Transactional promotion helpers for reviewed KiCad document candidates.

The routing service deliberately works on isolated files.  This module is the
small, backend-neutral boundary used when a caller has a supported live IPC
adapter.  It never treats ``apply`` or ``save`` alone as success: the saved
document is reopened, read back, compared with the reviewed candidate, and
validated.  Any failure after mutation runs the same save/reopen/readback
sequence against the original snapshot before returning failure.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Mapping

try:
    from kicad_contracts import DocumentState, OperationResult, stable_uuid
except ImportError:  # package import from repository root
    from scripts.kicad_contracts import DocumentState, OperationResult, stable_uuid


def _jsonable(value: Any) -> Any:
    """Canonicalise adapter data without relying on mapping insertion order."""
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def board_digest(board: Mapping[str, Any]) -> str:
    """Return a deterministic digest suitable for stale-source protection."""
    encoded = json.dumps(_jsonable(board), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, Mapping):
        return None
    x = value.get("x_mm", value.get("x"))
    y = value.get("y_mm", value.get("y"))
    if x is None or y is None:
        return None
    return (round(float(x), 6), round(float(y), 6))


def _track_signature(item: Mapping[str, Any]) -> tuple[Any, ...]:
    start = _point(item.get("start", item.get("from")))
    end = _point(item.get("end", item.get("to")))
    return (
        str(item.get("uuid", "")),
        start,
        end,
        str(item.get("layer", "")),
        str(item.get("net", item.get("net_name", ""))),
        round(float(item.get("width", item.get("width_mm", 0.0)) or 0.0), 6),
    )


def _via_signature(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(item.get("uuid", "")),
        _point(item.get("position", item)),
        str(item.get("net", item.get("net_name", ""))),
        tuple(str(layer) for layer in item.get("layers", ()) or ()),
    )


@dataclass(frozen=True)
class CopperDelta:
    """A narrow, geometry-aware delta extracted from a candidate board."""

    add_segments: tuple[Mapping[str, Any], ...] = ()
    add_vias: tuple[Mapping[str, Any], ...] = ()
    remove_uuids: tuple[str, ...] = ()
    changed_footprints: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "add_segments": [dict(item) for item in self.add_segments],
            "add_vias": [dict(item) for item in self.add_vias],
            "remove_uuids": list(self.remove_uuids),
            "changed_footprints": [dict(item) for item in self.changed_footprints],
        }


def _object_id(kind: str, item: Mapping[str, Any]) -> str:
    explicit = item.get("uuid") or item.get("id")
    if explicit:
        return str(explicit)
    if kind == "track":
        identity: Any = _track_signature(item)
    elif kind == "via":
        identity = _via_signature(item)
    else:
        identity = item.get("reference", item)
    return stable_uuid(kind, repr(identity))


def geometry_delta(source: Mapping[str, Any], candidate: Mapping[str, Any]) -> CopperDelta:
    """Compute copper additions/removals without treating metadata as geometry."""
    source_tracks = {
        _object_id("track", item): item
        for item in source.get("tracks", ()) or ()
        if isinstance(item, Mapping)
    }
    candidate_tracks = {
        _object_id("track", item): item
        for item in candidate.get("tracks", ()) or ()
        if isinstance(item, Mapping)
    }
    source_vias = {
        _object_id("via", item): item
        for item in source.get("vias", ()) or ()
        if isinstance(item, Mapping)
    }
    candidate_vias = {
        _object_id("via", item): item
        for item in candidate.get("vias", ()) or ()
        if isinstance(item, Mapping)
    }
    add = tuple(item for ident, item in candidate_tracks.items() if ident not in source_tracks)
    add_vias = tuple(item for ident, item in candidate_vias.items() if ident not in source_vias)
    removed = tuple(ident for ident in source_tracks if ident not in candidate_tracks)
    removed += tuple(ident for ident in source_vias if ident not in candidate_vias)

    source_fp = {
        str(item.get("uuid") or item.get("reference")): item
        for item in source.get("footprints", ()) or ()
        if isinstance(item, Mapping)
    }
    candidate_fp = {
        str(item.get("uuid") or item.get("reference")): item
        for item in candidate.get("footprints", ()) or ()
        if isinstance(item, Mapping)
    }
    changed = tuple(
        candidate_fp[ident]
        for ident in source_fp.keys() & candidate_fp.keys()
        if (
            _point(candidate_fp[ident].get("position", candidate_fp[ident]))
            != _point(source_fp[ident].get("position", source_fp[ident]))
            or candidate_fp[ident].get("rotation") != source_fp[ident].get("rotation")
        )
    )
    return CopperDelta(add, add_vias, removed, changed)


def _verify_copper_readback(
    candidate: Mapping[str, Any],
    readback: Mapping[str, Any],
    delta: CopperDelta,
) -> tuple[bool, str | None]:
    """Verify candidate copper exists in the reopened live document."""
    actual_tracks = {
        _object_id("track", item): item
        for item in readback.get("tracks", ()) or ()
        if isinstance(item, Mapping)
    }
    actual_vias = {
        _object_id("via", item): item
        for item in readback.get("vias", ()) or ()
        if isinstance(item, Mapping)
    }
    for item in delta.add_segments:
        ident = _object_id("track", item)
        if ident not in actual_tracks:
            return False, f"promoted track {ident} was not present after reopen"
        expected_net = item.get("net", item.get("net_name"))
        actual_net = actual_tracks[ident].get("net", actual_tracks[ident].get("net_name"))
        if expected_net is not None and str(expected_net) != str(actual_net):
            return False, f"promoted track {ident} changed net identity"
    for item in delta.add_vias:
        ident = _object_id("via", item)
        if ident not in actual_vias:
            return False, f"promoted via {ident} was not present after reopen"
    return True, None


class TransactionalPromotion:
    """Generic candidate -> live-document promotion with verified rollback."""

    def __init__(
        self,
        *,
        read_document: Callable[[], Mapping[str, Any]],
        snapshot: Callable[[], Any],
        apply: Callable[[Any], Mapping[str, Any] | None],
        restore: Callable[[Any], None],
        save: Callable[[], bool],
        reopen: Callable[[], Any],
        validate: Callable[[], bool],
        verify_readback: Callable[[Mapping[str, Any], Mapping[str, Any], Any], tuple[bool, str | None]],
        operation: str,
        state: DocumentState | None = None,
    ) -> None:
        self.read_document = read_document
        self.snapshot = snapshot
        self.apply = apply
        self.restore = restore
        self.save = save
        self.reopen = reopen
        self.validate = validate
        self.verify_readback = verify_readback
        self.operation = operation
        self.state = state or DocumentState()

    def _failure(
        self,
        error: str,
        *,
        delta: Any = None,
        effects: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(effects or {})
        if delta is not None:
            payload.setdefault("delta", delta.as_dict() if hasattr(delta, "as_dict") else deepcopy(delta))
        return OperationResult("failure", self.operation, self.state,
                               verified_effects=payload, error=error).as_dict()

    def promote(
        self,
        candidate: Mapping[str, Any],
        delta: Any,
        *,
        expected_revision: int | None = None,
        expected_source_hash: str | None = None,
        candidate_validate: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        if expected_revision is not None and expected_revision != self.state.document_revision:
            return self._failure(
                f"stale document revision: expected {expected_revision}, current {self.state.document_revision}"
            )
        if candidate_validate is not None:
            try:
                if not candidate_validate(candidate):
                    return self._failure("candidate validation failed before live promotion")
            except Exception as exc:
                return self._failure(f"candidate validation failed: {exc}")

        try:
            source = deepcopy(self.read_document())
        except Exception as exc:
            return self._failure(f"could not inspect live source document: {exc}")
        source_hash = board_digest(source)
        if expected_source_hash is not None and expected_source_hash != source_hash:
            return self._failure("source document changed since candidate routing/placement")

        before = self.snapshot()
        mutated = False
        try:
            effects = self.apply(delta) or {}
            mutated = True
            if not self.save():
                raise RuntimeError("save postcondition failed")
            self.reopen()
            readback = deepcopy(self.read_document())
            matches, reason = self.verify_readback(candidate, readback, delta)
            if not matches:
                raise RuntimeError(reason or "reopened document does not match candidate")
            if not self.validate():
                raise RuntimeError("post-promotion validation failed")
            self.state = DocumentState(False, True, self.state.document_revision + 1)
            payload = {
                "delta": delta.as_dict() if hasattr(delta, "as_dict") else deepcopy(delta),
                "source_digest": source_hash,
                "candidate_digest": board_digest(candidate),
                "readback_verified": True,
                "reopened": True,
                "post_validation": True,
                **dict(effects),
            }
            return OperationResult("success", self.operation, self.state,
                                   verified_effects=payload).as_dict()
        except Exception as exc:
            rollback_verified = False
            rollback_error: str | None = None
            if mutated:
                try:
                    self.restore(before)
                    if not self.save():
                        raise RuntimeError("rollback save failed")
                    self.reopen()
                    restored = deepcopy(self.read_document())
                    rollback_verified = board_digest(restored) == source_hash and bool(self.validate())
                    if not rollback_verified:
                        raise RuntimeError("reopened rollback does not match the original source")
                except Exception as rollback_exc:
                    rollback_error = str(rollback_exc)
            payload: dict[str, Any] = {
                "delta": delta.as_dict() if hasattr(delta, "as_dict") else deepcopy(delta),
                "rolled_back": mutated,
                "rollback_verified": rollback_verified,
                "source_digest": source_hash,
            }
            if rollback_error:
                payload["rollback_error"] = rollback_error
            return self._failure(str(exc), effects=payload)


class LivePromotion:
    """Promote reviewed routing copper through a supported live adapter."""

    def __init__(
        self,
        *,
        read_board: Callable[[], Mapping[str, Any]],
        snapshot: Callable[[], Any],
        apply_delta: Callable[[CopperDelta], Mapping[str, Any] | None],
        restore: Callable[[Any], None],
        save: Callable[[], bool],
        validate: Callable[[], bool],
        reopen: Callable[[], Any] | None = None,
        state: DocumentState | None = None,
    ) -> None:
        if reopen is None:
            raise ValueError("live promotion requires an explicit reopen callback")
        self._transaction = TransactionalPromotion(
            read_document=read_board,
            snapshot=snapshot,
            apply=apply_delta,
            restore=restore,
            save=save,
            reopen=reopen,
            validate=validate,
            verify_readback=_verify_copper_readback,
            operation="routing_promote",
            state=state,
        )

    @property
    def state(self) -> DocumentState:
        return self._transaction.state

    def promote(
        self,
        candidate: Mapping[str, Any],
        *,
        expected_revision: int | None = None,
        expected_source_hash: str | None = None,
        candidate_validate: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        source = self._transaction.read_document()
        delta = geometry_delta(source, candidate)
        if delta.changed_footprints:
            return self._transaction._failure(
                "candidate changes footprint placement; promote placement through the placement adapter",
                delta=delta,
            )
        if delta.remove_uuids:
            return self._transaction._failure(
                "candidate removes existing copper; explicit reviewed removal is required",
                delta=delta,
            )
        return self._transaction.promote(
            candidate,
            delta,
            expected_revision=expected_revision,
            expected_source_hash=expected_source_hash,
            candidate_validate=candidate_validate,
        )


def placement_delta(source: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return a footprint-position delta; additions/deletions are refused."""
    source_items = {str(item.get("uuid") or item.get("reference")): item
                    for item in source.get("footprints", ()) or () if isinstance(item, Mapping)}
    candidate_items = {str(item.get("uuid") or item.get("reference")): item
                       for item in candidate.get("footprints", ()) or () if isinstance(item, Mapping)}
    if set(source_items) != set(candidate_items):
        raise ValueError("placement promotion cannot add or remove footprints")
    changed: list[dict[str, Any]] = []
    for ident, item in candidate_items.items():
        old = source_items[ident]
        old_pos = _point(old.get("position", old))
        new_pos = _point(item.get("position", item))
        if old_pos != new_pos or old.get("rotation") != item.get("rotation"):
            changed.append({"uuid": ident, "reference": item.get("reference"),
                            "position": item.get("position", item),
                            "rotation": item.get("rotation") or 0.0})
    return {"changed_footprints": changed}


def _verify_placement_readback(
    candidate: Mapping[str, Any],
    readback: Mapping[str, Any],
    delta: Mapping[str, Any],
) -> tuple[bool, str | None]:
    actual = {str(item.get("uuid") or item.get("reference")): item
              for item in readback.get("footprints", ()) or () if isinstance(item, Mapping)}
    for expected in delta.get("changed_footprints", ()):
        ident = str(expected.get("uuid") or expected.get("reference"))
        got = actual.get(ident)
        if got is None or _point(got.get("position", got)) != _point(expected.get("position", expected)):
            return False, f"footprint {ident} did not survive reopen at the promoted position"
    return True, None


class PlacementPromotion:
    """Constraint-checked footprint promotion sharing routing transaction semantics."""

    def __init__(self, **kwargs: Any) -> None:
        if kwargs.get("reopen") is None:
            raise ValueError("placement promotion requires an explicit reopen callback")
        self._transaction = TransactionalPromotion(
            read_document=kwargs["read_board"], snapshot=kwargs["snapshot"],
            apply=kwargs["apply_delta"], restore=kwargs["restore"], save=kwargs["save"],
            reopen=kwargs["reopen"], validate=kwargs["validate"],
            verify_readback=_verify_placement_readback, operation="pcb_place_components",
            state=kwargs.get("state"),
        )

    @property
    def state(self) -> DocumentState:
        return self._transaction.state

    def promote(self, candidate: Mapping[str, Any], *, expected_revision: int | None = None,
                expected_source_hash: str | None = None,
                candidate_validate: Callable[[Mapping[str, Any]], bool] | None = None) -> dict[str, Any]:
        try:
            source = self._transaction.read_document()
            delta = placement_delta(source, candidate)
        except Exception as exc:
            return self._transaction._failure(str(exc))
        return self._transaction.promote(
            candidate, delta, expected_revision=expected_revision,
            expected_source_hash=expected_source_hash, candidate_validate=candidate_validate,
        )
