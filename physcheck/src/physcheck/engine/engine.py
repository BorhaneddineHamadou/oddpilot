"""Rule evaluation over Scenario IR attribute views."""

from __future__ import annotations

import string
from dataclasses import dataclass, field

from physcheck.engine.catalog import RuleSpec
from physcheck.engine.plugins.l0_structure import structural_findings
from physcheck.engine.plugins.l1_cross import cross_findings
from physcheck.engine.plugins.l2_map import map_findings
from physcheck.engine.plugins.l2_solar_geo import solar_geo_findings
from physcheck.engine.predicate import MissingAttribute, PredicateError
from physcheck.ir.attributes import Attrs, entity_contexts, scenario_contexts
from physcheck.ir.model import Scenario
from physcheck.xodr.model import XodrMap

__all__ = ["SEVERITY_ORDER", "Finding", "LintResult", "lint_scenario"]

SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


@dataclass
class Finding:
    rule_id: str
    severity: str
    layer: str
    title: str
    message: str
    file: str
    context: str
    values: dict[str, object] = field(default_factory=dict)
    citation: str = ""


@dataclass
class LintResult:
    file: str
    findings: list[Finding] = field(default_factory=list)
    document_kind: str = "scenario"
    rules_evaluated: int = 0
    rules_skipped: int = 0  # predicate not evaluable (missing attrs / type error)


class _SafeDict(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format_message(template: str, attrs: Attrs) -> str:
    # Templates use {dotted.attr.name}; str.format cannot handle dots, so
    # substitute via string.Formatter with the full field name as the key.
    out: list[str] = []
    for literal, name, _spec, _conv in string.Formatter().parse(template):
        out.append(literal)
        if name is not None:
            value = attrs.get(name, "{" + name + "}")
            out.append(str(value))
    return "".join(out)


def lint_scenario(
    scenario: Scenario,
    rules: list[RuleSpec],
    layers: set[str],
    xodr_map: XodrMap | None = None,
) -> LintResult:
    result = LintResult(file=scenario.source_path, document_kind=scenario.document_kind)
    if "L0" in layers:
        result.findings.extend(structural_findings(scenario))
    if scenario.document_kind != "scenario":
        return result
    if "L1" in layers:
        result.findings.extend(cross_findings(scenario))
    if "L2" in layers and xodr_map is not None:
        result.findings.extend(map_findings(scenario, xodr_map))
        result.findings.extend(solar_geo_findings(scenario, xodr_map))

    active = [r for r in rules if r.layer in layers]
    contexts_by_scope = {
        "scenario": scenario_contexts(scenario),
        "entity": entity_contexts(scenario),
    }
    for rule in active:
        for label, attrs in contexts_by_scope[rule.scope]:
            result.rules_evaluated += 1
            if rule.when_predicate is not None:
                try:
                    if not rule.when_predicate.evaluate(attrs):
                        continue
                except MissingAttribute:
                    continue
                except PredicateError:
                    result.rules_skipped += 1
                    continue
            try:
                ok = rule.assert_predicate.evaluate(attrs) if rule.assert_predicate else True
            except (MissingAttribute, PredicateError):
                result.rules_skipped += 1
                continue
            if not ok:
                names = set(rule.units)
                if rule.assert_predicate is not None:
                    names |= rule.assert_predicate.names
                values = {n: attrs[n] for n in sorted(names) if n in attrs}
                result.findings.append(
                    Finding(
                        rule_id=rule.id,
                        severity=rule.severity,
                        layer=rule.layer,
                        title=rule.title,
                        message=_format_message(rule.message, attrs),
                        file=scenario.source_path,
                        context=label,
                        values=values,
                        citation=rule.citation_str,
                    )
                )
    result.findings.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.rule_id, f.context))
    return result
