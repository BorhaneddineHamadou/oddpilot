"""L5 ODD conformance: scenario attributes against a supplied ODD definition.

Design brief §4 L5: evaluate scenario attributes against the ODD's
include/exclude conditions; verdict per attribute: in / out / undeclared.
Out-of-ODD is an error (the test exercises operation the system is not
declared for), undeclared is a warning (conformance cannot be established).
Interpretation decision D34 in docs/decisions.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physcheck.ir.model import Scenario
from physcheck.odd import OddDefinition, conformance

if TYPE_CHECKING:  # imported late at runtime to avoid a cycle with engine.py
    from physcheck.engine.engine import Finding

__all__ = ["PLUGIN_RULES", "odd_findings"]

#: id -> (layer, severity, title, citation)
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    "ODD-000": (
        "L5", "warning",
        "ODD definition could not be fully parsed",
        "ASAM OpenODD 1.0.0 concept (include/exclude conditions over ODD "
        "attributes); ISO 34503:2023 (ODD taxonomy)",
    ),
    "ODD-001": (
        "L5", "error",
        "Attribute value outside the declared ODD",
        "ASAM OpenODD 1.0.0 concept (include/exclude condition semantics); "
        "ISO 34503:2023 §6 (the ODD bounds the conditions the ADS is "
        "designed to operate in)",
    ),
    "ODD-002": (
        "L5", "warning",
        "ODD constrains an attribute the scenario leaves undeclared",
        "ISO 34503:2023 (conformance to a bounded ODD cannot be established "
        "for unspecified conditions)",
    ),
}


def _mk(rule_id: str, message: str, scenario: Scenario, context: str,
        values: dict[str, object]) -> Finding:
    from physcheck.engine.engine import Finding

    layer, severity, title, citation = PLUGIN_RULES[rule_id]
    return Finding(
        rule_id=rule_id, severity=severity, layer=layer, title=title,
        message=message, file=scenario.source_path, context=context,
        values=values, citation=citation,
    )


def odd_findings(scenario: Scenario, odd: OddDefinition) -> list[Finding]:
    findings: list[Finding] = []
    if odd.issues:
        summary = "; ".join(odd.issues[:5])
        if len(odd.issues) > 5:
            summary += f"; ... ({len(odd.issues) - 5} more)"
        findings.append(
            _mk(
                "ODD-000",
                f"ODD definition '{odd.source_path}' parsed with problems: "
                f"{summary}. L5 runs on the parseable constraints only.",
                scenario, "odd", {"odd.issues": len(odd.issues)},
            )
        )
    for label, attribute, verdict, value in conformance(scenario, odd):
        if verdict == "out":
            findings.append(
                _mk(
                    "ODD-001",
                    f"'{attribute}' = {value!r} lies outside ODD "
                    f"'{odd.name}': the scenario exercises operation the "
                    "system is not declared for.",
                    scenario, label,
                    {attribute: value, "odd.name": odd.name},
                )
            )
        elif verdict == "undeclared":
            findings.append(
                _mk(
                    "ODD-002",
                    f"ODD '{odd.name}' constrains '{attribute}' but the "
                    "scenario does not declare it — conformance cannot be "
                    "established.",
                    scenario, label,
                    {"odd.attribute": attribute, "odd.name": odd.name},
                )
            )
    return findings
