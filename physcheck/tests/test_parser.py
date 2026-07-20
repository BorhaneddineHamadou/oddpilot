from __future__ import annotations

from physcheck.ir.attributes import entity_contexts, scenario_contexts
from physcheck.ir.osc_parser import parse_string

MINIMAL = """<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="2026-01-01T00:00:00" description="t" author="a"/>
  <ParameterDeclarations>
    <ParameterDeclaration name="Speed" parameterType="double" value="27.5"/>
    <ParameterDeclaration name="Fog" parameterType="double" value="$Speed"/>
  </ParameterDeclarations>
  <Entities>
    <ScenarioObject name="ego">
      <Vehicle name="car" vehicleCategory="car" mass="1500">
        <BoundingBox><Center x="0" y="0" z="0"/>
          <Dimensions length="4.5" width="1.8" height="1.5"/></BoundingBox>
        <Performance maxSpeed="60" maxAcceleration="5" maxDeceleration="9"/>
      </Vehicle>
    </ScenarioObject>
  </Entities>
  <Storyboard>
    <Init><Actions>
      <GlobalAction><EnvironmentAction><Environment name="e">
        <TimeOfDay animation="false" dateTime="2026-06-21T14:30:00"/>
        <Weather cloudState="free" temperature="288.15">
          <Sun azimuth="3.14" elevation="0.9" illuminance="90000"/>
          <Fog visualRange="$Fog"/>
          <Precipitation precipitationType="dry" precipitationIntensity="0"/>
        </Weather>
        <RoadCondition frictionScaleFactor="1.0" wetness="dry"/>
      </Environment></EnvironmentAction></GlobalAction>
      <Private entityRef="ego">
        <PrivateAction><LongitudinalAction><SpeedAction>
          <SpeedActionDynamics dynamicsShape="step" value="0" dynamicsDimension="time"/>
          <SpeedActionTarget><AbsoluteTargetSpeed value="${$Speed + 2.5}"/></SpeedActionTarget>
        </SpeedAction></LongitudinalAction></PrivateAction>
      </Private>
    </Actions></Init>
  </Storyboard>
</OpenSCENARIO>
"""


def test_parse_minimal() -> None:
    sc = parse_string(MINIMAL)
    assert sc.osc_version == "1.2"
    assert not sc.parse_issues
    assert len(sc.entities) == 1
    ego = sc.entities[0]
    assert ego.category == "car"
    assert ego.mass_kg == 1500
    assert ego.performance is not None and ego.performance.max_deceleration_mps2 == 9
    assert ego.initial_speed_mps == 30.0  # ${$Speed + 2.5}
    assert len(sc.environments) == 1
    env = sc.environments[0]
    assert env.weather is not None
    assert env.weather.fog is not None and env.weather.fog.visual_range_m == 27.5  # $Fog -> $Speed
    assert env.road_condition is not None and env.road_condition.wetness == "dry"


def test_attribute_view() -> None:
    sc = parse_string(MINIMAL)
    (label, attrs) = scenario_contexts(sc)[0]
    assert label == "Init"
    assert attrs["env.temperature_c"] == 15.0
    assert attrs["env.fog.present"] is True
    assert attrs["scenario.max_speed_mps"] == 30.0
    (_elabel, eattrs) = entity_contexts(sc)[0]
    assert eattrs["entity.max_target_speed_mps"] == 30.0
    assert eattrs["env.road.friction_scale"] == 1.0  # entity ctx sees init env


def test_broken_xml_yields_issue_not_exception() -> None:
    sc = parse_string("<OpenSCENARIO><oops")
    assert any(i.code == "xml-error" for i in sc.parse_issues)


def test_wrong_root() -> None:
    sc = parse_string("<NotAScenario/>")
    assert any(i.code == "xml-error" for i in sc.parse_issues)


def test_undeclared_parameter_reported() -> None:
    text = MINIMAL.replace('value="$Speed"', 'value="$Missing"')
    sc = parse_string(text)
    assert any(i.code == "unresolved-parameter" for i in sc.parse_issues)


def test_parameter_value_distribution_detected() -> None:
    doc = (
        '<OpenSCENARIO><FileHeader revMajor="1" revMinor="3" date="d" description="x" author="a"/>'
        "<ParameterValueDistribution/></OpenSCENARIO>"
    )
    sc = parse_string(doc)
    assert sc.document_kind == "parameter_value_distribution"


def test_catalog_reference_resolution() -> None:
    from pathlib import Path

    from physcheck.ir.osc_parser import parse_file

    path = Path(__file__).resolve().parent / "fixtures" / "catalogs" / "scenario_with_catalog.xosc"
    sc = parse_file(path)
    assert not [i for i in sc.parse_issues if i.code == "unresolved-catalog"]
    ego = sc.entities[0]
    assert ego.kind == "vehicle" and ego.from_catalog
    assert ego.category == "car"
    assert ego.mass_kg == 1600  # entry default parameter
    assert ego.performance is not None
    assert ego.performance.max_acceleration_mps2 == 20  # ParameterAssignment override
    assert ego.bounding_box is not None and ego.bounding_box.length_m == 4.6


def test_catalog_resolved_entity_gets_linted() -> None:
    from pathlib import Path

    from physcheck.engine.catalog import load_default_packs
    from physcheck.engine.engine import lint_scenario
    from physcheck.ir.osc_parser import parse_file

    rules, errors = load_default_packs()
    assert not errors
    path = Path(__file__).resolve().parent / "fixtures" / "catalogs" / "scenario_with_catalog.xosc"
    result = lint_scenario(parse_file(path), rules, {"L0", "L1"})
    fired = {f.rule_id for f in result.findings}
    assert "KIN-018" in fired  # maxAcceleration=20 from the assignment override


def test_case_variant_root_still_parses() -> None:
    # SCTrans-style <OpenScenario> root: flagged as SCH-001 but fully parsed.
    from physcheck.ir.osc_parser import parse_string

    xml = """<?xml version="1.0"?>
<OpenScenario>
  <FileHeader revMajor="1" revMinor="0" date="2024-01-01T00:00:00" description="d" author="a"/>
  <Entities>
    <ScenarioObject name="ego"><Vehicle name="m" vehicleCategory="car">
      <BoundingBox><Center x="0" y="0" z="0"/>
      <Dimensions length="4.6" width="1.86" height="1.5"/></BoundingBox>
    </Vehicle></ScenarioObject>
  </Entities>
  <Storyboard><Init><Actions/></Init></Storyboard>
</OpenScenario>
"""
    sc = parse_string(xml)
    assert any(i.code == "xml-error" for i in sc.parse_issues)
    assert len(sc.entities) == 1  # parsing continued past the bad root
