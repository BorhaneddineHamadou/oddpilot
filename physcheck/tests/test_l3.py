"""L3 tier: trajectory IR capture, curvature, and the DYN kinematics rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from physcheck.engine.engine import lint_scenario
from physcheck.engine.plugins.l3_kinematics import (
    PLUGIN_RULES,
    kinematic_findings,
)
from physcheck.ir.osc_parser import parse_string
from physcheck.xodr import XodrMap, load_map

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def curve_map() -> XodrMap:
    xmap = load_map(FIXTURES / "maps" / "curve.xodr")
    assert not xmap.issues, xmap.issues
    return xmap


def _scenario(body: str, env: str = "") -> str:
    return f"""<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="2026-07-21T12:00:00"
              description="l3 test" author="physcheck"/>
  <RoadNetwork><LogicFile filepath="curve.xodr"/></RoadNetwork>
  <Entities>
    <ScenarioObject name="ego">
      <Vehicle name="car" vehicleCategory="car" mass="1600">
        <BoundingBox><Center x="0" y="0" z="0"/>
          <Dimensions length="4.6" width="1.86" height="1.5"/></BoundingBox>
        <Performance maxSpeed="62" maxAcceleration="5" maxDeceleration="9"/>
      </Vehicle>
    </ScenarioObject>
    <ScenarioObject name="walker">
      <Pedestrian name="ped" pedestrianCategory="pedestrian" mass="80">
        <BoundingBox><Center x="0" y="0" z="0"/>
          <Dimensions length="0.5" width="0.6" height="1.8"/></BoundingBox>
      </Pedestrian>
    </ScenarioObject>
  </Entities>
  <Storyboard>
    <Init>
      <Actions>
        {env}
        {body}
      </Actions>
    </Init>
  </Storyboard>
</OpenSCENARIO>"""


def _teleport(entity: str, road: str = "C1", lane: str = "-1", s: float = 39.0) -> str:
    return f"""<Private entityRef="{entity}">
      <PrivateAction><TeleportAction><Position>
        <LanePosition roadId="{road}" laneId="{lane}" s="{s}" offset="0"/>
      </Position></TeleportAction></PrivateAction>
    </Private>"""


def _speed(entity: str, mps: float) -> str:
    return f"""<Private entityRef="{entity}">
      <PrivateAction><LongitudinalAction><SpeedAction>
        <SpeedActionDynamics dynamicsShape="step" value="0" dynamicsDimension="time"/>
        <SpeedActionTarget><AbsoluteTargetSpeed value="{mps}"/></SpeedActionTarget>
      </SpeedAction></LongitudinalAction></PrivateAction>
    </Private>"""


def _trajectory(entity: str, points: list[tuple[float, float, float]]) -> str:
    vertices = "".join(
        f'<Vertex time="{t}"><Position><WorldPosition x="{x}" y="{y}"/></Position></Vertex>'
        for t, x, y in points
    )
    return f"""<Private entityRef="{entity}">
      <PrivateAction><RoutingAction><FollowTrajectoryAction>
        <Trajectory name="traj_{entity}" closed="false">
          <Shape><Polyline>{vertices}</Polyline></Shape>
        </Trajectory>
        <TimeReference><Timing domainAbsoluteRelative="absolute" scale="1"
                                offset="0"/></TimeReference>
        <TrajectoryFollowingMode followingMode="position"/>
      </FollowTrajectoryAction></RoutingAction></PrivateAction>
    </Private>"""


_WET_ENV = """<GlobalAction><EnvironmentAction><Environment name="wet">
  <Weather><Precipitation precipitationType="rain" precipitationIntensity="8"/></Weather>
  <RoadCondition wetness="highFlooded"/>
</Environment></EnvironmentAction></GlobalAction>"""

_FRICTION_ENV = """<GlobalAction><EnvironmentAction><Environment name="slick">
  <Weather/>
  <RoadCondition frictionScaleFactor="0.3"/>
