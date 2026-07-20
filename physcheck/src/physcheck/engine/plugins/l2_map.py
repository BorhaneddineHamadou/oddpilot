"""L2 map cross-checks: scenario positions and motion against an OpenDRIVE map.

Design brief §4 L2: spawn poses on drivable lanes; referenced roads/lanes
exist; ego route topologically connected; no initial object interpenetration;
scenario speeds consistent with the road's speed limit. Interpretation
decisions D21-D24 in docs/decisions.md.
"""

from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING

from physcheck.ir.model import Entity, Position, Scenario
from physcheck.xodr.model import XodrMap

if TYPE_CHECKING:  # imported late at runtime to avoid a cycle with engine.py
    from physcheck.engine.engine import Finding

__all__ = ["PLUGIN_RULES", "map_findings"]

#: id -> (layer, severity, title, citation)
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    "MAP-000": (
        "L2",
        "warning",
        "OpenDRIVE map could not be fully parsed",
        "ASAM OpenDRIVE 1.6 specification (XML schema)",
    ),
    "MAP-001": (
        "L2",
        "error",
        "Referenced road does not exist in the map",
        "ASAM OpenSCENARIO 1.x Model Documentation, RoadPosition/LanePosition "
        "(roadId refers to a road in the OpenDRIVE road network)",
    ),
    "MAP-002": (
        "L2",
        "error",
        "Referenced lane does not exist on the road at the given s",
        "ASAM OpenSCENARIO 1.x Model Documentation, LanePosition (laneId refers "
        "to an OpenDRIVE lane id valid at coordinate s)",
    ),
    "MAP-003": (
        "L2",
        "error",
        "s-coordinate beyond the end of the road",
        "ASAM OpenDRIVE 1.6 specification §7 (road reference line, s in [0, length])",
    ),
    "MAP-004": (
        "L2",
        "error",
        "Vehicle spawned off any drivable lane",
        "ASAM OpenDRIVE 1.6 specification §9.5.3 (lane types: 'driving' and ramp/"
        "bus/parking types are vehicle-passable; 'sidewalk' etc. are not)",
    ),
    "MAP-005": (
        "L2",
        "error",
        "Initial bounding boxes interpenetrate",
        "Rigid bodies cannot overlap; ASAM OpenSCENARIO 1.x Model Documentation, "
        "class BoundingBox (spatial extent of an entity)",
    ),
    "MAP-006": (
        "L2",
        "error",
        "Route waypoints lie on roads with no connecting path",
        "ASAM OpenDRIVE 1.6 specification §8 & §10 (road links and junction "
        "connections define network reachability)",
    ),
    "MAP-007": (
        "L2",
        "warning",
        "Commanded speed exceeds the road speed limit",
        "ASAM OpenDRIVE 1.6 specification §7.3 (road type speed record: legal "
        "speed limit of the road segment)",
    ),
}

#: Lane types a motorised vehicle can plausibly occupy (OpenDRIVE 1.4-1.8
#: vocabularies merged; docs/decisions.md D23).
_VEHICLE_LANES = {
    "driving", "exit", "entry", "onRamp", "offRamp", "connectingRamp", "slipLane",
    "bus", "taxi", "HOV", "hov", "mwyEntry", "mwyExit", "parking", "stop",
}
#: Additional lane types allowed for bicycles (incl. sidewalk: cyclists
#: plausibly stage on sidewalks in crossing scenarios, D23).
_BICYCLE_EXTRA = {"biking", "shoulder", "border", "sidewalk", "walking"}

_S_TOL_M = 0.5
#: A world position is "off the map" when even the reference line is this far away.
_OFF_MAP_DIST_M = 30.0
#: Tolerated excess over the legal limit before MAP-007 fires (D24).
_SPEED_LIMIT_SLACK = 1.10


def map_findings(scenario: Scenario, xmap: XodrMap) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_map_parse_findings(scenario, xmap))
    findings.extend(_existence_findings(scenario, xmap))
    findings.extend(_spawn_findings(scenario, xmap))
    findings.extend(_interpenetration_findings(scenario, xmap))
    findings.extend(_route_findings(scenario, xmap))
    findings.extend(_speed_limit_findings(scenario, xmap))
    return findings


