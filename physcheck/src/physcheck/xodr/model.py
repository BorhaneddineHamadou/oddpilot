"""Typed OpenDRIVE map model with just enough geometry for map cross-checks.

Scope (docs/decisions.md D21): reference-line geometry (line, arc, spiral,
poly3, paramPoly3) is evaluated by sampling at ~0.5 m; world->road projection
is nearest-sample with linear refinement, giving centimetre-level accuracy —
far tighter than the half-lane-width tolerances any L2 rule uses. Elevation
profiles and superelevation are not modelled (all checks are planar).

Supports OpenDRIVE 1.1 through 1.8 documents (the elements read here are
stable across revisions; 1.4-era lane types like ``mwyEntry`` are kept).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

__all__ = [
    "GeoReference",
    "Geometry",
    "Junction",
    "Lane",
    "LaneSection",
    "Poly3",
    "Road",
    "RoadLink",
    "SpeedRecord",
    "XodrMap",
]

_SAMPLE_STEP_M = 0.5


@dataclass
class Poly3:
    """Cubic polynomial record a + b*ds + c*ds^2 + d*ds^3 valid from ``s0``."""

    s0: float
    a: float
    b: float
    c: float
    d: float

    def eval(self, ds: float) -> float:
        return self.a + self.b * ds + self.c * ds * ds + self.d * ds * ds * ds


def _pick(records: list[Poly3], s: float) -> Poly3 | None:
    """Last record whose s0 <= s (records are kept sorted by s0)."""
    chosen: Poly3 | None = None
    for rec in records:
        if rec.s0 <= s + 1e-9:
            chosen = rec
        else:
            break
    return chosen


@dataclass
class Geometry:
    """One <planView><geometry> element."""

    s0: float
    x: float
    y: float
    hdg: float
    length: float
    #: line | arc | spiral | poly3 | param_poly3
    gtype: str
    #: arc: curvature; spiral: (curvStart, curvEnd); poly3/paramPoly3: coefficients.
    curvature: float = 0.0
    curv_start: float = 0.0
    curv_end: float = 0.0
    au: float = 0.0
    bu: float = 0.0
    cu: float = 0.0
    du: float = 0.0
    av: float = 0.0
    bv: float = 0.0
    cv: float = 0.0
    dv: float = 0.0
    #: paramPoly3 pRange: normalized -> parameter in [0,1]; arcLength -> [0,length].
    p_range: str = "normalized"

    def sample(self, step: float = _SAMPLE_STEP_M) -> list[tuple[float, float, float, float]]:
        """Sample as (s, x, y, hdg) tuples, s measured along the road."""
        if self.length <= 0:
            return []
        if self.gtype == "line":
            return self._sample_line(step)
        if self.gtype == "arc":
            return self._sample_arc(step)
        if self.gtype == "spiral":
            return self._sample_spiral(step)
        return self._sample_poly(step)

    def _steps(self, step: float) -> list[float]:
        n = max(2, math.ceil(self.length / step) + 1)
        return [self.length * i / (n - 1) for i in range(n)]

    def _sample_line(self, step: float) -> list[tuple[float, float, float, float]]:
        cos_h, sin_h = math.cos(self.hdg), math.sin(self.hdg)
        return [
            (self.s0 + ds, self.x + ds * cos_h, self.y + ds * sin_h, self.hdg)
            for ds in self._steps(step)
        ]

    def _sample_arc(self, step: float) -> list[tuple[float, float, float, float]]:
        c = self.curvature
        if abs(c) < 1e-12:
            return self._sample_line(step)
        out = []
        for ds in self._steps(step):
            hdg = self.hdg + c * ds
            x = self.x + (math.sin(hdg) - math.sin(self.hdg)) / c
            y = self.y - (math.cos(hdg) - math.cos(self.hdg)) / c
            out.append((self.s0 + ds, x, y, hdg))
        return out

    def _sample_spiral(self, step: float) -> list[tuple[float, float, float, float]]:
        # Numerical heading integration (midpoint rule) of the clothoid
        # k(ds) = curv_start + (curv_end - curv_start) * ds / length.
        rate = (self.curv_end - self.curv_start) / self.length
        out = [(self.s0, self.x, self.y, self.hdg)]
        x, y, hdg = self.x, self.y, self.hdg
        steps = self._steps(min(step, 0.25))
        for prev, cur in itertools.pairwise(steps):
            d = cur - prev
            mid = prev + d / 2
            hdg_mid = self.hdg + self.curv_start * mid + rate * mid * mid / 2
            x += d * math.cos(hdg_mid)
            y += d * math.sin(hdg_mid)
            hdg = self.hdg + self.curv_start * cur + rate * cur * cur / 2
            out.append((self.s0 + cur, x, y, hdg))
        return _resample(out, step)

    def _sample_poly(self, step: float) -> list[tuple[float, float, float, float]]:
        # Local (u, v) curve rotated into the inertial frame; s approximated by
        # chord-length accumulation (docs/decisions.md D21).
        cos_h, sin_h = math.cos(self.hdg), math.sin(self.hdg)
        n = max(8, math.ceil(self.length / min(step, 0.25)) + 1)
        pts_local: list[tuple[float, float]] = []
        for i in range(4 * n):
            if self.gtype == "poly3":
                u = self.length * 2.0 * i / (4 * n - 1)  # generous u span; trimmed by length
                v = self.av + self.bv * u + self.cv * u * u + self.dv * u * u * u
            else:
                p_max = 1.0 if self.p_range == "normalized" else self.length
                p = p_max * i / (4 * n - 1)
                u = self.au + self.bu * p + self.cu * p * p + self.du * p * p * p
                v = self.av + self.bv * p + self.cv * p * p + self.dv * p * p * p
            pts_local.append((u, v))
        out: list[tuple[float, float, float, float]] = []
        arc = 0.0
        prev_xy: tuple[float, float] | None = None
        for i, (u, v) in enumerate(pts_local):
            x = self.x + u * cos_h - v * sin_h
            y = self.y + u * sin_h + v * cos_h
            if prev_xy is not None:
                arc += math.hypot(x - prev_xy[0], y - prev_xy[1])
            prev_xy = (x, y)
            if i + 1 < len(pts_local):
                nu, nv = pts_local[i + 1]
                hdg = self.hdg + math.atan2(nv - v, nu - u)
            out.append((self.s0 + arc, x, y, hdg))
            if arc >= self.length:
                break
        return _resample(out, step)


def _resample(
    pts: list[tuple[float, float, float, float]], step: float
) -> list[tuple[float, float, float, float]]:
    """Thin a finely sampled polyline back to roughly ``step`` spacing."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for pt in pts[1:-1]:
        if pt[0] - out[-1][0] >= step:
            out.append(pt)
    out.append(pts[-1])
    return out


