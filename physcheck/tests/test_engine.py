from __future__ import annotations

from physcheck.engine.catalog import RuleSpec, validate_pack_data
from physcheck.engine.engine import lint_scenario
from physcheck.ir.osc_parser import parse_string


def _rule(when: str | None, assert_expr: str, scope: str = "scenario") -> RuleSpec:
    spec = RuleSpec(
        id="T-001",
        layer="L1",
        severity="error",
        title="test rule",
        scope=scope,
        assert_expr=assert_expr,
        message="value is {env.fog.visual_range_m}",
        pack="test",
        when=when,
        citation={"source": "s", "year": 2020, "doi_or_url": "u"},
    )
    spec.compile()
    return spec


_DOC = """<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="d" description="x" author="a"/>
  <Entities>
    <ScenarioObject name="ego"><Vehicle name="v" vehicleCategory="car"/></ScenarioObject>
  </Entities>
  <Storyboard><Init><Actions>
    <GlobalAction><EnvironmentAction><Environment name="e">
      <Weather><Fog visualRange="{fog}"/></Weather>
    </Environment></EnvironmentAction></GlobalAction>
  </Actions></Init></Storyboard>
</OpenSCENARIO>
"""


def test_finding_fires_and_message_templated() -> None:
    sc = parse_string(_DOC.format(fog=5000))
    rule = _rule("env.fog.present", "env.fog.visual_range_m < 1000")
    result = lint_scenario(sc, [rule], {"L0", "L1"})
    findings = [f for f in result.findings if f.rule_id == "T-001"]
    assert len(findings) == 1
    assert findings[0].message == "value is 5000.0"
    assert findings[0].values["env.fog.visual_range_m"] == 5000.0


def test_guard_false_skips() -> None:
    sc = parse_string(_DOC.format(fog=500))
    rule = _rule("env.fog.visual_range_m > 1000", "1 < 0")
    result = lint_scenario(sc, [rule], {"L1"})
    assert not [f for f in result.findings if f.rule_id == "T-001"]


def test_missing_attribute_in_guard_skips_silently() -> None:
    sc = parse_string(_DOC.format(fog=500))
    rule = _rule("env.road.wetness == 'dry'", "1 < 0")
    result = lint_scenario(sc, [rule], {"L1"})
    assert not [f for f in result.findings if f.rule_id == "T-001"]
    assert result.rules_skipped == 0  # guard-missing is "not applicable", not "skipped"


def test_missing_attribute_in_assert_counts_skipped() -> None:
    sc = parse_string(_DOC.format(fog=500))
    rule = _rule(None, "env.road.friction_scale < 2")
    result = lint_scenario(sc, [rule], {"L1"})
    assert result.rules_skipped >= 1


def test_layer_filter() -> None:
    sc = parse_string(_DOC.format(fog=5000))
    rule = _rule("env.fog.present", "env.fog.visual_range_m < 1000")
    result = lint_scenario(sc, [rule], {"L0"})
    assert not [f for f in result.findings if f.rule_id == "T-001"]


def test_structural_dangling_ref() -> None:
    doc = _DOC.format(fog=500).replace(
        "</Actions></Init></Storyboard>",
        '<Private entityRef="ghost"><PrivateAction><LongitudinalAction><SpeedAction>'
        '<SpeedActionDynamics dynamicsShape="step" value="0" dynamicsDimension="time"/>'
        '<SpeedActionTarget><AbsoluteTargetSpeed value="1"/></SpeedActionTarget>'
        "</SpeedAction></LongitudinalAction></PrivateAction></Private>"
        "</Actions></Init></Storyboard>",
    )
    sc = parse_string(doc)
    result = lint_scenario(sc, [], {"L0"})
    assert any(f.rule_id == "SCH-004" for f in result.findings)


def test_multiple_environments_multiple_contexts() -> None:
    from physcheck.ir.attributes import scenario_contexts

    doc = _DOC.format(fog=500).replace(
        "</Actions></Init></Storyboard>",
        "</Actions></Init>"
        '<Story name="s"><Act name="a"><ManeuverGroup maximumExecutionCount="1" name="mg">'
        '<Actors selectTriggeringEntities="false"/>'
        '<Maneuver name="m"><Event name="e" priority="overwrite"><Action name="x">'
        "<GlobalAction><EnvironmentAction><Environment name=\"e2\">"
        '<Weather><Fog visualRange="9000"/></Weather>'
        "</Environment></EnvironmentAction></GlobalAction>"
        "</Action></Event></Maneuver></ManeuverGroup></Act></Story></Storyboard>",
    )
    sc = parse_string(doc)
    assert len(scenario_contexts(sc)) == 2


def test_shipped_catalog_no_false_positives_on_valid(all_rules: list[RuleSpec]) -> None:
    from pathlib import Path

    fixtures = Path(__file__).resolve().parent / "fixtures" / "valid"
    for path in sorted(fixtures.glob("*.xosc")):
        from physcheck.ir.osc_parser import parse_file

        sc = parse_file(path)
        result = lint_scenario(sc, all_rules, {"L0", "L1"})
        assert result.findings == [], (path.name, [f.rule_id for f in result.findings])


def test_validate_pack_roundtrip_with_engine() -> None:
    doc = {
        "pack": "custom",
        "version": "0.0.1",
        "rules": [
            {
                "id": "CUST-001",
                "layer": "L1",
                "severity": "warning",
                "scope": "scenario",
                "title": "custom",
                "when": "env.fog.present",
                "assert": "env.fog.visual_range_m > 100",
                "message": "too dense",
                "citation": {"source": "s", "year": 1, "doi_or_url": "u"},
            }
        ],
    }
    rules, errors = validate_pack_data(doc)
    assert not errors
    sc = parse_string(_DOC.format(fog=50))
    result = lint_scenario(sc, rules, {"L1"})
    assert any(f.rule_id == "CUST-001" for f in result.findings)
