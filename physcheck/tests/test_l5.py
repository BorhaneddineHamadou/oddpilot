"""L5 tier: ODD definition parsing and conformance verdicts."""

from __future__ import annotations

from pathlib import Path

import pytest

from physcheck.cli import main
from physcheck.engine.engine import lint_scenario
from physcheck.engine.plugins.l5_odd import odd_findings
from physcheck.ir.osc_parser import parse_string
from physcheck.odd import Constraint, load_odd

ODD_YAML = """
odd:
  name: urban-daytime-dry
  attributes:
    env.temperature_k:
      include: {min: 263, max: 313}
      exclude:
        - {min: 268, max: 271}
    env.precip.type:
      include: [dry, rain]
    env.road.wetness:
      exclude: [lowFlooded, highFlooded]
    entity.max_target_speed_mps:
      include: {max: 20}
"""


def _scenario(temp: float = 288, precip: str = "dry", wetness: str = "dry",
              speed: float = 12) -> str:
    return f"""<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="2026-07-21T12:00:00"
              description="l5 test" author="physcheck"/>
  <Entities>
    <ScenarioObject name="ego">
      <Vehicle name="car" vehicleCategory="car" mass="1600">
        <BoundingBox><Center x="0" y="0" z="0"/>
          <Dimensions length="4.6" width="1.86" height="1.5"/></BoundingBox>
        <Performance maxSpeed="62" maxAcceleration="5" maxDeceleration="9"/>
      </Vehicle>
    </ScenarioObject>
  </Entities>
  <Storyboard>
    <Init><Actions>
      <GlobalAction><EnvironmentAction><Environment name="env">
        <Weather temperature="{temp}">
          <Precipitation precipitationType="{precip}"
                         precipitationIntensity="{0.0 if precip == 'dry' else 1.5}"/>
        </Weather>
        <RoadCondition wetness="{wetness}"/>
      </Environment></EnvironmentAction></GlobalAction>
      <Private entityRef="ego">
        <PrivateAction><LongitudinalAction><SpeedAction>
          <SpeedActionDynamics dynamicsShape="step" value="0" dynamicsDimension="time"/>
          <SpeedActionTarget><AbsoluteTargetSpeed value="{speed}"/></SpeedActionTarget>
        </SpeedAction></LongitudinalAction></PrivateAction>
      </Private>
    </Actions></Init>
  </Storyboard>
</OpenSCENARIO>"""


@pytest.fixture()
def odd_file(tmp_path: Path) -> Path:
    path = tmp_path / "odd.yaml"
    path.write_text(ODD_YAML)
    return path


def test_load_odd(odd_file: Path) -> None:
    odd = load_odd(odd_file)
    assert odd.name == "urban-daytime-dry"
    assert not odd.issues
    assert len(odd.constraints) == 4


def test_constraint_verdicts() -> None:
    c = Constraint(
        attribute="env.temperature_k",
        include_ranges=[(263.0, 313.0)],
        exclude_ranges=[(268.0, 271.0)],
    )
    assert c.verdict(288.0) == "in"
    assert c.verdict(250.0) == "out"      # below include range
    assert c.verdict(269.5) == "out"      # inside the carve-out
    assert c.verdict(None) == "undeclared"
    enum = Constraint(attribute="env.precip.type", include_values=["dry", "rain"])
    assert enum.verdict("rain") == "in"
    assert enum.verdict("snow") == "out"


def test_in_odd_scenario_is_clean(odd_file: Path) -> None:
    findings = odd_findings(parse_string(_scenario()), load_odd(odd_file))
    assert findings == []


def test_out_of_odd_attributes(odd_file: Path) -> None:
    xml = _scenario(temp=250, precip="snow", wetness="highFlooded", speed=33)
    findings = odd_findings(parse_string(xml), load_odd(odd_file))
    out = [f for f in findings if f.rule_id == "ODD-001"]
    assert len(out) == 4  # every constrained attribute violates
    assert all(f.severity == "error" for f in out)


def test_undeclared_attribute(odd_file: Path) -> None:
    # No RoadCondition wetness declared -> conformance not establishable.
    xml = _scenario().replace('<RoadCondition wetness="dry"/>', "")
    findings = odd_findings(parse_string(xml), load_odd(odd_file))
    undeclared = [f for f in findings if f.rule_id == "ODD-002"]
    assert len(undeclared) == 1
    assert "env.road.wetness" in undeclared[0].message
    assert undeclared[0].severity == "warning"


def test_bad_odd_definition_reported(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("odd:\n  name: x\n  attributes:\n    env.temperature_k: {}\n")
    odd = load_odd(path)
    assert odd.issues
    findings = odd_findings(parse_string(_scenario()), odd)
    assert [f.rule_id for f in findings] == ["ODD-000"]


def test_layer_gating(odd_file: Path) -> None:
    scenario = parse_string(_scenario(temp=250))
    odd = load_odd(odd_file)
    with_l5 = lint_scenario(scenario, [], {"L5"}, odd=odd)
    assert "ODD-001" in {f.rule_id for f in with_l5.findings}
    without = lint_scenario(scenario, [], {"L0", "L1"}, odd=odd)
    assert "ODD-001" not in {f.rule_id for f in without.findings}


def test_cli_odd_enables_l5(odd_file: Path, tmp_path: Path) -> None:
    bad = tmp_path / "out_of_odd.xosc"
    bad.write_text(_scenario(temp=250))
    assert main(["lint", str(bad), "--odd", str(odd_file), "--fail-on", "error"]) == 1
    good = tmp_path / "in_odd.xosc"
    good.write_text(_scenario())
    assert main(["lint", str(good), "--odd", str(odd_file), "--fail-on", "error"]) == 0
    assert main(["lint", str(good), "--odd", str(tmp_path / "missing.yaml")]) == 3
