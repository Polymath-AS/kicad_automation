#!/usr/bin/env python3
"""Constraint-aware automatic placement for schematic-to-PCB synchronization."""

from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
from typing import Any, Iterable, Mapping
import math

try:
    from kicad_contracts import DocumentState, OperationResult
    from kicad_topology import Point, Rect, _point
    from kicad_promotion import PlacementPromotion
except ImportError:  # package import from repository root
    from scripts.kicad_contracts import DocumentState, OperationResult
    from scripts.kicad_topology import Point, Rect, _point
    from scripts.kicad_promotion import PlacementPromotion


def _rect_for_footprint(item: Mapping[str, Any], *, courtyard: bool = True) -> Rect:
    value = item.get("courtyard" if courtyard else "bounds") or item.get("bounds")
    if isinstance(value, Mapping):
        return Rect.from_value(value)
    position = _point(item.get("position", item))
    size = item.get("size", {"width": 1.0, "height": 1.0})
    width, height = float(size.get("width", 1.0)), float(size.get("height", 1.0))
    return Rect(position[0] - width / 2, position[1] - height / 2,
                position[0] + width / 2, position[1] + height / 2)


@dataclass(frozen=True)
class PlacementRequest:
    reference: str
    position: Point
    locked: bool = False
    connector_edge: str | None = None
    antenna_keepout: Rect | None = None
    max_edge_distance: float = 2.0
    search_radius: float = 12.0
    step: float = 1.0
    intent: Mapping[str, Any] | None = None
    rotation: float | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PlacementRequest":
        keepout = value.get("antenna_keepout")
        return cls(
            reference=str(value["reference"]), position=_point(value.get("position", value)),
            locked=bool(value.get("locked", False)), connector_edge=value.get("connector_edge"),
            antenna_keepout=Rect.from_value(keepout) if isinstance(keepout, Mapping) else None,
            max_edge_distance=float(value.get("max_edge_distance", 2.0)),
            search_radius=float(value.get("search_radius", 12.0)), step=float(value.get("step", 1.0)),
            intent=value.get("intent") if isinstance(value.get("intent"), Mapping) else None,
            rotation=float(value["rotation"]) if value.get("rotation") is not None else None,
        )


@dataclass
class PlacementPlan:
    success: bool
    positions: dict[str, Point]
    violations: list[dict[str, Any]]
    rotations: dict[str, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "positions": {ref: {"x_mm": p[0], "y_mm": p[1]} for ref, p in self.positions.items()},
            "violations": self.violations,
            "rotations": dict(self.rotations or {}),
        }


def board_edge_bounds(board: Mapping[str, Any]) -> Rect:
    """Derive placement bounds from Edge.Cuts, never from a schematic frame."""
    outline = board.get("edge_cuts") or board.get("Edge.Cuts") or board.get("outline") or board.get("bounds")
    if isinstance(outline, list) and outline:
        points = [_point(item) for item in outline if isinstance(item, Mapping)]
        if points:
            return Rect(min(x for x, _ in points), min(y for _, y in points),
                        max(x for x, _ in points), max(y for _, y in points))
    if not isinstance(outline, Mapping):
        raise ValueError("Edge.Cuts outline is required for constrained placement")
    if isinstance(outline.get("outer"), Mapping):
        outline = outline["outer"]
    if isinstance(outline.get("points"), list) and outline["points"]:
        points = [_point(item) for item in outline["points"] if isinstance(item, Mapping)]
        if points:
            return Rect(min(x for x, _ in points), min(y for _, y in points),
                        max(x for x, _ in points), max(y for _, y in points))
    return Rect.from_value(outline)


def _outline_points(board: Mapping[str, Any]) -> tuple[list[Point], list[list[Point]]]:
    outline = board.get("edge_cuts") or board.get("Edge.Cuts") or board.get("outline")
    if isinstance(outline, Mapping) and isinstance(outline.get("outer"), Mapping):
        outer = outline["outer"]
        cutouts = outline.get("cutouts", ())
    else:
        outer, cutouts = outline, ()
    def points(value: Any) -> list[Point]:
        if isinstance(value, Mapping) and isinstance(value.get("points"), list):
            return [_point(item) for item in value["points"] if isinstance(item, Mapping)]
        if isinstance(value, list):
            return [_point(item) for item in value if isinstance(item, Mapping)]
        return []
    return points(outer), [points(item) for item in cutouts if points(item)]


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    inside = False
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        if (current[1] > point[1]) != (previous[1] > point[1]):
            x = (previous[0] - current[0]) * (point[1] - current[1]) / ((previous[1] - current[1]) or 1e-12) + current[0]
            if point[0] < x:
                inside = not inside
    return inside


