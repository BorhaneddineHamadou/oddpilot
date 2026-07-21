"""L4 tier: storyboard control-structure static analysis."""

from __future__ import annotations

from physcheck.engine.engine import lint_scenario
from physcheck.engine.plugins.l4_storyboard import storyboard_findings
from physcheck.ir.osc_parser import parse_string


def _scenario(
    story: str = "",
    stop_trigger: str = """<StopTrigger><ConditionGroup>
      <Condition name="end" delay="0" conditionEdge="rising">
        <ByValueCondition><SimulationTimeCondition value="60"
          rule="greaterThan"/></ByValueCondition>
      </Condition></ConditionGroup></StopTrigger>""",
    parameters: str = "",
) -> str:
    return f"""<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="2026-07-21T12:00:00"
              description="l4 test" author="physcheck"/>
  {parameters}
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
    <Init><Actions/></Init>
    {story}
    {stop_trigger}
  </Storyboard>
</OpenSCENARIO>"""


def _act(name: str = "a", start: float | None = 5, stop: float | None = None,
         groups: str = "") -> str:
    def trig(tag: str, t: float | None) -> str:
        if t is None:
            return f"<{tag}/>"
        return f"""<{tag}><ConditionGroup>
          <Condition name="c" delay="0" conditionEdge="rising">
            <ByValueCondition><SimulationTimeCondition value="{t}"
              rule="greaterThan"/></ByValueCondition>
          </Condition></ConditionGroup></{tag}>"""

    return f"""<Story name="s"><Act name="{name}">
      {groups}
      {trig("StartTrigger", start)}
      {trig("StopTrigger", stop)}
    </Act></Story>"""


def _group(events: str, actors: str = '<EntityRef entityRef="ego"/>',
           count: str = "1", select: str = "false") -> str:
    return f"""<ManeuverGroup name="mg" maximumExecutionCount="{count}">
      <Actors selectTriggeringEntities="{select}">{actors}</Actors>
      <Maneuver name="m">{events}</Maneuver>
    </ManeuverGroup>"""


def _event(actions: str, name: str = "e", start: float | None = None,
           count: str | None = None) -> str:
    trigger = ""
    if start is not None:
        trigger = f"""<StartTrigger><ConditionGroup>
          <Condition name="c" delay="0" conditionEdge="rising">
            <ByValueCondition><SimulationTimeCondition value="{start}"
              rule="greaterThan"/></ByValueCondition>
          </Condition></ConditionGroup></StartTrigger>"""
    count_attr = f' maximumExecutionCount="{count}"' if count is not None else ""
    return f'<Event name="{name}" priority="overwrite"{count_attr}>{actions}{trigger}</Event>'


_SPEED = """<Action name="speed"><PrivateAction><LongitudinalAction><SpeedAction>
  <SpeedActionDynamics dynamicsShape="step" value="0" dynamicsDimension="time"/>
  <SpeedActionTarget><AbsoluteTargetSpeed value="10"/></SpeedActionTarget>
</SpeedAction></LongitudinalAction></PrivateAction></Action>"""
_SPEED2 = _SPEED.replace('name="speed"', 'name="speed2"')
_LANE = """<Action name="lane"><PrivateAction><LateralAction><LaneChangeAction>
  <LaneChangeActionDynamics dynamicsShape="sinusoidal" value="3" dynamicsDimension="time"/>
  <LaneChangeTarget><RelativeTargetLane entityRef="ego" value="1"/></LaneChangeTarget>
</LaneChangeAction></LateralAction></PrivateAction></Action>"""


def _ids(xml: str) -> list[str]:
    return sorted(f.rule_id for f in storyboard_findings(parse_string(xml)))


def test_clean_storyboard() -> None:
    xml = _scenario(_act(groups=_group(_event(_SPEED + _LANE))))
    assert _ids(xml) == []  # one longitudinal + one lateral: no conflict


def test_stb001_empty_act_interval() -> None:
    xml = _scenario(_act(start=30, stop=10))
    assert "STB-001" in _ids(xml)


def test_stb002_dead_trigger_after_scenario_end() -> None:
    xml = _scenario(_act(groups=_group(_event(_SPEED, start=120))))
    assert "STB-002" in _ids(xml)  # storyboard stops at 60 s
    ok = _scenario(_act(groups=_group(_event(_SPEED, start=30))))
    assert "STB-002" not in _ids(ok)


def test_stb002_dead_act() -> None:
    xml = _scenario(_act(start=90))
    assert "STB-002" in _ids(xml)


def test_stb003_conflicting_longitudinal_actions() -> None:
    xml = _scenario(_act(groups=_group(_event(_SPEED + _SPEED2))))
    assert "STB-003" in _ids(xml)


def test_stb004_zero_execution_count() -> None:
    xml = _scenario(_act(groups=_group(_event(_SPEED, count="0"))))
    assert "STB-004" in _ids(xml)
    xml = _scenario(_act(groups=_group(_event(_SPEED), count="0")))
    assert "STB-004" in _ids(xml)


def test_stb005_no_actors() -> None:
    xml = _scenario(_act(groups=_group(_event(_SPEED), actors="")))
    assert "STB-005" in _ids(xml)
    # selectTriggeringEntities=true is a legitimate actor source
    ok = _scenario(_act(groups=_group(_event(_SPEED), actors="", select="true")))
    assert "STB-005" not in _ids(ok)


def test_stb006_no_stop_trigger() -> None:
    xml = _scenario(_act(groups=_group(_event(_SPEED))), stop_trigger="<StopTrigger/>")
    assert "STB-006" in _ids(xml)


def test_stb007_unit_incompatible_parameter_comparison() -> None:
    params = """<ParameterDeclarations>
      <ParameterDeclaration name="mode" parameterType="string" value="fast"/>
    </ParameterDeclarations>"""
    trigger = """<StartTrigger><ConditionGroup>
      <Condition name="p" delay="0" conditionEdge="rising">
        <ByValueCondition><ParameterCondition parameterRef="mode" value="3"
          rule="greaterThan"/></ByValueCondition>
      </Condition></ConditionGroup></StartTrigger>"""
    event = f'<Event name="e" priority="overwrite">{_SPEED}{trigger}</Event>'
    xml = _scenario(_act(groups=_group(event)), parameters=params)
    assert "STB-007" in _ids(xml)


def test_layer_gating() -> None:
    xml = _scenario(_act(start=90))
    scenario = parse_string(xml)
    with_l4 = lint_scenario(scenario, [], {"L4"})
    assert "STB-002" in {f.rule_id for f in with_l4.findings}
    without = lint_scenario(scenario, [], {"L0", "L1"})
    assert not {f.rule_id for f in without.findings} & {"STB-002"}


def test_pytest_registry() -> None:
    from physcheck.engine.plugins import PLUGIN_RULES

    assert all(f"STB-00{i}" in PLUGIN_RULES for i in range(1, 8))