def _mk(rule_id: str, message: str, scenario: Scenario, context: str,
        values: dict[str, object]) -> Finding:
    from physcheck.engine.engine import Finding

    layer, severity, title, citation = PLUGIN_RULES[rule_id]
    return Finding(
        rule_id=rule_id, severity=severity, layer=layer, title=title,
        message=message, file=scenario.source_path, context=context,
        values=values, citation=citation,
    )


def _map_parse_findings(scenario: Scenario, xmap: XodrMap) -> list[Finding]:
    if not xmap.issues:
        return []
    summary = "; ".join(xmap.issues[:5])
    if len(xmap.issues) > 5:
        summary += f"; ... ({len(xmap.issues) - 5} more)"
    return [
        _mk(
            "MAP-000",
            f"Map '{xmap.source_path}' parsed with problems: {summary}. "
            "L2 checks run on the parseable part only.",
            scenario, "map", {"map.issues": len(xmap.issues)},
        )
    ]


# -- referenced roads / lanes / s ------------------------------------------


def _existence_findings(scenario: Scenario, xmap: XodrMap) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str | None, str | None, float | None]] = set()
    for use in scenario.position_uses:
        pos = use.position
        if pos.kind not in ("road", "lane") or pos.road_id is None:
            continue
        key = (pos.kind, pos.road_id, pos.lane_id, pos.s)
        if key in seen:
            continue
        seen.add(key)
        road = xmap.roads.get(pos.road_id)
        if road is None:
            findings.append(
                _mk(
                    "MAP-001",
                    f"Position references road '{pos.road_id}' which does not exist "
                    f"in map '{xmap.source_path}'.",
                    scenario, use.label, {"position.road_id": pos.road_id},
                )
            )
            continue
        if pos.s is not None and pos.s > road.length + _S_TOL_M:
            findings.append(
                _mk(
                    "MAP-003",
                    f"Position s={pos.s} m lies beyond the end of road "
                    f"'{pos.road_id}' (length {road.length} m).",
                    scenario, use.label,
                    {"position.s": pos.s, "road.length": road.length},
                )
            )
        if pos.kind == "lane" and pos.lane_id is not None:
            s = min(pos.s if pos.s is not None else 0.0, road.length)
            lane_ids: set[int] = set()
            section = road.section_at(s)
            if section is not None:
                lane_ids = {lid for lid in section.lanes if lid != 0}
            try:
                lane_num = int(pos.lane_id)
            except ValueError:
                lane_num = None
            if lane_num is None or lane_num not in lane_ids:
                findings.append(
                    _mk(
                        "MAP-002",
                        f"Position references lane '{pos.lane_id}' on road "
                        f"'{pos.road_id}' at s={s} m, but the lane section there "
                        f"only has lanes {sorted(lane_ids)}.",
                        scenario, use.label,
                        {"position.lane_id": pos.lane_id, "road.lanes": sorted(lane_ids)},
                    )
                )
    return findings


# -- initial poses ----------------------------------------------------------


def _init_pose(
    name: str,
    scenario: Scenario,
    xmap: XodrMap,
    cache: dict[str, tuple[float, float, float] | None],
    visiting: set[str],
) -> tuple[float, float, float] | None:
    """World (x, y, heading) of an entity's Init teleport, resolving Relative*
    positions through the referenced entity (cycle-safe)."""
    if name in cache:
        return cache[name]
    if name in visiting:
        return None
    visiting.add(name)
    pose = None
    entity = next((e for e in scenario.entities if e.name == name), None)
    pos = entity.initial_position if entity is not None else None
    if pos is not None:
        pose = _resolve_position(pos, scenario, xmap, cache, visiting)
    visiting.discard(name)
    cache[name] = pose
    return pose