def _rect_corners(rect: Rect) -> tuple[Point, ...]:
    return ((rect.left, rect.bottom), (rect.left, rect.top),
            (rect.right, rect.bottom), (rect.right, rect.top))


def _translate(rect: Rect, origin: Point, position: Point) -> Rect:
    dx, dy = position[0] - origin[0], position[1] - origin[1]
    return Rect(rect.left + dx, rect.bottom + dy, rect.right + dx, rect.top + dy)


def _overlap(a: Rect, b: Rect) -> bool:
    return not (a.right <= b.left or b.right <= a.left or a.top <= b.bottom or b.top <= a.bottom)


def _rotate_rect(rect: Rect, origin: Point, degrees: float) -> Rect:
    radians = math.radians(degrees % 360)
    cos_value, sin_value = math.cos(radians), math.sin(radians)
    corners = []
    for point in _rect_corners(rect):
        dx, dy = point[0] - origin[0], point[1] - origin[1]
        corners.append((origin[0] + dx * cos_value - dy * sin_value,
                        origin[1] + dx * sin_value + dy * cos_value))
    return Rect(min(x for x, _ in corners), min(y for _, y in corners),
                max(x for x, _ in corners), max(y for _, y in corners))


class ConstraintPlacement:
    """Deterministic greedy placement with hard-failure/no-mutation semantics."""

    def __init__(self, board: Mapping[str, Any]):
        self.board = board
        self.bounds = board_edge_bounds(board)
        self.outline, self.cutouts = _outline_points(board)
        self.antenna_keepouts = [
            Rect.from_value(item)
            for item in (board.get("antenna_keepouts", ()) or ())
            if isinstance(item, Mapping)
        ]

    def _violations(self, item: Mapping[str, Any], position: Point, placed: Mapping[str, Rect], request: PlacementRequest) -> list[dict[str, Any]]:
        origin = _point(item.get("position", item))
        current_rotation = float(item.get("rotation", 0.0) or 0.0)
        target_rotation = current_rotation if request.rotation is None else request.rotation
        body = _rotate_rect(_translate(_rect_for_footprint(item, courtyard=False), origin, position),
                            position, target_rotation - current_rotation)
        courtyard = _rotate_rect(_translate(_rect_for_footprint(item), origin, position),
                                 position, target_rotation - current_rotation)
        violations: list[dict[str, Any]] = []
        if body.left < self.bounds.left or body.right > self.bounds.right or body.bottom < self.bounds.bottom or body.top > self.bounds.top:
            violations.append({"constraint": "inside_board", "reference": request.reference,
                               "coordinate": {"x_mm": position[0], "y_mm": position[1]},
                               "reason": "footprint extends outside Edge.Cuts"})
        if self.outline and any(not _point_in_polygon(corner, self.outline) for corner in _rect_corners(body)):
            violations.append({"constraint": "inside_board", "reference": request.reference,
                               "coordinate": {"x_mm": position[0], "y_mm": position[1]},
                               "reason": "footprint corner is outside the Edge.Cuts polygon"})
        if any(_point_in_polygon(corner, cutout) for cutout in self.cutouts for corner in _rect_corners(body)):
            violations.append({"constraint": "inside_board", "reference": request.reference,
                               "coordinate": {"x_mm": position[0], "y_mm": position[1]},
                               "reason": "footprint overlaps an Edge.Cuts cutout"})
        for reference, other in placed.items():
            if _overlap(courtyard, other):
                violations.append({"constraint": "courtyard_overlap", "reference": request.reference,
                                   "blocking_reference": reference,
                                   "coordinate": {"x_mm": position[0], "y_mm": position[1]}})
        keepouts = list(self.antenna_keepouts)
        if request.antenna_keepout is not None:
            keepouts.append(request.antenna_keepout)
        if any(_overlap(courtyard, keepout) for keepout in keepouts):
            violations.append({"constraint": "antenna_keepout", "reference": request.reference,
                               "coordinate": {"x_mm": position[0], "y_mm": position[1]}})
        if request.connector_edge:
            edge = request.connector_edge.lower()
            distance = {
                "left": abs(courtyard.left - self.bounds.left),
                "right": abs(self.bounds.right - courtyard.right),
                "top": abs(self.bounds.top - courtyard.top),
                "bottom": abs(courtyard.bottom - self.bounds.bottom),
            }.get(edge)
            if distance is None:
                violations.append({"constraint": "connector_edge", "reference": request.reference,
                                   "reason": f"unknown board edge: {request.connector_edge}"})
            elif distance > request.max_edge_distance:
                violations.append({"constraint": "connector_edge", "reference": request.reference,
                                   "edge": edge, "distance_mm": distance,
                                   "coordinate": {"x_mm": position[0], "y_mm": position[1]}})
        return violations

    def _candidates(self, requested: Point, request: PlacementRequest) -> Iterable[Point]:
        yield requested
        radius = request.step
        while radius <= request.search_radius + 1e-9:
            offsets = ((radius, 0), (-radius, 0), (0, radius), (0, -radius),
                       (radius, radius), (-radius, radius), (radius, -radius), (-radius, -radius))
            for dx, dy in offsets:
                yield requested[0] + dx, requested[1] + dy
            radius += request.step

    def plan(self, requests: Iterable[PlacementRequest]) -> PlacementPlan:
        requests = list(requests)
        requested_refs = {request.reference for request in requests}
        items = {str(item.get("reference")): item for item in self.board.get("footprints", ()) or () if isinstance(item, Mapping)}
        placed: dict[str, Rect] = {}
        positions: dict[str, Point] = {}
        rotations: dict[str, float] = {}
        violations: list[dict[str, Any]] = []
        # Existing locked footprints are hard obstacles.
        for reference, item in items.items():
            current = _point(item.get("position", item))
            if reference not in requested_refs or item.get("locked") or item.get("locked_position"):
                placed[reference] = _rect_for_footprint(item)
                positions[reference] = current
        for request in requests:
            item = items.get(request.reference)
            if item is None:
                violations.append({"constraint": "reference_exists", "reference": request.reference})
                continue
            intent = request.intent or item.get("intent") or {}
            connector_edge = request.connector_edge or item.get("connector_edge") or intent.get("connector_edge") or intent.get("edge")
            antenna = request.antenna_keepout
            if antenna is None:
                candidate_keepout = item.get("antenna_keepout") or item.get("antenna_region") or intent.get("antenna_keepout")
                if isinstance(candidate_keepout, Mapping):
                    antenna = Rect.from_value(candidate_keepout)
            if connector_edge != request.connector_edge or antenna != request.antenna_keepout:
                request = replace(request, connector_edge=str(connector_edge) if connector_edge else None,
                                  antenna_keepout=antenna)
            if item.get("locked") or request.locked:
                # A locked part may be accepted only at its current location.
                current = _point(item.get("position", item))
                if distance(current, request.position) > 1e-6:
                    violations.append({"constraint": "locked_part", "reference": request.reference,
                                       "coordinate": {"x_mm": request.position[0], "y_mm": request.position[1]},
                                       "reason": "locked footprint cannot move"})
                placed[request.reference] = _rect_for_footprint(item)
                positions[request.reference] = current
                if item.get("rotation") is not None:
                    rotations[request.reference] = float(item.get("rotation", 0.0))
                continue
            found = None
            last: list[dict[str, Any]] = []
            for candidate in self._candidates(request.position, request):
                last = self._violations(item, candidate, placed, request)
                if not last:
                    found = candidate
                    break
            if found is None:
                violations.extend(last or [{"constraint": "unsatisfiable", "reference": request.reference}])
                continue
            positions[request.reference] = found
            current_rotation = float(item.get("rotation", 0.0) or 0.0)
            target_rotation = current_rotation if request.rotation is None else request.rotation
            rotations[request.reference] = target_rotation
            placed[request.reference] = _rotate_rect(
                _translate(_rect_for_footprint(item), _point(item.get("position", item)), found),
                found, target_rotation - current_rotation,
            )
        # Include untouched unlocked items in overlap checks for subsequent
        # requests, without moving them.
        return PlacementPlan(not violations, positions, violations, rotations)


