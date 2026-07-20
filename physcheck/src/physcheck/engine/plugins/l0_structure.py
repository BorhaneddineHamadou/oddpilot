"""L0 structural checks implemented as a Python plugin.

These need the document/IR structure rather than the flat attribute view:
XML well-formedness, header presence, supported version, dangling entity
references, unresolved parameters/catalogs, unparseable literals.

Rule ids SCH-001..SCH-020 (YAML range/enum rules are SCH-101+ in
catalog/schema_ranges.yaml).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physcheck.ir.model import Scenario

if TYPE_CHECKING:  # imported late at runtime to avoid a cycle with engine.py
    from physcheck.engine.engine import Finding

__all__ = ["PLUGIN_RULES", "structural_findings"]

#: id -> (layer, severity, title, citation)
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    "SCH-001": (
        "L0",
        "error",
        "File is not a well-formed OpenSCENARIO document",
        "ASAM OpenSCENARIO 1.x specification (XML schema)",
    ),
    "SCH-002": (
        "L0",
        "error",
        "FileHeader missing or incomplete",
        "ASAM OpenSCENARIO 1.x Model Documentation, class FileHeader",
    ),
    "SCH-003": (
        "L0",
        "error",
        "Unsupported OpenSCENARIO major revision",
        "ASAM OpenSCENARIO 1.x Model Documentation, class FileHeader (revMajor)",
    ),
    "SCH-004": (
        "L0",
        "error",
        "Dangling entityRef",
        "ASAM OpenSCENARIO 1.x Model Documentation, EntityRef semantics",
    ),
    "SCH-005": (
        "L0",
        "error",
        "Unresolved parameter or expression",
        "ASAM OpenSCENARIO 1.x Model Documentation, ParameterDeclarations",
    ),
    "SCH-006": (
        "L0",
        "error",
        "Value not parseable as its declared type",
        "ASAM OpenSCENARIO 1.x specification (XML schema types)",
    ),
    "SCH-007": (
        "L0",
        "info",
        "CatalogReference could not be resolved",
        "ASAM OpenSCENARIO 1.x Model Documentation, Catalogs",
    ),
    "SCH-008": (
        "L0",
        "error",
        "TimeOfDay dateTime not ISO 8601",
        "ASAM OpenSCENARIO 1.x Model Documentation, class TimeOfDay (xsd:dateTime)",
    ),
}

_ISSUE_TO_RULE = {
    "xml-error": "SCH-001",
    "io-error": "SCH-001",
    "missing-header": "SCH-002",
    "unresolved-parameter": "SCH-005",
    "unresolved-expression": "SCH-005",
    "bad-number": "SCH-006",
    "bad-enum": "SCH-006",
    "unresolved-catalog": "SCH-007",
    "bad-datetime": "SCH-008",
    "unknown-entity": "SCH-006",
}


def structural_findings(scenario: Scenario) -> list[Finding]:
    from physcheck.engine.engine import Finding

    findings: list[Finding] = []

    def add(rule_id: str, message: str, context: str = "") -> None:
        _layer, severity, title, citation = PLUGIN_RULES[rule_id]
        findings.append(
            Finding(
                rule_id=rule_id,
                severity=severity,
                layer="L0",
                title=title,
                message=message,
                file=scenario.source_path,
                context=context or "document",
                citation=citation,
            )
        )

    for issue in scenario.parse_issues:
        rule_id = _ISSUE_TO_RULE.get(issue.code, "SCH-006")
        add(rule_id, issue.message, issue.context)

    if scenario.document_kind != "scenario":
        return findings

    header = scenario.header
    if header.rev_major is not None and header.rev_major != 1:
        add(
            "SCH-003",
            f"revMajor={header.rev_major}: physcheck v0.1 supports OpenSCENARIO 1.x only",
        )

    declared = {e.name for e in scenario.entities}
    for ref in sorted(set(scenario.entity_refs)):
        if ref and ref not in declared:
            add("SCH-004", f"entityRef '{ref}' does not match any declared entity")
    return findings
