"""Rule-pack loading and validation.

Packs are YAML files with the schema documented in physcheck/README.md.
``validate_pack_data`` powers both pack loading and ``physcheck rules lint``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from physcheck.engine.predicate import Predicate, PredicateError

__all__ = ["RuleSpec", "load_default_packs", "load_pack", "validate_pack_data"]

_SEVERITIES = ("error", "warning", "info")
_LAYERS = tuple(f"L{i}" for i in range(7))
_SCOPES = ("scenario", "entity")


@dataclass
class RuleSpec:
    id: str
    layer: str
    severity: str
    title: str
    scope: str
    assert_expr: str
    message: str
    pack: str
    when: str | None = None
    units: dict[str, str] = field(default_factory=dict)
    citation: dict[str, Any] = field(default_factory=dict)
    quantitative_basis: str = ""
    when_predicate: Predicate | None = None
    assert_predicate: Predicate | None = None

    @property
    def citation_str(self) -> str:
        src = str(self.citation.get("source", "")).strip()
        year = self.citation.get("year")
        url = str(self.citation.get("doi_or_url", "")).strip()
        parts = [p for p in (src, f"({year})" if year else "", url) if p]
        return " ".join(parts)

    def compile(self) -> None:
        if self.when is not None:
            self.when_predicate = Predicate(self.when)
        self.assert_predicate = Predicate(self.assert_expr)


def validate_pack_data(data: Any, origin: str = "<pack>") -> tuple[list[RuleSpec], list[str]]:
    """Validate a parsed pack document. Returns (rules, errors)."""
    errors: list[str] = []
    rules: list[RuleSpec] = []
    if not isinstance(data, dict):
        return [], [f"{origin}: pack document must be a YAML mapping"]
    pack_name = data.get("pack")
    if not isinstance(pack_name, str) or not pack_name:
        errors.append(f"{origin}: missing 'pack' name")
        pack_name = origin
    if not isinstance(data.get("version"), str):
        errors.append(f"{origin}: missing 'version' string")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        errors.append(f"{origin}: 'rules' must be a non-empty list")
        return [], errors

    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_rules):
        where = f"{origin}: rules[{i}]"
        if not isinstance(raw, dict):
            errors.append(f"{where}: rule must be a mapping")
            continue
        rule_id = raw.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            errors.append(f"{where}: missing 'id'")
            continue
        where = f"{origin}: {rule_id}"
        if rule_id in seen_ids:
            errors.append(f"{where}: duplicate rule id")
        seen_ids.add(rule_id)
        problems: list[str] = []
        layer = raw.get("layer")
        if layer not in _LAYERS:
            problems.append(f"layer must be one of {_LAYERS}")
        severity = raw.get("severity")
        if severity not in _SEVERITIES:
            problems.append(f"severity must be one of {_SEVERITIES}")
        scope = raw.get("scope")
        if scope not in _SCOPES:
            problems.append(f"scope must be one of {_SCOPES}")
        title = raw.get("title")
        if not isinstance(title, str) or not title:
            problems.append("missing 'title'")
        message = raw.get("message")
        if not isinstance(message, str) or not message:
            problems.append("missing 'message'")
        assert_expr = raw.get("assert")
        if not isinstance(assert_expr, str) or not assert_expr:
            problems.append("missing 'assert' predicate")
        when = raw.get("when")
        if when is not None and not isinstance(when, str):
            problems.append("'when' must be a string predicate")
        citation = raw.get("citation")
        if not isinstance(citation, dict) or not citation.get("source"):
            problems.append("missing 'citation' with a 'source' — every rule must be cited")
        if problems:
            errors.extend(f"{where}: {p}" for p in problems)
            continue
        assert isinstance(assert_expr, str)  # narrowed above
        assert isinstance(severity, str) and isinstance(layer, str)
        assert isinstance(scope, str) and isinstance(title, str) and isinstance(message, str)
        assert isinstance(citation, dict)
        spec = RuleSpec(
            id=rule_id,
            layer=layer,
            severity=severity,
            title=title,
            scope=scope,
            assert_expr=assert_expr,
            message=" ".join(message.split()),
            pack=pack_name,
            when=when,
            units=dict(raw.get("units") or {}),
            citation=citation,
            quantitative_basis=" ".join(str(raw.get("quantitative_basis", "")).split()),
        )
        try:
            spec.compile()
        except PredicateError as exc:
            errors.append(f"{where}: {exc}")
            continue
        rules.append(spec)
    return rules, errors


def load_pack(path: str | Path) -> tuple[list[RuleSpec], list[str]]:
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [], [f"{p}: cannot load pack: {exc}"]
    return validate_pack_data(data, origin=p.name)


def default_pack_paths() -> list[Path]:
    """Shipped catalog packs (package data, with a repo-layout fallback)."""
    candidates: list[Path] = []
    pkg_dir = resources.files("physcheck") / "catalog"
    with resources.as_file(pkg_dir) as concrete:
        if concrete.is_dir():
            candidates = sorted(concrete.glob("*.yaml"))
    if not candidates:
        repo = Path(__file__).resolve().parents[3] / "catalog"
        if repo.is_dir():
            candidates = sorted(repo.glob("*.yaml"))
    return candidates


def load_default_packs() -> tuple[list[RuleSpec], list[str]]:
    rules: list[RuleSpec] = []
    errors: list[str] = []
    for path in default_pack_paths():
        pack_rules, pack_errors = load_pack(path)
        rules.extend(pack_rules)
        errors.extend(pack_errors)
    return rules, errors
