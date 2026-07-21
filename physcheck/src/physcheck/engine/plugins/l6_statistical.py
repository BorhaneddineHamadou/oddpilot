"""L6 statistical plausibility: score scenarios under an operational model.

Design brief §4 L6: score each scenario's environmental assignment under the
learned operational model; combinations with near-zero probability under the
joint (below a configurable quantile) are flagged ``warning: never-observed``.
This tier is data-driven and NEVER blocks execution — the single rule is a
warning by design.

physcheck carries no model dependency: the caller injects a ``scorer``
callable (odd-pilot provides one from its Bayesian network via
``oddpilot.statistical.scorer_for``). The scorer receives the scenario's
attribute view and returns ``(log_probability, empirical_quantile)`` — the
quantile of the score within the model's own reference sample — or ``None``
when the scenario does not declare the attributes the model needs (D36).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from physcheck.ir.attributes import Attrs, scenario_contexts
from physcheck.ir.model import Scenario

if TYPE_CHECKING:  # imported late at runtime to avoid a cycle with engine.py
    from physcheck.engine.engine import Finding

__all__ = ["PLUGIN_RULES", "Scorer", "statistical_findings"]

#: (attribute view) -> (log probability, empirical quantile in [0, 1]) | None.
Scorer = Callable[[Attrs], "tuple[float, float] | None"]

#: id -> (layer, severity, title, citation)
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    "STA-001": (
        "L6", "warning",
        "Never-observed condition combination under the operational model",
        "Design brief §4 L6 (statistical plausibility tier): probability "
        "under the learned joint distribution of real operation, flagged "
        "below a configurable quantile; data-driven, never blocks execution",
    ),
}


def statistical_findings(
    scenario: Scenario, scorer: Scorer, quantile: float = 0.01
) -> list[Finding]:
    from physcheck.engine.engine import Finding

    findings: list[Finding] = []
    layer, severity, title, citation = PLUGIN_RULES["STA-001"]
    for label, attrs in scenario_contexts(scenario):
        scored = scorer(attrs)
        if scored is None:
            continue  # the model's attributes are not declared here
        logp, empirical = scored
        if empirical < quantile:
            findings.append(
                Finding(
                    rule_id="STA-001", severity=severity, layer=layer,
                    title=title,
                    message=(
                        f"This environmental assignment sits at the "
                        f"{empirical:.2%} quantile of the operational model "
                        f"(log p = {logp:.2f}), below the configured "
                        f"{quantile:.0%} floor: real operation essentially "
                        "never offers this combination. Warning only — "
                        "statistical rarity never blocks execution."
                    ),
                    file=scenario.source_path, context=label,
                    values={"sta.log_p": round(logp, 4),
                            "sta.quantile": round(empirical, 6)},
                    citation=citation,
                )
            )
    return findings