def _resolve_position(
    pos: Position,
    scenario: Scenario,
    xmap: XodrMap,
    cache: dict[str, tuple[float, float, float] | None],
    visiting: set[str],
) -> tuple[float, float, float] | None:
    if pos.kind == "world":
        if pos.x is None or pos.y is None:
            return None
        return (pos.x, pos.y, pos.h if pos.h is not None else 0.0)
    if pos.kind == "lane" and pos.road_id is not None and pos.lane_id is not None:
        road = xmap.roads.get(pos.road_id)
        if road is None:
            return None
        try:
            lane_num = int(pos.lane_id)
        except ValueError:
            return None
        s = min(pos.s if pos.s is not None else 0.0, road.length)
        center = road.lane_center(s, lane_num)
        if center is None:
            return None
        x, y, heading = center
        offset = pos.t_or_offset or 0.0
        ref = road.ref_point(s)
        if offset and ref is not None:
            x += offset * -math.sin(ref[2])
            y += offset * math.cos(ref[2])
        return (x, y, heading)
    if pos.kind == "road" and pos.road_id is not None:
        road = xmap.roads.get(pos.road_id)
        if road is None:
            return None
        s = min(pos.s if pos.s is not None else 0.0, road.length)
        ref = road.ref_point(s)
        if ref is None:
            return None
        x, y, hdg = ref
        t = pos.t_or_offset or 0.0
        return (x + t * -math.sin(hdg), y + t * math.cos(hdg), hdg)
    if pos.kind in ("relative_world", "relative_object") and pos.entity_ref:
        base = _init_pose(pos.entity_ref, scenario, xmap, cache, visiting)
        if base is None:
            return None
        bx, by, bh = base
        dx, dy = pos.dx or 0.0, pos.dy or 0.0
        if pos.kind == "relative_world":
            return (bx + dx, by + dy, bh)
        return (
            bx + dx * math.cos(bh) - dy * math.sin(bh),
            by + dx * math.sin(bh) + dy * math.cos(bh),
            bh,
        )
    return None


def _init_poses(
    scenario: Scenario, xmap: XodrMap
) -> dict[str, tuple[float, float, float] | None]:
    cache: dict[str, tuple[float, float, float] | None] = {}
    for entity in scenario.entities:
        _init_pose(entity.name, scenario, xmap, cache, set())
    return cache


def _is_motor_vehicle(entity: Entity) -> bool:
    return entity.kind == "vehicle" and entity.category not in ("bicycle",)


def _spawn_findings(scenario: Scenario, xmap: XodrMap) -> list[Finding]:
    findings: list[Finding] = []
    poses = _init_poses(scenario, xmap)
    for entity in scenario.entities:
        if entity.kind != "vehicle" or entity.initial_position is None:
            continue
        allowed = _VEHICLE_LANES if _is_motor_vehicle(entity) else (
            _VEHICLE_LANES | _BICYCLE_EXTRA
        )
        pos = entity.initial_position
        context = f"entity '{entity.name}'"
        if pos.kind == "lane" and pos.road_id is not None and pos.lane_id is not None:
            road = xmap.roads.get(pos.road_id)
            if road is None:
                continue  # MAP-001 already covers this
            try:
                lane_num = int(pos.lane_id)
            except ValueError:
                continue  # MAP-002 already covers this
            s = min(pos.s if pos.s is not None else 0.0, road.length)
            section = road.section_at(s)
            if section is None or lane_num not in section.lanes:
                continue  # MAP-002 already covers this
            ltype = section.lanes[lane_num].ltype
            if ltype not in allowed:
                findings.append(
                    _mk(
                        "MAP-004",
                        f"Vehicle '{entity.name}' spawns on lane {lane_num} of road "
                        f"'{pos.road_id}', which has type '{ltype}' — not a lane a "
                        "vehicle can occupy.",
                        scenario, context,
                        {"lane.type": ltype, "position.road_id": pos.road_id},
                    )
                )
            continue
        pose = poses.get(entity.name)
        if pose is None or pos.kind not in ("world", "road", "relative_world",
                                            "relative_object"):
            continue
        candidates = xmap.candidate_lanes(pose[0], pose[1], max_ref_dist=_OFF_MAP_DIST_M)
        if not candidates:
            mirrored = xmap.candidate_lanes(pose[0], -pose[1], max_ref_dist=_OFF_MAP_DIST_M)
            hint = ""
            values: dict[str, object] = {"position.x": pose[0], "position.y": pose[1]}
            if any(ltype in allowed for _r, _s, _l, ltype in mirrored):
                hint = (
                    f" The y-mirrored point ({pose[0]:.1f}, {-pose[1]:.1f}) IS on a "
                    "drivable lane: the scenario's coordinates appear to be in "
                    "CARLA's left-handed frame instead of the OpenDRIVE inertial "
                    "frame ASAM OpenSCENARIO mandates — non-portable across engines."
                )
                values["position.mirrored_on_lane"] = True
            findings.append(
                _mk(
                    "MAP-004",
                    f"Vehicle '{entity.name}' spawns at ({pose[0]:.1f}, {pose[1]:.1f}), "
                    f"which lies outside every lane of the map.{hint}",
                    scenario, context, values,
                )
            )
        elif not any(ltype in allowed for _r, _s, _l, ltype in candidates):
            types = sorted({ltype for _r, _s, _l, ltype in candidates})
            findings.append(
                _mk(
                    "MAP-004",
                    f"Vehicle '{entity.name}' spawns at ({pose[0]:.1f}, {pose[1]:.1f}) "
                    f"on lane type(s) {types} — not a lane a vehicle can occupy.",
                    scenario, context, {"lane.types": types},
                )
            )
    return findings


