"""Property-based tests (hypothesis)."""

from __future__ import annotations

import contextlib

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from physcheck.engine.catalog import RuleSpec  # noqa: E402
from physcheck.engine.engine import lint_scenario  # noqa: E402
from physcheck.engine.predicate import MissingAttribute, Predicate, PredicateError  # noqa: E402
from physcheck.ir.osc_parser import parse_string  # noqa: E402

_finite = st.floats(allow_nan=False, allow_infinity=False, width=32)


@given(x=_finite, y=_finite)
def test_comparison_predicates_total(x: float, y: float) -> None:
    p = Predicate("env.x < env.y")
    assert p.evaluate({"env.x": x, "env.y": y}) == (x < y)


@given(f=st.floats(min_value=0.001, max_value=1e6, allow_nan=False))
def test_atm003_style_power_never_crashes(f: float) -> None:
    p = Predicate("env.v <= 40000 * env.r ** -0.55")
    result = p.evaluate({"env.v": 100.0, "env.r": f})
    assert isinstance(result, bool)


@given(value=st.one_of(st.floats(allow_nan=False), st.text(max_size=10), st.booleans()))
def test_mixed_type_comparison_never_leaks_raw_exception(value: object) -> None:
    p = Predicate("env.x > 1")
    with contextlib.suppress(PredicateError, MissingAttribute):
        p.evaluate({"env.x": value})  # only these exceptions are allowed outcomes


@given(junk=st.text(max_size=200))
@settings(max_examples=60)
def test_parser_never_raises_on_junk(junk: str) -> None:
    scenario = parse_string(junk)
    assert scenario.source_path == "<string>"


@given(
    fog=st.floats(min_value=-1e5, max_value=1e6, allow_nan=False),
    friction=st.floats(min_value=-2, max_value=5, allow_nan=False),
    temp=st.floats(min_value=100, max_value=400, allow_nan=False),
)
@settings(max_examples=40, deadline=None)
def test_engine_total_over_environment_space(
    all_rules: list[RuleSpec], fog: float, friction: float, temp: float
) -> None:
    doc = f"""<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="d" description="x" author="a"/>
  <Entities>
    <ScenarioObject name="ego"><Vehicle name="v" vehicleCategory="car"/></ScenarioObject>
  </Entities>
  <Storyboard><Init><Actions>
    <GlobalAction><EnvironmentAction><Environment name="e">
      <Weather temperature="{temp}"><Fog visualRange="{fog}"/></Weather>
      <RoadCondition frictionScaleFactor="{friction}"/>
    </Environment></EnvironmentAction></GlobalAction>
  </Actions></Init></Storyboard>
</OpenSCENARIO>
"""
    scenario = parse_string(doc)
    result = lint_scenario(scenario, all_rules, {"L0", "L1"})
    for finding in result.findings:
        assert finding.severity in {"error", "warning", "info"}