</Environment></EnvironmentAction></GlobalAction>"""


def _ids(findings: list) -> set[str]:  # type: ignore[type-arg]
    return {f.rule_id for f in findings}


# -- IR capture -------------------------------------------------------------


def test_parser_captures_polyline_trajectory() -> None:
    xml = _scenario(_trajectory("ego", [(0, 0, 0), (1, 10, 0), (2, 20, 0)]))
    scenario = parse_string(xml)
    assert len(scenario.trajectories) == 1
    traj = scenario.trajectories[0]
    assert traj.entity == "ego"
    assert traj.shape == "polyline"
    assert traj.total_vertices == 3
    assert [v.x for v in traj.vertices] == [0.0, 10.0, 20.0]
    assert traj.vertices[1].time_s == 1.0


def test_parser_captures_trajectory_ref_and_counts_nonworld() -> None:
    xml = _scenario("""<Private entityRef="ego">
      <PrivateAction><RoutingAction><FollowTrajectoryAction>
        <TrajectoryRef><Trajectory name="t" closed="false"><Shape><Polyline>
          <Vertex time="0"><Position><WorldPosition x="0" y="0"/></Position></Vertex>
          <Vertex time="1"><Position><LanePosition roadId="C1" laneId="-1" s="5"
            offset="0"/></Position></Vertex>
          <Vertex time="2"><Position><WorldPosition x="20" y="0"/></Position></Vertex>
        </Polyline></Shape></Trajectory></TrajectoryRef>
      </FollowTrajectoryAction></RoutingAction></PrivateAction>
    </Private>""")
    scenario = parse_string(xml)
    traj = scenario.trajectories[0]
    assert traj.total_vertices == 3
    assert len(traj.vertices) == 2  # the LanePosition vertex is counted, not kept


def test_parser_flags_nonpolyline_shape() -> None:
    xml = _scenario("""<Private entityRef="ego">
      <PrivateAction><RoutingAction><FollowTrajectoryAction>
        <Trajectory name="t" closed="false"><Shape>
          <Clothoid curvature="0.01" curvatureDot="0" length="50"/>
        </Shape></Trajectory>
      </FollowTrajectoryAction></RoutingAction></PrivateAction>
    </Private>""")
    scenario = parse_string(xml)
    assert scenario.trajectories[0].shape == "clothoid"
    assert scenario.trajectories[0].vertices == []


# -- curvature --------------------------------------------------------------


def test_curvature_at(curve_map: XodrMap) -> None:
    road = curve_map.roads["C1"]
    kappa = road.curvature_at(39.0)
    assert kappa == pytest.approx(0.02, rel=0.05)


# -- DYN-001 curve speed ----------------------------------------------------


def test_dyn001_fires_on_infeasible_curve_speed(curve_map: XodrMap) -> None:
    xml = _scenario(_teleport("ego") + _speed("ego", 40.0))
    findings = kinematic_findings(parse_string(xml), curve_map)
    assert "DYN-001" in _ids(findings)


def test_dyn001_clean_at_feasible_speed(curve_map: XodrMap) -> None:
    xml = _scenario(_teleport("ego") + _speed("ego", 15.0))
    findings = kinematic_findings(parse_string(xml), curve_map)
    assert "DYN-001" not in _ids(findings)


def test_dyn001_needs_map() -> None:
    xml = _scenario(_teleport("ego") + _speed("ego", 40.0))
    assert "DYN-001" not in _ids(kinematic_findings(parse_string(xml), None))


def test_dyn001_ignores_world_position_spawns(curve_map: XodrMap) -> None:
    # World positions are NOT projected onto a road (D32): at junctions the
    # nearest reference line is often a corner arc the vehicle never drives.
    world_teleport = """<Private entityRef="ego">
      <PrivateAction><TeleportAction><Position>
        <WorldPosition x="49.0" y="-12.0" h="0"/>
      </Position></TeleportAction></PrivateAction>
    </Private>"""
    xml = _scenario(world_teleport + _speed("ego", 40.0))
    assert "DYN-001" not in _ids(kinematic_findings(parse_string(xml), curve_map))


# -- DYN-002 lane change ----------------------------------------------------


def test_dyn002_fires_on_impossible_lane_change() -> None:
    xml = _scenario(_teleport("ego")).replace(
        "</Storyboard>",
        """<Story name="s"><Act name="a"><ManeuverGroup name="mg" maximumExecutionCount="1">
        <Actors selectTriggeringEntities="false"><EntityRef entityRef="ego"/></Actors>
        <Maneuver name="m"><Event name="e" priority="overwrite"><Action name="lc">
        <PrivateAction><LateralAction><LaneChangeAction>
          <LaneChangeActionDynamics dynamicsShape="sinusoidal" value="0.5"
                                    dynamicsDimension="time"/>
          <LaneChangeTarget><RelativeTargetLane entityRef="ego" value="1"/></LaneChangeTarget>
        </LaneChangeAction></LateralAction></PrivateAction>
        </Action></Event></Maneuver></ManeuverGroup></Act></Story></Storyboard>""",
    )
    findings = kinematic_findings(parse_string(xml), None)
    assert "DYN-002" in _ids(findings)


def test_dyn002_clean_on_normal_lane_change() -> None:
    xml = _scenario(_teleport("ego")).replace(
        "</Storyboard>",
        """<Story name="s"><Act name="a"><ManeuverGroup name="mg" maximumExecutionCount="1">
        <Actors selectTriggeringEntities="false"><EntityRef entityRef="ego"/></Actors>
        <Maneuver name="m"><Event name="e" priority="overwrite"><Action name="lc">
        <PrivateAction><LateralAction><LaneChangeAction>
          <LaneChangeActionDynamics dynamicsShape="sinusoidal" value="3.0"
                                    dynamicsDimension="time"/>
          <LaneChangeTarget><RelativeTargetLane entityRef="ego" value="1"/></LaneChangeTarget>
        </LaneChangeAction></LateralAction></PrivateAction>
        </Action></Event></Maneuver></ManeuverGroup></Act></Story></Storyboard>""",
    )
    findings = kinematic_findings(parse_string(xml), None)
    assert "DYN-002" not in _ids(findings)


# -- DYN-003 speed rate vs surface ------------------------------------------


def test_dyn003_composes_with_wet_surface() -> None:
    body = _teleport("ego") + """<Private entityRef="ego">
      <PrivateAction><LongitudinalAction><SpeedAction>
        <SpeedActionDynamics dynamicsShape="linear" value="8" dynamicsDimension="rate"/>
        <SpeedActionTarget><AbsoluteTargetSpeed value="20"/></SpeedActionTarget>
      </SpeedAction></LongitudinalAction></PrivateAction>
    </Private>"""
    clean = kinematic_findings(parse_string(_scenario(body)), None)
    assert "DYN-003" not in _ids(clean)  # 8 m/s^2 is fine on dry
    wet = kinematic_findings(parse_string(_scenario(body, env=_WET_ENV)), None)
    assert "DYN-003" in _ids(wet)  # impossible on a flooded road (mu <= 0.4)


def test_dyn003_uses_declared_friction_scale() -> None:
    body = _teleport("ego") + """<Private entityRef="ego">
      <PrivateAction><LongitudinalAction><SpeedAction>
        <SpeedActionDynamics dynamicsShape="linear" value="8" dynamicsDimension="rate"/>
        <SpeedActionTarget><AbsoluteTargetSpeed value="20"/></SpeedActionTarget>
      </SpeedAction></LongitudinalAction></PrivateAction>
    </Private>"""
    findings = kinematic_findings(parse_string(_scenario(body, env=_FRICTION_ENV)), None)
    assert "DYN-003" in _ids(findings)  # mu <= 0.3*0.9*4/3 = 0.36 -> ~4.8 m/s^2


# -- DYN-004/005/006/007 trajectories ---------------------------------------


def test_dyn004_time_reversal() -> None:
    xml = _scenario(_trajectory("ego", [(0, 0, 0), (2, 20, 0), (1, 30, 0)]))
    findings = kinematic_findings(parse_string(xml), None)
    assert "DYN-004" in _ids(findings)


def test_dyn005_teleport_segment() -> None:
    xml = _scenario(_trajectory("ego", [(0, 0, 0), (1, 500, 0), (2, 520, 0)]))
    findings = kinematic_findings(parse_string(xml), None)
    assert "DYN-005" in _ids(findings)


def test_dyn005_pedestrian_ceiling() -> None:
    xml = _scenario(_trajectory("walker", [(0, 0, 0), (1, 20, 0), (2, 40, 0)]))
    findings = kinematic_findings(parse_string(xml), None)
    assert "DYN-005" in _ids(findings)  # 20 m/s "walk"


def test_dyn006_friction_circle_sustained() -> None:
    xml = _scenario(
        _trajectory("ego", [(0, 0, 0), (1, 50, 0), (2, 75, 0), (3, 75, 0)])
    )
    findings = kinematic_findings(parse_string(xml), None)
    assert "DYN-006" in _ids(findings)  # 25 m/s^2 braking over two samples


def test_dyn006_single_spike_tolerated() -> None:
    xml = _scenario(
        _trajectory("ego", [(0, 0, 0), (1, 30, 0), (2, 40, 0), (3, 48, 0), (4, 56, 0)])
    )
    findings = kinematic_findings(parse_string(xml), None)
    assert "DYN-006" not in _ids(findings)  # one -20 m/s^2 vertex: noise, not physics


def test_dyn006_clean_constant_speed() -> None:
    points = [(float(t), 20.0 * t, 0.0) for t in range(8)]
    xml = _scenario(_trajectory("ego", points))
    assert "DYN-006" not in _ids(kinematic_findings(parse_string(xml), None))


def test_dyn006_immune_to_position_quantisation() -> None:
    # Regression (benchmark corner_case_ndd): 25 Hz sampling with positions on
    # a 0.1 m grid makes adjacent-sample speeds alternate 37.5/40.0 m/s —
    # +-62 m/s^2 of phantom acceleration. Windowed estimation must stay quiet.
    points = [
        (round(0.04 * i, 2), round(37.5 * 0.04 * i, 1), 0.0) for i in range(120)
    ]
    xml = _scenario(_trajectory("ego", points))
    assert "DYN-006" not in _ids(kinematic_findings(parse_string(xml), None))


def test_dyn006_catches_sustained_braking_in_dense_data() -> None:
    # Continuous profile at 25 Hz: cruise 40 m/s for 1 s, then brake at
    # 25 m/s^2 to a stop — impossible on any surface, and it must survive
    # the windowed estimator.
    points = []
    for i in range(90):
        t = 0.04 * i
        if t <= 1.0:
            x = 40.0 * t
        elif t <= 2.6:
            b = t - 1.0
            x = 40.0 + 40.0 * b - 12.5 * b * b
        else:
            x = 72.0
        points.append((round(t, 2), round(x, 3), 0.0))
    xml = _scenario(_trajectory("ego", points))
    assert "DYN-006" in _ids(kinematic_findings(parse_string(xml), None))


def test_dyn007_sustained_pedestrian_sprint() -> None:
    points = [(5.0 * i, 40.0 * i, 0.0) for i in range(9)]  # 8 m/s for 40 s
    xml = _scenario(_trajectory("walker", points))
    findings = kinematic_findings(parse_string(xml), None)
    assert "DYN-007" in _ids(findings)


def test_teleport_is_a_data_break_not_phantom_acceleration() -> None:
    # Regression (benchmark corner_case_ndd): a placeholder first frame jumps
    # 11 m in 40 ms to the real track start; the jump must be reported ONCE
    # (DYN-005) and not leak into windowed acceleration around it (DYN-006).
    points = [(0.0, 0.0, 0.0), (0.04, 150.0, 0.0)] + [
        (round(0.04 * (i + 1), 2), round(150.0 + 15.0 * 0.04 * i, 3), 0.0)
        for i in range(1, 60)
    ]
    xml = _scenario(_trajectory("ego", points))
    ids = _ids(kinematic_findings(parse_string(xml), None))
    assert "DYN-005" in ids
    assert "DYN-006" not in ids


def test_dyn007_clean_walking() -> None:
    points = [(5.0 * i, 7.0 * i, 0.0) for i in range(9)]  # 1.4 m/s
    xml = _scenario(_trajectory("walker", points))
    assert "DYN-007" not in _ids(kinematic_findings(parse_string(xml), None))


# -- engine integration -----------------------------------------------------


def test_layer_gating(curve_map: XodrMap) -> None:
    xml = _scenario(_teleport("ego") + _speed("ego", 40.0))
    scenario = parse_string(xml)
    with_l3 = lint_scenario(scenario, [], {"L3"}, xodr_map=curve_map)
    assert "DYN-001" in {f.rule_id for f in with_l3.findings}
    without = lint_scenario(scenario, [], {"L0", "L1"}, xodr_map=curve_map)
    assert not {f.rule_id for f in without.findings} & set(PLUGIN_RULES)


def test_rule_metadata_registered() -> None:
    from physcheck.engine.plugins import PLUGIN_RULES as ALL_RULES

    for rule_id, (layer, severity, _title, citation) in PLUGIN_RULES.items():
        assert rule_id in ALL_RULES
        assert layer == "L3"
        assert severity in ("error", "warning", "info")
        assert citation
