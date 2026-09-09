#!/usr/bin/env python3
"""Topology-aware, transactional PCB routing primitives.

The planner operates on the structured objects returned by MCP Pro.  It is
deliberately backend-neutral: a live adapter can provide snapshot/apply/restore
callbacks, while unit tests can use a plain dictionary board.  No KiCad file is
edited by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math
from typing import Any, Callable, Iterable, Mapping

try:
    from kicad_contracts import DocumentState, OperationResult, stable_uuid
except ImportError:  # package import from repository root
    from scripts.kicad_contracts import DocumentState, OperationResult, stable_uuid


Point = tuple[float, float]


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point(value: Any) -> Point:
    if isinstance(value, Mapping):
        return float(value.get("x", value.get("x_mm", 0))), float(value.get("y", value.get("y_mm", 0)))
    return float(value[0]), float(value[1])


@dataclass(frozen=True)
class Rect:
    left: float
    bottom: float
    right: float
    top: float

    @classmethod
    def from_value(cls, value: Mapping[str, Any]) -> "Rect":
        if "left" in value:
            return cls(float(value["left"]), float(value["bottom"]), float(value["right"]), float(value["top"]))
        origin = _point(value.get("origin", value))
        return cls(origin[0], origin[1], origin[0] + float(value["width"]), origin[1] + float(value["height"]))

    def inflate(self, amount: float) -> "Rect":
        return Rect(self.left - amount, self.bottom - amount, self.right + amount, self.top + amount)

    def contains(self, point: Point) -> bool:
        return self.left <= point[0] <= self.right and self.bottom <= point[1] <= self.top

    def segment_hits(self, a: Point, b: Point) -> bool:
        # Routing segments are axis-aligned (the grid planner only emits
        # doglegs); this test also covers a diagonal endpoint supplied by a
        # caller.
        if self.contains(a) or self.contains(b):
            return True
        if abs(a[0] - b[0]) < 1e-9:
            return self.left <= a[0] <= self.right and not (max(a[1], b[1]) < self.bottom or min(a[1], b[1]) > self.top)
        if abs(a[1] - b[1]) < 1e-9:
            return self.bottom <= a[1] <= self.top and not (max(a[0], b[0]) < self.left or min(a[0], b[0]) > self.right)
        # Conservative bounding-box intersection for unsupported diagonals.
        return not (max(a[0], b[0]) < self.left or min(a[0], b[0]) > self.right or
                    max(a[1], b[1]) < self.bottom or min(a[1], b[1]) > self.top)


@dataclass(frozen=True)
class Obstacle:
    object_type: str
    uuid: str
    bounds: Rect
    layer: str | None = None
    net: str | None = None
    description: str = ""

    def blocker(self, coordinate: Point, reason: str = "clearance") -> dict[str, Any]:
        return {
            "object_type": self.object_type,
            "uuid": self.uuid,
            "coordinate": {"x_mm": coordinate[0], "y_mm": coordinate[1]},
            "layer": self.layer,
            "net": self.net,
            "reason": reason,
            "description": self.description,
        }


@dataclass(frozen=True)
class RouteRequest:
    start: Point
    end: Point
    net: str
    layers: tuple[str, ...] = ("F.Cu",)
    clearance: float = 0.2
    grid_step: float = 0.5
    track_width: float = 0.25
    allow_vias: bool = False
    dry_run: bool = False
    max_nodes: int = 100_000

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RouteRequest":
        layers = value.get("layers", ("F.Cu",))
        if not isinstance(layers, (list, tuple)) or not layers:
            raise ValueError("route layers must be non-empty")
        return cls(
            start=_point(value["start"]), end=_point(value["end"]), net=str(value.get("net", "")),
            layers=tuple(str(layer) for layer in layers), clearance=float(value.get("clearance", 0.2)),
            grid_step=float(value.get("grid_step", 0.5)), track_width=float(value.get("track_width", 0.25)),
            allow_vias=bool(value.get("allow_vias", False)), dry_run=bool(value.get("dry_run", False)),
            max_nodes=int(value.get("max_nodes", 100_000)),
        )


@dataclass
class RoutePlan:
    success: bool
    segments: list[dict[str, Any]] = field(default_factory=list)
    vias: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    explored_nodes: int = 0
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "segments": self.segments,
            "vias": self.vias,
            "blockers": self.blockers,
            "explored_nodes": self.explored_nodes,
            **({"reason": self.reason} if self.reason else {}),
        }


def obstacles_from_board(board: Mapping[str, Any], *, clearance: float, net: str) -> list[Obstacle]:
    result: list[Obstacle] = []
    for collection, object_type in (("footprints", "footprint"), ("keepouts", "keepout"), ("shapes", "shape")):
        for index, item in enumerate(board.get(collection, ()) or ()):
            if not isinstance(item, Mapping):
                continue
            try:
                bounds = Rect.from_value(item.get("bounds", item))
            except (KeyError, TypeError, ValueError):
                continue
            ident = str(item.get("uuid") or stable_uuid(object_type, item.get("reference", index)))
            item_net = item.get("net")
            # A footprint is still an obstacle when it owns the target pad; a
            # caller should provide endpoint-only footprints or their pads as
            # explicit exceptions.  Existing same-net tracks are allowed.
            result.append(Obstacle(object_type, ident, bounds.inflate(clearance), item.get("layer"),
                                   str(item_net) if item_net else None, str(item.get("reference", ""))))
    for index, item in enumerate(board.get("tracks", ()) or ()):
        if not isinstance(item, Mapping):
            continue
        if item.get("net") and str(item.get("net")) == net:
            continue
        a = _point(item.get("start", item.get("from")))
        b = _point(item.get("end", item.get("to")))
        width = float(item.get("width", 0.2)) / 2 + clearance
        result.append(Obstacle("track", str(item.get("uuid") or stable_uuid("track", index)),
                               Rect(min(a[0], b[0]) - width, min(a[1], b[1]) - width,
                                    max(a[0], b[0]) + width, max(a[1], b[1]) + width),
                               item.get("layer"), item.get("net"), "existing copper"))
    return result


class GridRouter:
    """A deterministic four-neighbour A* router with structured blockers."""

    def __init__(self, board: Mapping[str, Any]):
        self.board = board

    def plan(self, request: RouteRequest) -> RoutePlan:
        if request.grid_step <= 0 or request.clearance < 0:
            return RoutePlan(False, reason="grid_step and clearance must be non-negative")
        bounds_value = self.board.get("bounds") or self.board.get("outline")
        if not isinstance(bounds_value, Mapping):
            return RoutePlan(False, reason="board Edge.Cuts bounds are unavailable")
        bounds = Rect.from_value(bounds_value)
        start, end = request.start, request.end
        if not bounds.contains(start) or not bounds.contains(end):
            return RoutePlan(False, blockers=[{
                "object_type": "Edge.Cuts", "uuid": stable_uuid("edge", bounds_value),
                "coordinate": {"x_mm": end[0], "y_mm": end[1]}, "reason": "endpoint outside board outline",
            }], reason="route endpoint is outside Edge.Cuts")
        obstacles = obstacles_from_board(self.board, clearance=request.clearance + request.track_width / 2,
                                          net=request.net)
        # Do not reject the endpoint's own pad/footprint.  All other points in
        # the footprint remain blocked by the surrounding bounds.
        filtered: list[Obstacle] = []
        for obstacle in obstacles:
            if obstacle.object_type in {"footprint", "pad"} and (obstacle.bounds.contains(start) or obstacle.bounds.contains(end)):
                continue
            filtered.append(obstacle)
        obstacles = filtered
        step = request.grid_step
        def snap(p: Point) -> tuple[int, int]:
            return round((p[0] - bounds.left) / step), round((p[1] - bounds.bottom) / step)
        def unsnap(node: tuple[int, int]) -> Point:
            return bounds.left + node[0] * step, bounds.bottom + node[1] * step
        start_node, end_node = snap(start), snap(end)
        max_x = max(0, round((bounds.right - bounds.left) / step))
        max_y = max(0, round((bounds.top - bounds.bottom) / step))
        def allowed(node: tuple[int, int]) -> bool:
            x, y = node
            if x < 0 or y < 0 or x > max_x or y > max_y:
                return False
            point = unsnap(node)
            return not any(obstacle.bounds.contains(point) for obstacle in obstacles)
        active_layer = request.layers[0]
        def edge_allowed(a: Point, b: Point) -> bool:
            return not any(
                (obstacle.layer is None or str(obstacle.layer) == active_layer)
                and obstacle.bounds.segment_hits(a, b)
                for obstacle in obstacles
            )
        if not allowed(start_node) or not allowed(end_node):
            return RoutePlan(False, blockers=[o.blocker(start if not allowed(start_node) else end) for o in obstacles
                                              if o.bounds.contains(start if not allowed(start_node) else end)],
                             reason="endpoint is blocked by an obstacle")
        queue: list[tuple[float, int, tuple[int, int]]] = []
        serial = 0
        heapq.heappush(queue, (0.0, serial, start_node))
        came: dict[tuple[int, int], tuple[int, int] | None] = {start_node: None}
        costs = {start_node: 0.0}
        explored = 0
        dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
        while queue and explored < request.max_nodes:
            _, _, node = heapq.heappop(queue)
            explored += 1
            if node == end_node:
                nodes: list[tuple[int, int]] = []
                current: tuple[int, int] | None = node
                while current is not None:
                    nodes.append(current)
                    current = came[current]
                nodes.reverse()
                points = [start] + [unsnap(n) for n in nodes[1:-1]] + [end]
                # Compress collinear steps into real copper segments.
                compressed: list[Point] = [points[0]]
                for point in points[1:-1]:
                    if len(compressed) >= 2:
                        a, b = compressed[-2], compressed[-1]
                        if (abs(a[0] - b[0]) < 1e-9 and abs(b[0] - point[0]) < 1e-9) or (
                            abs(a[1] - b[1]) < 1e-9 and abs(b[1] - point[1]) < 1e-9):
                            compressed[-1] = point
                            continue
                    compressed.append(point)
                compressed.append(points[-1])
                segments = [{"start": {"x_mm": a[0], "y_mm": a[1]}, "end": {"x_mm": b[0], "y_mm": b[1]},
                             "layer": active_layer, "net": request.net,
                             "width_mm": request.track_width,
                             "uuid": stable_uuid("route-segment", {"a": a, "b": b, "net": request.net})}
                            for a, b in zip(compressed, compressed[1:])]
                vias: list[dict[str, Any]] = []
                if request.allow_vias and len(request.layers) > 1 and len(segments) > 1:
                    split = max(1, len(segments) // 2)
                    for index, segment in enumerate(segments):
                        segment["layer"] = request.layers[0] if index < split else request.layers[1]
                    point = segments[split - 1]["end"]
                    vias.append({"position": point, "layers": [request.layers[0], request.layers[1]],
                                 "net": request.net,
                                 "uuid": stable_uuid("route-via", point)})
                return RoutePlan(True, segments=segments, vias=vias, explored_nodes=explored)
            for dx, dy in dirs:
                neighbour = node[0] + dx, node[1] + dy
                if neighbour in came or not allowed(neighbour):
                    continue
                a, b = unsnap(node), unsnap(neighbour)
                if not edge_allowed(a, b):
                    continue
                new_cost = costs[node] + 1
                if new_cost < costs.get(neighbour, float("inf")):
                    costs[neighbour] = new_cost
                    came[neighbour] = node
                    serial += 1
                    priority = new_cost + abs(neighbour[0] - end_node[0]) + abs(neighbour[1] - end_node[1])
                    heapq.heappush(queue, (priority, serial, neighbour))
        # Report the nearest blocking objects, not merely an opaque no-path
        # message.  This is actionable in an MCP response and deterministic.
        probe = end
        nearest = sorted(obstacles, key=lambda o: distance(probe, ((o.bounds.left + o.bounds.right) / 2,
                                                                      (o.bounds.bottom + o.bounds.top) / 2)))[:8]
        return RoutePlan(False, blockers=[o.blocker(probe, "no clearance path") for o in nearest],
                         explored_nodes=explored, reason="no DRC-safe path found")


class TransactionalRouter:
    """Plan, optionally preview, and atomically apply a routed path."""

    def __init__(self, *, snapshot: Callable[[], Any], apply: Callable[[RoutePlan], Mapping[str, Any] | None],
                 restore: Callable[[Any], None], validate: Callable[[], bool], state: DocumentState | None = None):
        self.snapshot = snapshot
        self.apply = apply
        self.restore = restore
        self.validate = validate
        self.state = state or DocumentState()

    def route(self, request: RouteRequest, board: Mapping[str, Any]) -> dict[str, Any]:
        planned = GridRouter(board).plan(request)
        if not planned.success:
            return OperationResult("failure", "pcb_route_trace", self.state,
                                   blockers=planned.blockers, error=planned.reason).as_dict()
        if request.dry_run:
            return OperationResult("success", "pcb_route_trace", self.state,
                                   verified_effects={"dry_run": True, "plan": planned.as_dict()}).as_dict()
        before = self.snapshot()
        try:
            effects = self.apply(planned) or {}
            if not self.validate():
                raise RuntimeError("post-route DRC validation failed")
            self.state = DocumentState(True, False, self.state.document_revision + 1)
            return OperationResult("success", "pcb_route_trace", self.state,
                                   verified_effects={"plan": planned.as_dict(), **dict(effects)}).as_dict()
        except Exception as exc:
            self.restore(before)
            return OperationResult("failure", "pcb_route_trace", self.state,
                                   verified_effects={"rolled_back": True, "plan": planned.as_dict()},
                                   error=str(exc)).as_dict()