@dataclass
class Lane:
    lane_id: int
    ltype: str
    widths: list[Poly3] = field(default_factory=list)

    def width_at(self, ds: float) -> float:
        rec = _pick(self.widths, ds)
        if rec is None:
            return 0.0
        return max(0.0, rec.eval(ds - rec.s0))


@dataclass
class LaneSection:
    s0: float
    #: lane id -> Lane; id 0 is the (zero-width) centre lane.
    lanes: dict[int, Lane] = field(default_factory=dict)


@dataclass
class SpeedRecord:
    s0: float
    max_mps: float


@dataclass
class RoadLink:
    #: "road" | "junction"
    kind: str
    ref_id: str


@dataclass
class Road:
    road_id: str
    name: str
    length: float
    #: "-1" outside junctions, else the junction id.
    junction: str
    predecessor: RoadLink | None = None
    successor: RoadLink | None = None
    speeds: list[SpeedRecord] = field(default_factory=list)
    geometries: list[Geometry] = field(default_factory=list)
    lane_offsets: list[Poly3] = field(default_factory=list)
    sections: list[LaneSection] = field(default_factory=list)
    _samples: list[tuple[float, float, float, float]] | None = None

    # -- reference line ----------------------------------------------------
    def samples(self) -> list[tuple[float, float, float, float]]:
        """Sampled reference line as (s, x, y, hdg), ~0.5 m spacing."""
        if self._samples is None:
            pts: list[tuple[float, float, float, float]] = []
            for geom in self.geometries:
                seg = geom.sample()
                if pts and seg and abs(seg[0][0] - pts[-1][0]) < 1e-6:
                    seg = seg[1:]
                pts.extend(seg)
            self._samples = pts
        return self._samples

    def ref_point(self, s: float) -> tuple[float, float, float] | None:
        """(x, y, hdg) at arc length s, linearly interpolated."""
        pts = self.samples()
        if not pts:
            return None
        s = min(max(s, pts[0][0]), pts[-1][0])
        lo, hi = 0, len(pts) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if pts[mid][0] <= s:
                lo = mid
            else:
                hi = mid
        s0, x0, y0, h0 = pts[lo]
        s1, x1, y1, h1 = pts[hi]
        if s1 <= s0:
            return (x0, y0, h0)
        f = (s - s0) / (s1 - s0)
        dh = math.atan2(math.sin(h1 - h0), math.cos(h1 - h0))
        return (x0 + f * (x1 - x0), y0 + f * (y1 - y0), h0 + f * dh)

    def curvature_at(self, s: float) -> float | None:
        """|curvature| of the reference line at arc length s (1/m), from the
        heading difference of the surrounding ~0.5 m samples — uniform across
        line/arc/spiral/poly geometries."""
        pts = self.samples()
        if len(pts) < 2:
            return None
        s = min(max(s, pts[0][0]), pts[-1][0])
        lo, hi = 0, len(pts) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if pts[mid][0] <= s:
                lo = mid
            else:
                hi = mid
        s0, _x0, _y0, h0 = pts[lo]
        s1, _x1, _y1, h1 = pts[hi]
        if s1 <= s0:
            return None
        dh = math.atan2(math.sin(h1 - h0), math.cos(h1 - h0))
        return abs(dh / (s1 - s0))

    # -- lanes -------------------------------------------------------------
    def section_at(self, s: float) -> LaneSection | None:
        chosen: LaneSection | None = None
        for section in self.sections:
            if section.s0 <= s + 1e-9:
                chosen = section
            else:
                break
        return chosen

    def lane_offset_at(self, s: float) -> float:
        rec = _pick(self.lane_offsets, s)
        return rec.eval(s - rec.s0) if rec is not None else 0.0

    def lane_t_range(self, s: float, lane_id: int) -> tuple[float, float] | None:
        """Lateral [t_inner, t_outer] interval of a lane at s (t_inner may be > t_outer
        for right lanes; callers should use min/max)."""
        section = self.section_at(s)
        if section is None or lane_id not in section.lanes or lane_id == 0:
            return None
        ds = s - section.s0
        t = self.lane_offset_at(s)
        sign = 1 if lane_id > 0 else -1
        for i in range(1, abs(lane_id) + 1):
            lane = section.lanes.get(sign * i)
            if lane is None:
                return None
            inner = t
            t += sign * lane.width_at(ds)
            if i == abs(lane_id):
                return (inner, t)
        return None

    def lane_center(self, s: float, lane_id: int) -> tuple[float, float, float] | None:
        """World (x, y, heading) of the lane centre at s; heading follows travel
        direction (right lanes run against the reference line)."""
        rng = self.lane_t_range(s, lane_id)
        ref = self.ref_point(s)
        if rng is None or ref is None:
            return None
        t = (rng[0] + rng[1]) / 2
        x, y, hdg = ref
        x += t * -math.sin(hdg)
        y += t * math.cos(hdg)
        # Left lanes (positive ids) run against s in right-hand traffic.
        heading = hdg + math.pi if lane_id > 0 else hdg
        return (x, y, heading)

    def lane_id_at(self, s: float, t: float) -> int | None:
        """Lane containing lateral offset t at s, or None when off the road."""
        section = self.section_at(s)
        if section is None:
            return None
        for lane_id in section.lanes:
            if lane_id == 0:
                continue
            rng = self.lane_t_range(s, lane_id)
            if rng is None:
                continue
            lo, hi = min(rng), max(rng)
            if lo - 1e-6 <= t <= hi + 1e-6:
                return lane_id
        return None


