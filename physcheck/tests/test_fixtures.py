"""Every catalog rule is covered by a violating fixture; valid fixtures are clean."""

from __future__ import annotations

from pathlib import Path

import pytest

from physcheck.engine.catalog import RuleSpec
from physcheck.engine.engine import lint_scenario
from physcheck.engine.plugins.l0_structure import PLUGIN_RULES
from physcheck.ir.osc_parser import parse_file

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_VIOLATING = sorted((FIXTURES / "violating").glob("*.xosc"))


def test_every_rule_has_a_violating_fixture(all_rules: list[RuleSpec]) -> None:
    fixture_ids = {p.stem for p in _VIOLATING}
    rule_ids = {r.id for r in all_rules} | set(PLUGIN_RULES)
    missing = rule_ids - fixture_ids
    assert not missing, f"rules without violating fixture: {sorted(missing)}"


@pytest.mark.parametrize("path", _VIOLATING, ids=lambda p: p.stem)
def test_violating_fixture_triggers_its_rule(path: Path, all_rules: list[RuleSpec]) -> None:
    scenario = parse_file(path)
    result = lint_scenario(scenario, all_rules, {"L0", "L1"})
    fired = {f.rule_id for f in result.findings}
    assert path.stem in fired, f"{path.stem} expected in findings, got {sorted(fired)}"


@pytest.mark.parametrize(
    "path", sorted((FIXTURES / "valid").glob("*.xosc")), ids=lambda p: p.stem
)
def test_valid_fixture_is_clean(path: Path, all_rules: list[RuleSpec]) -> None:
    scenario = parse_file(path)
    result = lint_scenario(scenario, all_rules, {"L0", "L1"})
    assert result.findings == [], [(f.rule_id, f.message) for f in result.findings]
