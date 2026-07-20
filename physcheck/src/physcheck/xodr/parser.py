"""OpenDRIVE (.xodr) frontend for the map model.

Tolerant like the OSC frontend: anything unreadable becomes an entry in
``XodrMap.issues``, never an exception — L2 checks run on whatever could be
parsed, and MAP-000 surfaces the parse problems themselves.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from physcheck.xodr.model import (
    Geometry,
    GeoReference,
    Junction,
    Lane,
    LaneSection,
    Poly3,
    Road,
    RoadLink,
    SpeedRecord,
    XodrMap,
)

__all__ = ["load_map", "parse_map_string"]

#: OpenDRIVE speed record units -> m/s conversion factor.
_SPEED_UNIT_TO_MPS = {"m/s": 1.0, "ms": 1.0, "mph": 0.44704, "km/h": 1.0 / 3.6, "kmh": 1.0 / 3.6}


def load_map(path: str | Path) -> XodrMap:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        xmap = XodrMap(source_path=str(p))
        xmap.issues.append(f"cannot read map file: {exc}")
        return xmap
    return parse_map_string(text, source_path=str(p))


def parse_map_string(text: str, source_path: str = "<string>") -> XodrMap:
    xmap = XodrMap(source_path=source_path)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        xmap.issues.append(f"not well-formed XML: {exc}")
        return xmap
    if root.tag != "OpenDRIVE":
        xmap.issues.append(f"root element is <{root.tag}>, expected <OpenDRIVE>")
        return xmap

    geo_elem = root.find("header/geoReference")
    if geo_elem is not None and geo_elem.text:
        xmap.geo = _parse_geo_reference(geo_elem.text)

    for road_elem in root.findall("road"):
        road = _parse_road(road_elem, xmap)
        if road is not None:
            xmap.roads[road.road_id] = road

    for junction_elem in root.findall("junction"):
        junction_id = junction_elem.get("id")
        if junction_id is None:
            xmap.issues.append("junction without id skipped")
            continue
        junction = Junction(junction_id=junction_id)
        for conn in junction_elem.findall("connection"):
            incoming = conn.get("incomingRoad")
            connecting = conn.get("connectingRoad") or conn.get("linkedRoad")
            if incoming and connecting:
                junction.connections.append((incoming, connecting))
        xmap.junctions[junction_id] = junction

    if not xmap.roads:
        xmap.issues.append("map declares no <road> elements")
    return xmap


def _parse_geo_reference(raw: str) -> GeoReference:
    geo = GeoReference(raw=raw.strip())

    def grab(key: str) -> float | None:
        match = re.search(rf"\+{key}=([-+0-9.eE]+)", raw)
        if match is None:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    geo.lat0_deg = grab("lat_0")
    geo.lon0_deg = grab("lon_0")
    return geo


def _float(elem: ET.Element, attr: str, xmap: XodrMap, where: str) -> float | None:
    raw = elem.get(attr)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        xmap.issues.append(f"{where}@{attr}={raw!r} is not a number")
        return None


def _parse_road(road_elem: ET.Element, xmap: XodrMap) -> Road | None:
    road_id = road_elem.get("id")
    if road_id is None:
        xmap.issues.append("road without id skipped")
        return None
    where = f"road[{road_id}]"
    length = _float(road_elem, "length", xmap, where) or 0.0
    road = Road(
        road_id=road_id,
        name=road_elem.get("name", ""),
        length=length,
        junction=road_elem.get("junction", "-1"),
    )

    link = road_elem.find("link")
    if link is not None:
        for tag in ("predecessor", "successor"):
            ref = link.find(tag)
            if ref is None:
                continue
            kind = ref.get("elementType")
            ref_id = ref.get("elementId")
            if kind in ("road", "junction") and ref_id:
                setattr(road, tag, RoadLink(kind=kind, ref_id=ref_id))

    for type_elem in road_elem.findall("type"):
        s0 = _float(type_elem, "s", xmap, f"{where}/type") or 0.0
        speed = type_elem.find("speed")
        if speed is None:
            continue
        raw_max = speed.get("max")
        if raw_max is None or raw_max in ("no limit", "undefined"):
            continue
        try:
            value = float(raw_max)
        except ValueError:
            xmap.issues.append(f"{where}/type/speed@max={raw_max!r} is not a number")
            continue
        unit = speed.get("unit", "m/s")
        factor = _SPEED_UNIT_TO_MPS.get(unit)
        if factor is None:
            xmap.issues.append(f"{where}/type/speed@unit={unit!r} is not a known unit")
            continue
        road.speeds.append(SpeedRecord(s0=s0, max_mps=value * factor))
    road.speeds.sort(key=lambda rec: rec.s0)

    for geom_elem in road_elem.findall("planView/geometry"):
        geom = _parse_geometry(geom_elem, xmap, where)
        if geom is not None:
            road.geometries.append(geom)
    road.geometries.sort(key=lambda g: g.s0)

    lanes_elem = road_elem.find("lanes")
    if lanes_elem is not None:
        for offset_elem in lanes_elem.findall("laneOffset"):
            poly = _parse_poly3(offset_elem, "s", xmap, f"{where}/laneOffset")
            if poly is not None:
                road.lane_offsets.append(poly)
        road.lane_offsets.sort(key=lambda p: p.s0)
        for section_elem in lanes_elem.findall("laneSection"):
            s0 = _float(section_elem, "s", xmap, f"{where}/laneSection") or 0.0
            section = LaneSection(s0=s0)
            for side in ("left", "center", "right"):
                side_elem = section_elem.find(side)
                if side_elem is None:
                    continue
                for lane_elem in side_elem.findall("lane"):
                    lane = _parse_lane(lane_elem, xmap, f"{where}/laneSection")
                    if lane is not None:
                        section.lanes[lane.lane_id] = lane
            road.sections.append(section)
        road.sections.sort(key=lambda sec: sec.s0)

    if not road.geometries:
        xmap.issues.append(f"{where} has no <planView> geometry")
    if not road.sections:
        xmap.issues.append(f"{where} has no <laneSection>")
    return road


def _parse_geometry(geom_elem: ET.Element, xmap: XodrMap, where: str) -> Geometry | None:
    values = {}
    for attr in ("s", "x", "y", "hdg", "length"):
        value = _float(geom_elem, attr, xmap, f"{where}/geometry")
        if value is None:
            xmap.issues.append(f"{where}/geometry misses attribute {attr!r}")
            return None
        values[attr] = value
    geom = Geometry(
        s0=values["s"], x=values["x"], y=values["y"], hdg=values["hdg"],
        length=values["length"], gtype="line",
    )
    shape = next(iter(geom_elem), None)
    if shape is None or shape.tag == "line":
        return geom
    if shape.tag == "arc":
        geom.gtype = "arc"
        geom.curvature = _float(shape, "curvature", xmap, f"{where}/arc") or 0.0
        return geom
    if shape.tag == "spiral":
        geom.gtype = "spiral"
        geom.curv_start = _float(shape, "curvStart", xmap, f"{where}/spiral") or 0.0
        geom.curv_end = _float(shape, "curvEnd", xmap, f"{where}/spiral") or 0.0
        return geom
    if shape.tag == "poly3":
        geom.gtype = "poly3"
        geom.av = _float(shape, "a", xmap, f"{where}/poly3") or 0.0
        geom.bv = _float(shape, "b", xmap, f"{where}/poly3") or 0.0
        geom.cv = _float(shape, "c", xmap, f"{where}/poly3") or 0.0
        geom.dv = _float(shape, "d", xmap, f"{where}/poly3") or 0.0
        return geom
    if shape.tag == "paramPoly3":
        geom.gtype = "param_poly3"
        for name in ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV"):
            value = _float(shape, name, xmap, f"{where}/paramPoly3") or 0.0
            setattr(geom, name[0].lower() + name[1].lower(), value)
        geom.p_range = shape.get("pRange", "normalized")
        return geom
    xmap.issues.append(f"{where}/geometry has unknown shape <{shape.tag}>; treated as line")
    return geom


def _parse_poly3(elem: ET.Element, s_attr: str, xmap: XodrMap, where: str) -> Poly3 | None:
    s0 = _float(elem, s_attr, xmap, where)
    if s0 is None:
        s0 = 0.0
    return Poly3(
        s0=s0,
        a=_float(elem, "a", xmap, where) or 0.0,
        b=_float(elem, "b", xmap, where) or 0.0,
        c=_float(elem, "c", xmap, where) or 0.0,
        d=_float(elem, "d", xmap, where) or 0.0,
    )


def _parse_lane(lane_elem: ET.Element, xmap: XodrMap, where: str) -> Lane | None:
    raw_id = lane_elem.get("id")
    if raw_id is None:
        xmap.issues.append(f"{where} lane without id skipped")
        return None
    try:
        lane_id = int(raw_id)
    except ValueError:
        xmap.issues.append(f"{where} lane id {raw_id!r} is not an integer")
        return None
    lane = Lane(lane_id=lane_id, ltype=lane_elem.get("type", "none"))
    for width_elem in lane_elem.findall("width"):
        poly = _parse_poly3(width_elem, "sOffset", xmap, f"{where}/lane[{lane_id}]/width")
        if poly is not None:
            lane.widths.append(poly)
    lane.widths.sort(key=lambda p: p.s0)
    return lane
