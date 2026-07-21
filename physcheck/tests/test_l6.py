"""L6 tier: statistical plausibility via an injected scorer (model-free)."""

from __future__ import annotations

from physcheck.engine.engine import lint_scenario
from physcheck.engine.plugins.l6_statistical import statistical_findings
from physcheck.ir.attributes import Attrs
from physcheck.ir.osc_parser import parse_string

_SCENARIO = """<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="2026-07-21T12:00:00"
              description="l6 test" author="physcheck"/>
  <Entities/>
  <Storyboard><Init><Actions>
    <GlobalAction><EnvironmentAction><Environment name="env">
      <Weather temperature="288"/>
    </Environment></EnvironmentAction></GlobalAction>
  </Actions></Init></Storyboard>
</OpenSCENARIO>"""


def _scorer(quantile: float):
    def scorer(_attrs: Attrs) -> tuple[float, float]:
        return (-12.5, quantile)

    return scorer


def test_never_observed_flagged_below_quantile() -> None:
    scenario = parse_string(_SCENARIO)
    findings = statistical_findings(scenario, _scorer(0.002), quantile=0.01)
    assert [f.rule_id for f in findings] == ["STA-001"]
    assert findings[0].severity == "warning"  # never blocks execution
    assert "0.20%" in findings[0].message


def test_common_combination_is_quiet() -> None:
    scenario = parse_string(_SCENARIO)
    assert statistical_findings(scenario, _scorer(0.4), quantile=0.01) == []


def test_unscoreable_context_skipped() -> None:
    scenario = parse_string(_SCENARIO)
    assert statistical_findings(scenario, lambda _a: None, quantile=0.01) == []


def test_layer_gating() -> None:
    scenario = parse_string(_SCENARIO)
    with_l6 = lint_scenario(scenario, [], {"L6"}, scorer=_scorer(0.0))
    assert "STA-001" in {f.rule_id for f in with_l6.findings}
    without = lint_scenario(scenario, [], {"L6"})  # no scorer injected
    assert without.findings == []