def apply_placement(
    board: dict[str, Any], requests: Iterable[PlacementRequest], *, state: DocumentState | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Plan and commit positions only after every hard constraint succeeds."""
    current_state = state or DocumentState()
    before = deepcopy(board)
    try:
        planner = ConstraintPlacement(board)
        plan = planner.plan(requests)
    except Exception as exc:
        return OperationResult("failure", "pcb_place_components", current_state, error=str(exc)).as_dict()
    if not plan.success:
        return OperationResult("failure", "pcb_place_components", current_state,
                               verified_effects={"rolled_back": True, "plan": plan.as_dict()},
                               blockers=plan.violations, error="placement constraints are unsatisfiable").as_dict()
    if dry_run:
        return OperationResult("success", "pcb_place_components", current_state,
                               verified_effects={"dry_run": True, "plan": plan.as_dict()}).as_dict()
    try:
        by_ref = {str(item.get("reference")): item for item in board.get("footprints", ()) or ()}
        for reference, position in plan.positions.items():
            if reference in by_ref:
                by_ref[reference]["position"] = {"x_mm": position[0], "y_mm": position[1]}
                if reference in (plan.rotations or {}):
                    by_ref[reference]["rotation"] = plan.rotations[reference]
        return OperationResult("success", "pcb_place_components",
                               DocumentState(True, False, current_state.document_revision + 1),
                               verified_effects={"plan": plan.as_dict()}).as_dict()
    except Exception as exc:
        board.clear()
        board.update(before)
        return OperationResult("failure", "pcb_place_components", current_state,
                               verified_effects={"rolled_back": True}, error=str(exc)).as_dict()


def placement_requests_from_candidate(
    source: Mapping[str, Any], candidate: Mapping[str, Any],
) -> list[PlacementRequest]:
    """Translate a reviewed candidate board into constraint-checked requests."""
    source_items = {str(item.get("uuid") or item.get("reference")): item
                    for item in source.get("footprints", ()) or () if isinstance(item, Mapping)}
    requests: list[PlacementRequest] = []
    for item in candidate.get("footprints", ()) or ():
        if not isinstance(item, Mapping):
            continue
        ident = str(item.get("uuid") or item.get("reference"))
        original = source_items.get(ident)
        if original is None:
            continue
        position = _point(item.get("position", item))
        if position is None:
            raise ValueError(f"candidate footprint {ident} has no position")
        intent = item.get("intent") if isinstance(item.get("intent"), Mapping) else original.get("intent")
        requests.append(PlacementRequest(
            reference=str(item.get("reference") or original.get("reference")), position=position,
            locked=bool(item.get("locked", original.get("locked", False))), intent=intent,
            rotation=float(item["rotation"]) if item.get("rotation") is not None else None,
        ))
    return requests


def promote_placement_candidate(
    source: Mapping[str, Any], candidate: Mapping[str, Any], *,
    read_board: Any, snapshot: Any, apply_delta: Any, restore: Any,
    save: Any, reopen: Any, validate: Any, state: DocumentState | None = None,
    expected_revision: int | None = None, expected_source_hash: str | None = None,
) -> dict[str, Any]:
    """Validate intent constraints, then promote with save/reopen/rollback checks."""
    requests = placement_requests_from_candidate(source, candidate)
    validation_board = deepcopy(source)
    planned = ConstraintPlacement(validation_board).plan(requests)
    if not planned.success:
        return OperationResult(
            "failure", "pcb_place_components", state or DocumentState(),
            verified_effects={"rolled_back": True, "plan": planned.as_dict()},
            blockers=planned.violations, error="placement candidate violates hard constraints",
        ).as_dict()
    promotion = PlacementPromotion(
        read_board=read_board, snapshot=snapshot, apply_delta=apply_delta,
        restore=restore, save=save, reopen=reopen, validate=validate, state=state,
    )
    return promotion.promote(candidate, expected_revision=expected_revision,
                             expected_source_hash=expected_source_hash,
                             candidate_validate=lambda _: True)


def distance(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