@dataclass
class Junction:
    junction_id: str
    #: (incoming road id, connecting road id) pairs.
    connections: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class GeoReference:
    raw: str = ""
    lat0_deg: float | None = None
    lon0_deg: float | None = None


@dataclass
class XodrMap:
    source_path: str = "<string>"
    roads: dict[str, Road] = field(default_factory=dict)
    junctions: dict[str, Junction] = field(default_factory=dict)
    geo: GeoReference = field(default_factory=GeoReference)
    #: Problems found while parsing (map is still usable; see parser module).
    issues: list[str] = field(default_factory=list)

    def project(self, x: float, y: float) -> tuple[str, float, float, float] | None:
        """Nearest (road_id, s, t, distance-to-reference-line) for a world point."""
        best: tuple[str, float, float, float] | None = None
        for road in self.roads.values():
            for s, px, py, hdg in road.samples():
                dx, dy = x - px, y - py
                dist = math.hypot(dx, dy)
                if best is None or dist < best[3]:
                    # signed lateral offset: positive t is left of the reference line
                    t = -dx * math.sin(hdg) + dy * math.cos(hdg)
                    best = (road.road_id, s, t, dist)
        return best

    def candidate_lanes(
        self, x: float, y: float, max_ref_dist: float = 25.0
    ) -> list[tuple[str, float, int, str]]:
        """All (road_id, s, lane_id, lane_type) whose lane interval contains the
        point, across overlapping roads (junctions overlap by construction)."""
        out: list[tuple[str, float, int, str]] = []
        for road in self.roads.values():
            best: tuple[float, float, float] | None = None  # (dist, s, t)
            for s, px, py, hdg in road.samples():
                dx, dy = x - px, y - py
                dist = math.hypot(dx, dy)
                if best is None or dist < best[0]:
                    t = -dx * math.sin(hdg) + dy * math.cos(hdg)
                    best = (dist, s, t)
            if best is None or best[0] > max_ref_dist:
                continue
            _dist, s, t = best
            lane_id = road.lane_id_at(s, t)
            if lane_id is not None:
                section = road.section_at(s)
                if section is not None and lane_id in section.lanes:
                    out.append((road.road_id, s, lane_id, section.lanes[lane_id].ltype))
        return out

    def adjacency(self) -> dict[str, set[str]]:
        """Undirected road-connectivity graph over links and junction connections
        (docs/decisions.md D22: direction-agnostic, existence-of-path check only)."""
        adj: dict[str, set[str]] = {rid: set() for rid in self.roads}

        def connect(a: str, b: str) -> None:
            if a in adj and b in adj:
                adj[a].add(b)
                adj[b].add(a)

        for road in self.roads.values():
            for link in (road.predecessor, road.successor):
                if link is None:
                    continue
                if link.kind == "road":
                    connect(road.road_id, link.ref_id)
                elif link.kind == "junction":
                    junction = self.junctions.get(link.ref_id)
                    if junction is not None:
                        for incoming, connecting in junction.connections:
                            if incoming == road.road_id:
                                connect(road.road_id, connecting)
        for junction in self.junctions.values():
            for incoming, connecting in junction.connections:
                connect(incoming, connecting)
        return adj

    def connected(self, road_a: str, road_b: str) -> bool:
        """True when a path exists between two roads in the adjacency graph."""
        if road_a == road_b:
            return True
        adj = self.adjacency()
        if road_a not in adj or road_b not in adj:
            return False
        seen = {road_a}
        frontier = [road_a]
        while frontier:
            current = frontier.pop()
            for nxt in adj[current]:
                if nxt == road_b:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return False