def _attached_pairs(scenario: Scenario) -> set[frozenset[str]]:
    """Entity pairs linked by a Relative* init position: overlap is the
    attachment idiom (mounted loads, trailer hitches), not an accident (D27)."""
    pairs: set[frozenset[str]] = set()
    for entity in scenario.entities:
        pos = entity.initial_position
        if pos is not None and pos.kind.startswith("relative") and pos.entity_ref:
            pairs.add(frozenset((entity.name, pos.entity_ref)))
    return pairs


def _interpenetration_findings(scenario: Scenario, xmap: XodrMap) -> list[Finding]:
    findings: list[Finding] = []
    poses = _init_poses(scenario, xmap)
    attached = _attached_pairs(scenario)
    boxed: list[tuple[str, float, float, float, float, float]] = []
    for entity in scenario.entities:
        pose = poses.get(entity.name)
        box = entity.bounding_box
        if pose is None or box is None or not box.length_m or not box.width_m:
            continue
        boxed.append((entity.name, pose[0], pose[1], pose[2], box.length_m, box.width_m))
    for i, (name_a, xa, ya, ha, la, wa) in enumerate(boxed):
        for name_b, xb, yb, hb, lb, wb in boxed[i + 1:]:
            if frozenset((name_a, name_b)) in attached:
                continue
            if _rects_overlap((xa, ya, ha, la, wa), (xb, yb, hb, lb, wb)):
                findings.append(
                    _mk(
                        "MAP-005",
                        f"Entities '{name_a}' and '{name_b}' interpenetrate at their "
                        f"initial positions (({xa:.1f}, {ya:.1f}) vs ({xb:.1f}, "
                        f"{yb:.1f})): rigid bodies cannot overlap at t=0.",
                        scenario, f"'{name_a}' vs '{name_b}'",
                        {"a.x": xa, "a.y": ya, "b.x": xb, "b.y": yb},
                    )
                )
    return findings


def _rects_overlap(
    a: tuple[float, float, float, float, float],
    b: tuple[float, float, float, float, float],
) -> bool:
    """Separating-axis test for two oriented rectangles (x, y, heading, length, width)."""

    def corners(r: tuple[float, float, float, float, float]) -> list[tuple[float, float]]:
        x, y, h, length, width = r
        cos_h, sin_h = math.cos(h), math.sin(h)
        out = []
        for su, sv in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
            u, v = su * length / 2, sv * width / 2
            out.append((x + u * cos_h - v * sin_h, y + u * sin_h + v * cos_h))
        return out

    ca, cb = corners(a), corners(b)
    for rect in (ca, cb):
        for i in range(4):
            edge_x = rect[(i + 1) % 4][0] - rect[i][0]
            edge_y = rect[(i + 1) % 4][1] - rect[i][1]
            axis = (-edge_y, edge_x)
            proj_a = [px * axis[0] + py * axis[1] for px, py in ca]
            proj_b = [px * axis[0] + py * axis[1] for px, py in cb]
            if max(proj_a) <= min(proj_b) or max(proj_b) <= min(proj_a):
                return False
    return True


