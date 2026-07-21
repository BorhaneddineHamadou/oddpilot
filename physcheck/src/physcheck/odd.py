"""ODD definitions and conformance verdicts (layer L5).

The definition is a YAML file keyed by physcheck's canonical attribute names
(docs/attribute_space.md), implementing OpenODD's include/exclude condition
semantics: a declared value is IN when it satisfies the ``include``
condition (if any) and hits no ``exclude`` condition; OUT otherwise; and
UNDECLARED when the scenario does not declare the attribute at all — the ODD
constrains something the scenario leaves unspecified, so conformance cannot
be established (decision D34).

    odd:
      name: urban-daytime-dry
      attributes:
        env.temperature_k:
          include: {min: 263, max: 313}
          exclude:
            - {min: 268, max: 271}     # black-ice band carved out
        env.precip.type:
          include: [dry, rain]
        env.road.wetness:
          exclude: [lowFlooded, highFlooded]
        entity.max_target_speed_mps:   # entity.* constraints: per entity
          include: {max: 20}

``include``/``exclude`` accept an enum list, a ``{min,max}`` range (either
bound optional), or a list of ranges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = ["Constraint", "OddDefinition", "Verdict", "conformance", "load_odd"]

#: "in" | "out" | "undeclared"
Verdict = str


@dataclass
class Constraint:
    attribute: str
    include_values: list[str] = field(default_factory=list)
    include_ranges: list[tuple[float | None, float | None]] = field(default_factory=list)
    exclude_values: list[str] = field(default_factory=list)
    exclude_ranges: list[tuple[float | None, float | None]] = field(default_factory=list)

    def verdict(self, value: object) -> Verdict:
        if value is None:
            return "undeclared"
        text = str(value)
        number: float | None
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            number = None

        def in_range(rng: tuple[float | None, float | None]) -> bool:
            if number is None:
                return False
            lo, hi = rng
            return (lo is None or number >= lo) and (hi is None or number <= hi)

        if self.include_values or self.include_ranges:
            included = text in self.include_values or any(
                in_range(r) for r in self.include_ranges
            )
            if not included:
                return "out"
        if text in self.exclude_values or any(in_range(r) for r in self.exclude_ranges):
            return "out"
        return "in"


@dataclass
class OddDefinition:
    name: str
    constraints: list[Constraint] = field(default_factory=list)
    source_path: str = "<odd>"
    issues: list[str] = field(default_factory=list)


def _parse_condition(
    raw: object, attribute: str, kind: str, constraint: Constraint,
    issues: list[str],
) -> None:
    values = constraint.include_values if kind == "include" else constraint.exclude_values
    ranges = constraint.include_ranges if kind == "include" else constraint.exclude_ranges
    items = raw if isinstance(raw, list) else [raw]
    for item in items:
        if isinstance(item, dict):
            lo, hi = item.get("min"), item.get("max")
            if lo is None and hi is None:
                issues.append(f"{attribute}: {kind} range needs min and/or max")
                continue
            try:
                ranges.append(
                    (None if lo is None else float(lo),
                     None if hi is None else float(hi))
                )
            except (TypeError, ValueError):
                issues.append(f"{attribute}: non-numeric {kind} bound {item!r}")
        elif isinstance(item, (str, int, float, bool)):
            values.append(str(item))
        else:
            issues.append(f"{attribute}: unsupported {kind} item {item!r}")


def load_odd(path: str | Path) -> OddDefinition:
    path = Path(path)
    raw: Any = yaml.safe_load(path.read_text())
    issues: list[str] = []
    body = raw.get("odd") if isinstance(raw, dict) else None
    if not isinstance(body, dict):
        return OddDefinition(
            name=path.stem, source_path=str(path),
            issues=["missing top-level 'odd:' mapping"],
        )
    attributes = body.get("attributes")
    constraints: list[Constraint] = []
    if not isinstance(attributes, dict) or not attributes:
        issues.append("odd.attributes is missing or empty")
    else:
        for attribute, spec in attributes.items():
            constraint = Constraint(attribute=str(attribute))
            if not isinstance(spec, dict) or not (
                "include" in spec or "exclude" in spec
            ):
                issues.append(f"{attribute}: needs an include: and/or exclude: block")
                continue
            for kind in ("include", "exclude"):
                if kind in spec:
                    _parse_condition(spec[kind], str(attribute), kind, constraint, issues)
            constraints.append(constraint)
    return OddDefinition(
        name=str(body.get("name", path.stem)),
        constraints=constraints,
        source_path=str(path),
        issues=issues,
    )


def conformance(
    scenario: Any, odd: OddDefinition
) -> list[tuple[str, str, Verdict, object]]:
    """(context_label, attribute, verdict, value) for every constraint over
    every applicable context: entity.* constraints per concrete entity,
    everything else per declared environment state."""
    from physcheck.ir.attributes import entity_contexts, scenario_contexts

    env_ctx = scenario_contexts(scenario)
    ent_ctx = entity_contexts(scenario)
    rows: list[tuple[str, str, Verdict, object]] = []
    for constraint in odd.constraints:
        contexts = ent_ctx if constraint.attribute.startswith("entity.") else env_ctx
        if not contexts:
            rows.append(("<no context>", constraint.attribute, "undeclared", None))
            continue
        for label, attrs in contexts:
            value = attrs.get(constraint.attribute)
            rows.append((label, constraint.attribute, constraint.verdict(value), value))
    return rows
