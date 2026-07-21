"""L3 kinematic & dynamic feasibility: motion against tyre physics and the map.

Design brief §4 L3: friction-circle bound v^2 <= mu*g*r against map curvature
(mu composed from the L1 environment state — layers compose), longitudinal
acceleration within traction envelopes, lane-change duration plausibility with
the actual lane width, trajectory continuity, VRU sustained speeds.
Interpretation decisions D28-D31 in docs/decisions.md.

The map is optional: rules that need one (DYN-001) are skipped without it;
lane-change and trajectory rules run map-free (width falls back to 3.5 m).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from physcheck.ir.model import Entity, Scenario, TrajectoryFollow, TrajVertex
from physcheck.xodr.model import XodrMap

if TYPE_CHECKING:  # imported late at runtime to avoid a cycle with engine.py
    from physcheck.engine.engine import Finding

__all__ = ["PLUGIN_RULES", "kinematic_findings"]

#: id -> (layer, severity, title, citation)
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    "DYN-001": (
        "L3",
        "error",
        "Commanded speed infeasible for the road curvature at the entity's location",
        "Gillespie, T.D., Fundamentals of Vehicle Dynamics, SAE R-114, Ch. 6 "
        "(cornering: lateral acceleration v^2/R is bounded by tire-road friction "
        "mu*g); AASHTO Green Book Ch. 3 (horizontal curve design speed)",
    ),
    "DYN-002": (
        "L3",
        "error",
        "Lane change requires lateral acceleration beyond the friction limit",
        "Toledo, T. & Zohar, D., Modeling Duration of Lane Changes, TRR 1999:71-78 "
        "(2007); Gillespie, Fundamentals of Vehicle Dynamics, SAE R-114 (lateral "
        "acceleration bounded by mu*g)",
    ),
    "DYN-003": (
        "L3",
        "error",
        "Commanded speed-change rate beyond the traction limit of the declared surface",
        "Gillespie, T.D., Fundamentals of Vehicle Dynamics, SAE R-114, Ch. 3 "
        "(a <= mu*g on level ground regardless of engine/brake power); Wallman & "
        "Åström, VTI Meddelande 911A (2001), wet/ice friction levels",
    ),
    "DYN-004": (
        "L3",
        "error",
        "Trajectory time stamps not strictly increasing",
        "ASAM OpenSCENARIO 1.x Model Documentation, class Polyline/Vertex (time "
        "defines the motion's time domain; causality requires monotonic time)",
    ),
    "DYN-005": (
        "L3",
        "error",
        "Trajectory segment implies a physically impossible speed",
        "Production car speed record ~136 m/s (Bugatti Chiron SS 300+, 2019); "
        "sprint peak ~12.3 m/s (Krzysztof & Mero, J. Human Kinetics 36, 2013); "
        "unpaced HPV record ~40 m/s (IHPVA/WHPSC, 2016)",
    ),
    "DYN-006": (
        "L3",
        "error",
        "Trajectory demands combined acceleration beyond the friction circle",
        "Gillespie, T.D., Fundamentals of Vehicle Dynamics, SAE R-114 (friction "
        "circle: sqrt(a_lat^2 + a_long^2) <= mu*g); Pacejka, Tire and Vehicle "
        "Dynamics, 3rd ed., Ch. 1",
    ),
    "DYN-007": (
        "L3",
        "warning",
        "VRU sustains a speed beyond human endurance capability",
        "World Athletics marathon world record 2:00:35 (Kiptum, Chicago 2023): "
        "5.83 m/s sustained; UCI hour record 56.792 km (Ganna, 2022): 15.8 m/s "
        "sustained",
    ),
}

_G = 9.81
#: Reference dry-asphalt peak mu (FRI-013 convention).
_MU_DRY_REF = 0.9
#: Generous upper bounds of peak tire-road mu per declared surface state (D29):
#: certainly-impossible checks use the top of each published range.
_MU_CEILING = {
    "dry": 1.2,
    "moist": 1.0,
    "wetWithPuddles": 0.9,
    "lowFlooded": 0.7,
    "highFlooded": 0.4,
    "snow": 0.5,
    "ice": 0.35,
}
#: Class-record speed ceilings for trajectory segments (KIN-001/006/011 values).
_SPEED_CEILING_MPS = {"pedestrian": 12.5, "bicycle": 39.0, "vehicle": 140.0}
#: Sustained-speed ceilings over a >=30 s window (D31).
_SUSTAINED_WINDOW_S = 30.0
_SUSTAINED_CEILING_MPS = {"pedestrian": 6.0, "bicycle": 16.0}
_DEFAULT_LANE_WIDTH_M = 3.5
#: Freezing threshold for the ice surface class (slightly below 0 C: brine).
_FREEZE_K = 271.5


def kinematic_findings(scenario: Scenario, xmap: XodrMap | None = None) -> list[Finding]:
    findings: list[Finding] = []
    mu = _mu_ceiling(scenario)
    if xmap is not None:
        findings.extend(_curve_speed_findings(scenario, xmap, mu))
    findings.extend(_lane_change_findings(scenario, xmap, mu))
    findings.extend(_speed_rate_findings(scenario, mu))
    findings.extend(_trajectory_findings(scenario, mu))
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


# -- effective friction ceiling from the L1 environment state ---------------


def _mu_ceiling(scenario: Scenario) -> float:
    """Upper bound of plausible peak tire-road friction given the declared
    environment(s). Generous by class (D29): a violation of mu_ceiling * g is
    certainly impossible on the declared surface. The MOST favourable declared
    state is used when several environments exist."""
    best: float | None = None
    for env in scenario.environments:
        road = env.road_condition
        weather = env.weather
        mu: float | None = None
        if road is not None and road.friction_scale_factor is not None:
            mu = max(road.friction_scale_factor, 0.05) * _MU_DRY_REF * 4 / 3
        else:
            wetness = road.wetness if road is not None else None
            freezing = (
                weather is not None
                and weather.temperature_k is not None
                and weather.temperature_k <= _FREEZE_K
            )
            snowing = (
                weather is not None
                and weather.precipitation is not None
                and weather.precipitation.ptype == "snow"
            )
            wet = wetness not in (None, "dry") or (
                weather is not None
                and weather.precipitation is not None
                and weather.precipitation.ptype == "rain"
            )
            if freezing and (wet or snowing):
                mu = _MU_CEILING["ice"]
            elif snowing:
                mu = _MU_CEILING["snow"]
            elif wetness is not None:
                mu = _MU_CEILING.get(wetness, _MU_CEILING["moist"])
            elif wet:
                mu = _MU_CEILING["moist"]
        if mu is not None:
            best = mu if best is None else max(best, mu)
    return best if best is not None else _MU_CEILING["dry"]


# -- shared entity helpers ---------------------------------------------------


def _entity_by_name(scenario: Scenario, name: str) -> Entity | None:
    for entity in scenario.entities:
        if entity.name == name:
            return entity
    return None


def _entity_class(entity: Entity | None) -> str:
    if entity is None:
        return "vehicle"
    if entity.kind == "pedestrian":
        return "pedestrian"
    if entity.kind == "vehicle" and entity.category == "bicycle":
        return "bicycle"
    return "vehicle"


def _commanded_speeds(scenario: Scenario, name: str) -> list[float]:
    speeds = [
        cmd.target_speed_mps
        for cmd in scenario.speed_commands
        if cmd.entity == name and cmd.target_speed_mps is not None
    ]
    entity = _entity_by_name(scenario, name)
    if entity is not None and entity.initial_speed_mps is not None:
        speeds.append(entity.initial_speed_mps)
    return speeds


def _spawn_road_s(entity: Entity, xmap: XodrMap) -> tuple[str, float] | None:
    """The road the entity DECLARES itself on. World positions are not
    projected: at junctions, tiny corner-arc roads overlap the through path,
    so nearest-reference-line projection routinely picks a curved road the
    vehicle never drives (verified on converted inD intersections, D32)."""
    pos = entity.initial_position
    if pos is None:
        return None
    if pos.kind in ("road", "lane") and pos.road_id in xmap.roads:
        return (pos.road_id, pos.s if pos.s is not None else 0.0)
    return None


# -- DYN-001: speed vs curvature --------------------------------------------


def _curve_speed_findings(
    scenario: Scenario, xmap: XodrMap, mu: float
) -> list[Finding]:
    findings: list[Finding] = []
    for entity in scenario.entities:
        if entity.kind != "vehicle":
            continue
        located = _spawn_road_s(entity, xmap)
        if located is None:
            continue
        road_id, s = located
        kappa = xmap.roads[road_id].curvature_at(s)
        if kappa is None or kappa < 1e-4:  # straighter than r = 10 km
            continue
        speeds = _commanded_speeds(scenario, entity.name)
        if not speeds:
            continue
        v = max(speeds)
        # 1.2: numeric sampling of kappa, superelevation, and path-radius vs
        # reference-line slack on top of the already-generous mu ceiling.
        if v * v * kappa > mu * _G * 1.2:
            radius = 1.0 / kappa
            v_max = math.sqrt(mu * _G * radius)
            findings.append(
                _mk(
                    "DYN-001",
                    f"'{entity.name}' is commanded to {v:.1f} m/s on road "
                    f"'{road_id}' whose curve radius at s={s:.0f} m is "
                    f"{radius:.0f} m: lateral acceleration would be "
                    f"{v * v * kappa:.1f} m/s^2, beyond the friction ceiling "
                    f"mu*g = {mu * _G:.1f} m/s^2 (mu <= {mu:.2f} on the declared "
                    f"surface). Max feasible speed there is ~{v_max:.0f} m/s.",
                    scenario, f"entity '{entity.name}'",
                    {"entity.speed_mps": v, "road.curve_radius_m": round(radius, 1),
                     "surface.mu_ceiling": mu},
                )
            )
    return findings


# -- DYN-002: lane-change lateral acceleration -------------------------------


def _lane_change_findings(
    scenario: Scenario, xmap: XodrMap | None, mu: float
) -> list[Finding]:
    findings: list[Finding] = []
    for lc in scenario.lane_changes:
        entity = _entity_by_name(scenario, lc.entity)
        duration = lc.duration_s
        if duration is None and lc.distance_m is not None and lc.distance_m > 0:
            speeds = [v for v in _commanded_speeds(scenario, lc.entity) if v > 0]
            if not speeds:
                continue
            # Minimum plausible speed -> longest duration: conservative.
            duration = lc.distance_m / min(speeds)
        if duration is None or duration <= 0:
            continue
        width = _DEFAULT_LANE_WIDTH_M
        if entity is not None and xmap is not None:
            located = _spawn_road_s(entity, xmap)
            if located is not None:
                road = xmap.roads[located[0]]
                section = road.section_at(located[1])
                if section is not None:
                    widths = [
                        lane.width_at(located[1] - section.s0)
                        for lid, lane in section.lanes.items()
                        if lid != 0 and lane.ltype == "driving"
                    ]
                    if widths and max(widths) > 0:
                        width = max(widths)
        # Peak lateral acceleration of the sinusoidal lateral profile
        # y(t) = w/2 * (1 - cos(pi t / T)) over the lane width (D30).
        a_peak = width * math.pi**2 / (2 * duration * duration)
        if a_peak > mu * _G * 1.2:
            findings.append(
                _mk(
                    "DYN-002",
                    f"'{lc.entity}' changes lane ({width:.1f} m lateral) in "
                    f"{duration:.2f} s: peak lateral acceleration "
                    f"{a_peak:.1f} m/s^2 exceeds the friction ceiling mu*g = "
                    f"{mu * _G:.1f} m/s^2 (mu <= {mu:.2f} on the declared "
                    "surface). No tire can hold this manoeuvre.",
                    scenario, f"entity '{lc.entity}'",
                    {"lane_change.duration_s": round(duration, 3),
                     "lane.width_m": round(width, 2),
                     "surface.mu_ceiling": mu},
                )
            )
    return findings


# -- DYN-003: commanded speed rate vs traction -------------------------------


def _speed_rate_findings(scenario: Scenario, mu: float) -> list[Finding]:
    findings: list[Finding] = []
    for cmd in scenario.speed_commands:
        if cmd.rate_mps2 is None:
            continue
        # 1.35: FRI-013's tolerance (tire-mu variability up to ~1.2 vs the 0.9
        # reference, plus grade) applied to the class ceiling.
        limit = mu * _G * 1.35
        if cmd.rate_mps2 > limit:
            findings.append(
                _mk(
                    "DYN-003",
                    f"'{cmd.entity}' commands a speed change at {cmd.rate_mps2:.1f} "
                    f"m/s^2, but the declared surface (mu <= {mu:.2f}) limits "
                    f"traction to ~{limit:.1f} m/s^2: force transfer through the "
                    "tires cannot exceed mu*g regardless of engine or brakes.",
                    scenario, cmd.label or f"entity '{cmd.entity}'",
                    {"speed.rate_mps2": cmd.rate_mps2, "surface.mu_ceiling": mu},
                )
            )
    return findings


# -- DYN-004/005/006/007: trajectory feasibility -----------------------------


def _trajectory_findings(scenario: Scenario, mu: float) -> list[Finding]:
    findings: list[Finding] = []
    for traj in scenario.trajectories:
        if traj.shape != "polyline" or len(traj.vertices) < 2:
            continue
        eclass = _entity_class(_entity_by_name(scenario, traj.entity))
        timed = [v for v in traj.vertices if v.time_s is not None]
        finding = _time_monotonic_finding(scenario, traj, timed)
        if finding is not None:
            findings.append(finding)
            continue  # speeds/accels are meaningless on a broken time axis
        if len(timed) < 2:
            continue
        findings.extend(_segment_speed_findings(scenario, traj, timed, eclass))
        # A teleport-grade segment is a data break, owned by DYN-005: windows
        # that straddle it would re-report the same defect as phantom
        # acceleration/sustained speed, so split and analyse each run (D33).
        for run in _split_at_teleports(timed, eclass):
            findings.extend(_friction_circle_findings(scenario, traj, run, mu, eclass))
            findings.extend(_sustained_speed_findings(scenario, traj, run, eclass))
    return findings


def _split_at_teleports(
    timed: list[TrajVertex], eclass: str
) -> list[list[TrajVertex]]:
    ceiling = _SPEED_CEILING_MPS[eclass]
    runs: list[list[TrajVertex]] = [[timed[0]]] if timed else []
    for i, v in enumerate(_segment_speeds(timed)):
        if v is not None and v > ceiling:
            runs.append([])
        runs[-1].append(timed[i + 1])
    return [run for run in runs if len(run) >= 2]


def _time_monotonic_finding(
    scenario: Scenario, traj: TrajectoryFollow, timed: list[TrajVertex]
) -> Finding | None:
    for i in range(1, len(timed)):
        t, prev_t = timed[i].time_s, timed[i - 1].time_s
        assert t is not None and prev_t is not None
        if t <= prev_t:
            return _mk(
                "DYN-004",
                f"Trajectory of '{traj.entity}': vertex {i} has time {t} s, not "
                f"after the previous vertex's {prev_t} s — the motion's time "
                "axis runs backwards (or stalls), which no body can perform.",
                scenario, traj.label or f"entity '{traj.entity}'",
                {"vertex.index": i, "vertex.time_s": t, "previous.time_s": prev_t},
            )
    return None


def _segment_speeds(timed: list[TrajVertex]) -> list[float | None]:
    """Speed of each segment (into vertex i+1); None when dt is too small to
    divide by meaningfully (duplicate/near-duplicate time stamps)."""
    speeds: list[float | None] = []
    for i in range(1, len(timed)):
        a, b = timed[i - 1], timed[i]
        assert a.time_s is not None and b.time_s is not None
        dt = b.time_s - a.time_s
        speeds.append(math.hypot(b.x - a.x, b.y - a.y) / dt if dt >= 1e-3 else None)
    return speeds


def _segment_speed_findings(
    scenario: Scenario, traj: TrajectoryFollow, timed: list[TrajVertex], eclass: str
) -> list[Finding]:
    ceiling = _SPEED_CEILING_MPS[eclass]
    worst_v = 0.0
    worst_i = -1
    for i, v in enumerate(_segment_speeds(timed)):
        if v is not None and v > worst_v:
            worst_v, worst_i = v, i + 1
    if worst_v <= ceiling:
        return []
    return [
        _mk(
            "DYN-005",
            f"Trajectory of '{traj.entity}' ({eclass}): segment into vertex "
            f"{worst_i} implies {worst_v:.1f} m/s, beyond the class record "
            f"ceiling of {ceiling:.1f} m/s — a position jump (teleport), not "
            "motion.",
            scenario, traj.label or f"entity '{traj.entity}'",
            {"segment.speed_mps": round(worst_v, 1), "class.ceiling_mps": ceiling,
             "vertex.index": worst_i},
        )
    ]


#: Minimum time base for speed/acceleration estimation over a trajectory.
#: Recorded corpora quantise positions (0.1 m grid at 25 Hz was observed):
#: adjacent-sample differencing turns that into tens of m/s^2 of phantom
#: acceleration, while a >=0.4 s window bounds the quantisation error to
#: ~1 m/s^2 (D31). Sparse keyframe trajectories (dt >= window) fall back to
#: their raw segments, which are already long enough.
_ACCEL_WINDOW_S = 0.4


def _window_index(times: list[float], i: int, direction: int) -> int | None:
    """Nearest index at least _ACCEL_WINDOW_S away from vertex i (backward
    when direction is -1, forward when +1), or None when the trajectory does
    not extend a full window on that side. Sparse keyframes (local step
    already >= window) resolve to the raw neighbour."""
    if direction < 0:
        target = times[i] - _ACCEL_WINDOW_S
        if times[0] > target:
            return None
        j = i - 1
        while times[j] > target:
            j -= 1
        return j
    target = times[i] + _ACCEL_WINDOW_S
    if times[-1] < target:
        return None
    k = i + 1
    while times[k] < target:
        k += 1
    return k


def _friction_circle_findings(
    scenario: Scenario, traj: TrajectoryFollow, timed: list[TrajVertex], mu: float,
    eclass: str,
) -> list[Finding]:
    if eclass != "vehicle":
        return []  # legs/pedals: tire traction physics does not apply
    limit = mu * _G * 1.35
    n = len(timed)
    if n < 3:
        return []
    times: list[float] = []
    dists: list[float] = [0.0]
    for i, vertex in enumerate(timed):
        assert vertex.time_s is not None
        times.append(vertex.time_s)
        if i:
            prev = timed[i - 1]
            dists.append(dists[-1] + math.hypot(vertex.x - prev.x, vertex.y - prev.y))
    violations: list[tuple[int, float]] = []
    for i in range(1, n - 1):
        j = _window_index(times, i, -1)
        k = _window_index(times, i, +1)
        if j is None or k is None:
            continue
        dt_in, dt_out = times[i] - times[j], times[k] - times[i]
        dt_mid = (times[k] - times[j]) / 2
        if dt_in <= 1e-9 or dt_out <= 1e-9 or not 0.02 <= dt_mid <= 10.0:
            continue
        v_in = (dists[i] - dists[j]) / dt_in
        v_out = (dists[k] - dists[i]) / dt_out
        a_long = (v_out - v_in) / dt_mid
        v_mid = (v_out + v_in) / 2
        kappa = _menger_curvature(
            (timed[j].x, timed[j].y), (timed[i].x, timed[i].y), (timed[k].x, timed[k].y)
        )
        a_lat = v_mid * v_mid * kappa
        a_tot = math.hypot(a_long, a_lat)
        if a_tot > limit:
            violations.append((i, a_tot))
    # Two consecutive violating vertices required: a single spike is
    # indistinguishable from tracking noise in recorded data (D31).
    sustained = [
        violations[j]
        for j in range(1, len(violations))
        if violations[j][0] == violations[j - 1][0] + 1
    ]
    if not sustained:
        return []
    worst_i, worst_a = max(sustained, key=lambda item: item[1])
    return [
        _mk(
            "DYN-006",
            f"Trajectory of '{traj.entity}' demands a combined (lateral + "
            f"longitudinal) acceleration of {worst_a:.1f} m/s^2 around vertex "
            f"{worst_i}, sustained over consecutive samples — beyond the "
            f"friction circle mu*g = {mu * _G:.1f} m/s^2 (mu <= {mu:.2f} on "
            "the declared surface, tolerance 1.35). Tires cannot transmit this.",
            scenario, traj.label or f"entity '{traj.entity}'",
            {"trajectory.accel_mps2": round(worst_a, 1),
             "surface.mu_ceiling": mu, "vertex.index": worst_i},
        )
    ]


def _sustained_speed_findings(
    scenario: Scenario, traj: TrajectoryFollow, timed: list[TrajVertex], eclass: str
) -> list[Finding]:
    ceiling = _SUSTAINED_CEILING_MPS.get(eclass)
    if ceiling is None:
        return []
    t0, t1 = timed[0].time_s, timed[-1].time_s
    assert t0 is not None and t1 is not None
    total = t1 - t0
    if total < 10.0:
        return []
    window = min(_SUSTAINED_WINDOW_S, total)
    # Prefix path length over the polyline, then max windowed average speed.
    times: list[float] = []
    dists: list[float] = [0.0]
    for i, vertex in enumerate(timed):
        assert vertex.time_s is not None
        times.append(vertex.time_s)
        if i:
            prev = timed[i - 1]
            dists.append(dists[-1] + math.hypot(vertex.x - prev.x, vertex.y - prev.y))
    best = 0.0
    j = 0
    for i in range(len(timed)):
        while times[i] - times[j] > window:
            j += 1
        span = times[i] - times[j]
        if span >= window * 0.8:
            best = max(best, (dists[i] - dists[j]) / span)
    if best <= ceiling:
        return []
    return [
        _mk(
            "DYN-007",
            f"Trajectory of '{traj.entity}' ({eclass}) sustains "
            f"{best:.1f} m/s over a ~{window:.0f} s window — beyond human "
            f"endurance capability (~{ceiling:.1f} m/s sustained: marathon "
            "record pace / cycling hour record).",
            scenario, traj.label or f"entity '{traj.entity}'",
            {"trajectory.sustained_mps": round(best, 2),
             "class.sustained_ceiling_mps": ceiling},
        )
    ]


def _menger_curvature(
    p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float]
) -> float:
    """Curvature of the circle through three points (0 for collinear/degenerate)."""
    d12 = math.dist(p1, p2)
    d23 = math.dist(p2, p3)
    d13 = math.dist(p1, p3)
    if d12 < 1e-9 or d23 < 1e-9 or d13 < 1e-9:
        return 0.0
    cross = (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0])
    return 2.0 * abs(cross) / (d12 * d23 * d13)
