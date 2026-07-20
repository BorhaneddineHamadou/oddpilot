"""Finding renderers for the four CLI output formats."""

from __future__ import annotations

import html
import json
from collections.abc import Sequence

from physcheck import __version__
from physcheck.engine.catalog import RuleSpec
from physcheck.engine.engine import Finding, LintResult

__all__ = ["render_report"]

_SARIF_LEVEL = {"error": "error", "warning": "warning", "info": "note"}


def render_report(
    results: Sequence[LintResult],
    fmt: str,
    rules: Sequence[RuleSpec] = (),
) -> str:
    if fmt == "table":
        return _table(results)
    if fmt == "json":
        return _json(results)
    if fmt == "sarif":
        return _sarif(results, rules)
    if fmt == "html":
        return _html(results)
    raise ValueError(f"unknown format {fmt!r}")


def _all_findings(results: Sequence[LintResult]) -> list[Finding]:
    return [f for r in results for f in r.findings]


def _summary_counts(results: Sequence[LintResult]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in _all_findings(results):
        counts[f.severity] += 1
    return counts


def _table(results: Sequence[LintResult]) -> str:
    lines: list[str] = []
    for result in results:
        if not result.findings:
            continue
        lines.append(result.file)
        for f in result.findings:
            lines.append(f"  {f.severity.upper():7s} {f.rule_id:8s} [{f.context}] {f.message}")
        lines.append("")
    counts = _summary_counts(results)
    total_files = len(results)
    lines.append(
        f"{total_files} file(s) checked: {counts['error']} error(s), "
        f"{counts['warning']} warning(s), {counts['info']} info"
    )
    return "\n".join(lines)


def _finding_dict(f: Finding) -> dict[str, object]:
    return {
        "rule_id": f.rule_id,
        "severity": f.severity,
        "layer": f.layer,
        "title": f.title,
        "message": f.message,
        "file": f.file,
        "context": f.context,
        "values": f.values,
        "citation": f.citation,
    }


def _json(results: Sequence[LintResult]) -> str:
    doc = {
        "tool": {"name": "physcheck", "version": __version__},
        "summary": _summary_counts(results),
        "files": [
            {
                "file": r.file,
                "document_kind": r.document_kind,
                "rules_evaluated": r.rules_evaluated,
                "rules_skipped": r.rules_skipped,
                "findings": [_finding_dict(f) for f in r.findings],
            }
            for r in results
        ],
    }
    return json.dumps(doc, indent=2)


def _sarif(results: Sequence[LintResult], rules: Sequence[RuleSpec]) -> str:
    fired = {f.rule_id for f in _all_findings(results)}
    sarif_rules: list[dict[str, object]] = []
    known_ids: set[str] = set()
    for rule in rules:
        if rule.id in fired:
            known_ids.add(rule.id)
            sarif_rules.append(
                {
                    "id": rule.id,
                    "name": rule.title.replace(" ", ""),
                    "shortDescription": {"text": rule.title},
                    "fullDescription": {"text": rule.quantitative_basis or rule.title},
                    "help": {"text": f"Citation: {rule.citation_str}"},
                    "properties": {"layer": rule.layer, "pack": rule.pack},
                }
            )
    for rule_id in sorted(fired - known_ids):  # plugin rules
        first = next(f for f in _all_findings(results) if f.rule_id == rule_id)
        sarif_rules.append(
            {
                "id": rule_id,
                "shortDescription": {"text": first.title},
                "help": {"text": f"Citation: {first.citation}"},
                "properties": {"layer": first.layer, "pack": "builtin"},
            }
        )
    sarif_results = [
        {
            "ruleId": f.rule_id,
            "level": _SARIF_LEVEL[f.severity],
            "message": {"text": f"[{f.context}] {f.message}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": f.file.replace("\\", "/")},
                    }
                }
            ],
        }
        for f in _all_findings(results)
    ]
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "physcheck",
                        "version": __version__,
                        "informationUri": "https://github.com/odd-pilot/odd-pilot",
                        "rules": sarif_rules,
                    }
                },
                "results": sarif_results,
            }
        ],
    }
    return json.dumps(doc, indent=2)


def _html(results: Sequence[LintResult]) -> str:
    counts = _summary_counts(results)
    rows: list[str] = []
    for f in _all_findings(results):
        rows.append(
            "<tr class='{sev}'><td>{sev}</td><td>{rid}</td><td>{file}</td>"
            "<td>{ctx}</td><td>{msg}<div class='cite'>{cite}</div></td></tr>".format(
                sev=html.escape(f.severity),
                rid=html.escape(f.rule_id),
                file=html.escape(f.file),
                ctx=html.escape(f.context),
                msg=html.escape(f.message),
                cite=html.escape(f.citation),
            )
        )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>physcheck report</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2em; }}
 table {{ border-collapse: collapse; width: 100%; }}
 td, th {{ border: 1px solid #ccc; padding: 6px 8px; vertical-align: top;
           font-size: 14px; }}
 tr.error td:first-child {{ color: #b00020; font-weight: 700; }}
 tr.warning td:first-child {{ color: #b26a00; font-weight: 700; }}
 tr.info td:first-child {{ color: #555; }}
 .cite {{ color: #666; font-size: 12px; margin-top: 4px; }}
</style></head>
<body>
<h1>physcheck {html.escape(__version__)} report</h1>
<p>{len(results)} file(s) checked: <b>{counts["error"]} error(s)</b>,
{counts["warning"]} warning(s), {counts["info"]} info.</p>
<table>
<tr><th>Severity</th><th>Rule</th><th>File</th><th>Context</th><th>Message</th></tr>
{chr(10).join(rows)}
</table>
</body></html>
"""
