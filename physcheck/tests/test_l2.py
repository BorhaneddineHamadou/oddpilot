"""L2 tier: OpenDRIVE parsing/geometry, ephemeris, and the MAP/GEO rules."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from physcheck.engine.catalog import RuleSpec
from physcheck.engine.engine import lint_scenario
from physcheck.engine.plugins.l2_map import PLUGIN_RULES as MAP_RULES
from physcheck.engine.plugins.l2_solar_geo import PLUGIN_RULES as GEO_RULES
from physcheck.ephemeris import solar_declination_deg, solar_position_deg
from physcheck.ir.osc_parser import parse_file
from physcheck.xodr import XodrMap, load_map

FIXTURES = Path(__file__).resolve().parent / "fixtures"
L2 = FIXTURES / "l2"
_VIOLATING = sorted(p for p in L2.glob("*.xosc") if not p.name.startswith("valid_"))


@pytest.fixture(scope="module")
def tiny_map() -> XodrMap:
    xmap = load_map(FIXTURES / "maps" / "tiny.xodr")
    assert not xmap.issues, xmap.issues
    return xmap


def _map_for(path: Path) -> XodrMap:
    scenario = parse_file(path)
    assert scenario.road_network_logic_file is not None
    return load_map(path.parent / scenario.road_network_logic_file)


# -- xodr parsing and geometry ---------------------------------------------


def test_map_inventory(tiny_map: XodrMap) -> None:
    assert set(tiny_map.roads) == {"1", "2", "20", "3", "99"}
    assert set(tiny_map.junctions) == {"10"}
    assert tiny_map.geo.lat0_deg == pytest.approx(48.9917)
    assert tiny_map.geo.lon0_deg == pytest.approx(8.0019)
    assert tiny_map.roads["1"].speeds[0].max_mps == pytest.approx(50 / 3.6)


def test_reference_line_and_lanes(tiny_map: XodrMap) -> None:
    road = tiny_map.roads["1"]
    assert road.ref_point(50.0) == pytest.approx((50.0, 0.0, 0.0))
    assert road.lane_t_range(50.0, -1) == pytest.approx((0.0, -3.5))
    center = road.lane_center(50.0, -1)
    assert center is not None and center[:2] == pytest.approx((50.0, -1.75))
    assert road.lane_id_at(50.0, -1.75) == -1
    assert road.lane_id_at(50.0, 4.5) == 2  # sidewalk
    assert road.lane_id_at(50.0, -9.0) is None  # off the road


def test_projection_and_candidates(tiny_map: XodrMap) -> None:
    projected = tiny_map.project(30.0, -1.75)
    assert projected is not None
    road_id, s, t, _dist = projected
    assert road_id == "1"
    assert s == pytest.approx(30.0)
    assert t == pytest.approx(-1.75)
    lanes = tiny_map.candidate_lanes(30.0, -1.75)
    assert [(lane[0], lane[2], lane[3]) for lane in lanes] == [("1", -1, "driving")]
    assert tiny_map.candidate_lanes(30.0, 300.0) == []


def test_connectivity(tiny_map: XodrMap) -> None:
    assert tiny_map.connected("1", "3")  # via road 2 and junction 10
    assert not tiny_map.connected("1", "99")


def test_arc_and_spiral_geometry() -> None:
    from physcheck.xodr.model import Geometry

    arc = Geometry(s0=0, x=0, y=0, hdg=0, length=math.pi * 25, gtype="arc", curvature=1 / 50)
    _s, x, y, hdg = arc.sample()[-1]
    assert x == pytest.approx(50, abs=1e-3)
    assert y == pytest.approx(50, abs=1e-3)
    assert hdg == pytest.approx(math.pi / 2)
    spiral = Geometry(s0=0, x=0, y=0, hdg=0, length=100, gtype="spiral",
                      curv_start=0, curv_end=1 / 50)
    _s, _x, _y, hdg = spiral.sample()[-1]
    assert hdg == pytest.approx(1.0, abs=1e-4)  # 0.5 * c_end * L


def test_broken_map_reports_issues() -> None:
    xmap = load_map(FIXTURES / "maps" / "broken.xodr")
    assert xmap.issues and "fifty" in xmap.issues[0]
    assert "1" in xmap.roads  # still usable


# -- ephemeris --------------------------------------------------------------


def test_declination_bounds() -> None:
    assert solar_declination_deg(datetime(2010, 6, 21, 12)) == pytest.approx(23.44, abs=0.05)
    assert solar_declination_deg(datetime(2010, 12, 21, 12)) == pytest.approx(-23.44, abs=0.05)
    assert solar_declination_deg(datetime(2010, 3, 20, 12)) == pytest.approx(0.0, abs=0.4)


def test_solar_position_noaa_reference() -> None:
    # NOAA solar calculator, Boulder CO (40.125 N, 105.2372 W), 2010-06-21
    # 13:02 MDT (19:02 UTC): elevation ~73.4 deg, azimuth ~180 deg.
    elev, azim = solar_position_deg(
        datetime(2010, 6, 21, 19, 2, tzinfo=timezone.utc), 40.125, -105.2372
    )
    assert elev == pytest.approx(73.4, abs=0.3)
    assert azim == pytest.approx(180.0, abs=1.5)


def test_solar_position_night() -> None:
    elev, _ = solar_position_deg(datetime(2020, 7, 1, 20, 0), 49.0, 8.4)
    assert elev < 0


# -- MAP/GEO rules over fixtures -------------------------------------------


def test_every_l2_rule_has_a_violating_fixture() -> None:
    fixture_ids = {p.stem for p in _VIOLATING}
    assert set(MAP_RULES) | set(GEO_RULES) == fixture_ids


@pytest.mark.parametrize("path", _VIOLATING, ids=lambda p: p.stem)
def test_violating_l2_fixture_triggers_its_rule(
    path: Path, all_rules: list[RuleSpec]
) -> None:
    scenario = parse_file(path)
    result = lint_scenario(scenario, all_rules, {"L2"}, xodr_map=_map_for(path))
    fired = {f.rule_id for f in result.findings}
    assert path.stem in fired, f"{path.stem} expected in findings, got {sorted(fired)}"


def test_valid_l2_fixture_is_clean(all_rules: list[RuleSpec]) -> None:
    path = L2 / "valid_l2_clean.xosc"
    scenario = parse_file(path)
    result = lint_scenario(
        scenario, all_rules, {"L0", "L1", "L2"}, xodr_map=_map_for(path)
    )
    assert result.findings == [], [(f.rule_id, f.message) for f in result.findings]


def test_l2_without_map_adds_no_findings(all_rules: list[RuleSpec]) -> None:
    path = L2 / "MAP-001.xosc"
    scenario = parse_file(path)
    result = lint_scenario(scenario, all_rules, {"L2"}, xodr_map=None)
    assert result.findings == []


def _inline_scenario(init_privates: str) -> str:
    return f"""<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="2026-07-20T12:00:00"
              description="inline" author="physcheck"/>
  <RoadNetwork><LogicFile filepath="../maps/tiny.xodr"/></RoadNetwork>
  <Entities>
    <ScenarioObject name="ego"><Vehicle name="m" vehicleCategory="car" mass="1600">
      <BoundingBox><Center x="0" y="0" z="0"/>
      <Dimensions length="4.6" width="1.86" height="1.5"/></BoundingBox>
      <Performance maxSpeed="62" maxAcceleration="5" maxDeceleration="9"/>
    </Vehicle></ScenarioObject>
    <ScenarioObject name="npc"><Vehicle name="m" vehicleCategory="car" mass="1600">
      <BoundingBox><Center x="0" y="0" z="0"/>
      <Dimensions length="4.6" width="1.86" height="1.5"/></BoundingBox>
      <Performance maxSpeed="62" maxAcceleration="5" maxDeceleration="9"/>
    </Vehicle></ScenarioObject>
  </Entities>
  <Storyboard><Init><Actions>
{init_privates}
  </Actions></Init></Storyboard>
