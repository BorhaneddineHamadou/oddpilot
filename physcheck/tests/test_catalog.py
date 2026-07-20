from __future__ import annotations

import yaml

from physcheck.engine.catalog import RuleSpec, default_pack_paths, validate_pack_data


def test_shipped_packs_exist() -> None:
    names = {p.name for p in default_pack_paths()}
    assert {
        "atmosphere.yaml",
        "entities.yaml",
        "friction_road.yaml",
        "kinematics.yaml",
        "precipitation.yaml",
        "schema_ranges.yaml",
        "solar.yaml",
    } <= names


def test_rule_ids_globally_unique(all_rules: list[RuleSpec]) -> None:
    ids = [r.id for r in all_rules]
    assert len(ids) == len(set(ids))


def test_every_rule_cited(all_rules: list[RuleSpec]) -> None:
    for rule in all_rules:
        assert rule.citation.get("source"), rule.id
        assert rule.citation.get("doi_or_url"), rule.id


def test_predicates_reference_known_attribute_roots(all_rules: list[RuleSpec]) -> None:
    for rule in all_rules:
        names = set(rule.assert_predicate.names if rule.assert_predicate else set())
        if rule.when_predicate is not None:
            names |= rule.when_predicate.names
        for name in names:
            root = name.split(".", 1)[0]
            assert root in {"env", "entity", "scenario", "osc", "file"}, (rule.id, name)
        if rule.scope == "scenario":
            assert not any(n.startswith("entity.") for n in names), rule.id


def test_validate_rejects_uncited_rule() -> None:
    doc = yaml.safe_load(
        """
pack: p
version: "0.0.1"
rules:
  - id: X-001
    layer: L1
    severity: error
    scope: scenario
    title: t
    assert: "1 < 2"
    message: m
"""
    )
    rules, errors = validate_pack_data(doc)
    assert not rules
    assert any("cited" in e for e in errors)


def test_validate_rejects_bad_predicate() -> None:
    doc = yaml.safe_load(
        """
pack: p
version: "0.0.1"
rules:
  - id: X-002
    layer: L1
    severity: warning
    scope: scenario
    title: t
    assert: "__import__('os')"
    message: m
    citation: {source: s, year: 2020, doi_or_url: u}
"""
    )
    rules, errors = validate_pack_data(doc)
    assert not rules and errors


def test_validate_rejects_duplicate_ids() -> None:
    doc = yaml.safe_load(
        """
pack: p
version: "0.0.1"
rules:
  - {id: X-003, layer: L1, severity: info, scope: scenario, title: t,
     assert: "1 < 2", message: m, citation: {source: s, doi_or_url: u}}
  - {id: X-003, layer: L1, severity: info, scope: scenario, title: t,
     assert: "1 < 2", message: m, citation: {source: s, doi_or_url: u}}
"""
    )
    _, errors = validate_pack_data(doc)
    assert any("duplicate" in e for e in errors)