# -- routes -----------------------------------------------------------------


def _waypoint_road(pos: Position, scenario: Scenario, xmap: XodrMap) -> str | None:
    if pos.kind in ("road", "lane"):
        return pos.road_id if pos.road_id in xmap.roads else None
    if pos.kind == "world" and pos.x is not None and pos.y is not None:
        projected = xmap.project(pos.x, pos.y)
        if projected is not None and projected[3] <= _OFF_MAP_DIST_M:
            return projected[0]
    return None


def _route_findings(scenario: Scenario, xmap: XodrMap) -> list[Finding]:
    findings: list[Finding] = []
    for route in scenario.routes:
        road_ids = [_waypoint_road(p, scenario, xmap) for p in route.waypoints]
        placed = [(i, rid) for i, rid in enumerate(road_ids) if rid is not None]
        for (i, rid_a), (j, rid_b) in itertools.pairwise(placed):
            if not xmap.connected(rid_a, rid_b):
                entity = f" of '{route.entity}'" if route.entity else ""
                findings.append(
                    _mk(
                        "MAP-006",
                        f"Route{entity}: waypoint {i} (road '{rid_a}') and waypoint "
                        f"{j} (road '{rid_b}') lie on roads with no connecting path "
                        "in the map's link/junction graph.",
                        scenario, route.label,
                        {"waypoint.a.road": rid_a, "waypoint.b.road": rid_b},
                    )
                )
    return findings


# -- speed limits -----------------------------------------------------------


def _spawn_road_s(
    entity: Entity, scenario: Scenario, xmap: XodrMap
) -> tuple[str, float] | None:
    pos = entity.initial_position
    if pos is None:
        return None
    if pos.kind in ("road", "lane") and pos.road_id in xmap.roads:
        return (pos.road_id, pos.s if pos.s is not None else 0.0)
    if pos.kind == "world" and pos.x is not None and pos.y is not None:
        projected = xmap.project(pos.x, pos.y)
        if projected is not None and projected[3] <= _OFF_MAP_DIST_M:
            return (projected[0], projected[1])
    return None


def _speed_limit_findings(scenario: Scenario, xmap: XodrMap) -> list[Finding]:
    findings: list[Finding] = []
    for entity in scenario.entities:
        if not _is_motor_vehicle(entity):
            continue
        located = _spawn_road_s(entity, scenario, xmap)
        if located is None:
            continue
        road_id, s = located
        road = xmap.roads[road_id]
        limit: float | None = None
        for rec in road.speeds:
            if rec.s0 <= s + 1e-9:
                limit = rec.max_mps
        if limit is None:
            continue
        speeds = [
            cmd.target_speed_mps
            for cmd in scenario.speed_commands
            if cmd.entity == entity.name and cmd.target_speed_mps is not None
        ]
        if entity.initial_speed_mps is not None:
            speeds.append(entity.initial_speed_mps)
        if not speeds:
            continue
        top = max(speeds)
        if top > limit * _SPEED_LIMIT_SLACK:
            findings.append(
                _mk(
                    "MAP-007",
                    f"'{entity.name}' is commanded to {top:.1f} m/s but road "
                    f"'{road_id}' has a {limit:.1f} m/s speed limit "
                    f"({top / limit:.0%} of the limit). Deliberate speeding should "
                    "be an explicit scenario parameter, not an accident.",
                    scenario, f"entity '{entity.name}'",
                    {"entity.top_speed_mps": top, "road.speed_limit_mps": limit},
                )
            )
    return findings