</OpenSCENARIO>
"""


def test_map004_hints_at_carla_mirrored_frame(
    tiny_map: XodrMap, all_rules: list[RuleSpec]
) -> None:
    from physcheck.ir.osc_parser import parse_string

    # (30, -500) is off every lane; its mirror (30, 500) is on island road 99.
    xml = _inline_scenario(
        '<Private entityRef="ego"><PrivateAction><TeleportAction><Position>'
        '<WorldPosition x="30" y="-500" z="0" h="0"/>'
        "</Position></TeleportAction></PrivateAction></Private>"
    )
    result = lint_scenario(parse_string(xml), all_rules, {"L2"}, xodr_map=tiny_map)
    map004 = [f for f in result.findings if f.rule_id == "MAP-004"]
    assert len(map004) == 1
    assert "left-handed frame" in map004[0].message


def test_map005_skips_relative_attached_entities(
    tiny_map: XodrMap, all_rules: list[RuleSpec]
) -> None:
    from physcheck.ir.osc_parser import parse_string

    xml = _inline_scenario(
        '<Private entityRef="ego"><PrivateAction><TeleportAction><Position>'
        '<WorldPosition x="30" y="-1.75" z="0" h="0"/>'
        "</Position></TeleportAction></PrivateAction></Private>"
        '<Private entityRef="npc"><PrivateAction><TeleportAction><Position>'
        '<RelativeObjectPosition entityRef="ego" dx="0.5" dy="0" dz="0.2"/>'
        "</Position></TeleportAction></PrivateAction></Private>"
    )
    result = lint_scenario(parse_string(xml), all_rules, {"L2"}, xodr_map=tiny_map)
    assert [f for f in result.findings if f.rule_id == "MAP-005"] == []


def test_solar_geo_skipped_without_geo_anchor(all_rules: list[RuleSpec]) -> None:
    xmap = XodrMap()  # no geoReference at all
    scenario = parse_file(L2 / "GEO-001.xosc")
    result = lint_scenario(scenario, all_rules, {"L2"}, xodr_map=xmap)
    geo_findings = [f for f in result.findings if f.rule_id.startswith("GEO-")]
    assert geo_findings == []
