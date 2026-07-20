"""Cross-environment consistency checks (need all environment states at once).

FRI-024: within one scenario, a more severe road water state must not be
assigned a higher friction scale factor than a less severe one — the friction
vs water-film-depth relation is monotone at every speed (Bosch Automotive
Handbook 4th ed. p. 330 friction table; Gallaway et al., FHWA-RD-79-31).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physcheck.ir.model import Scenario

if TYPE_CHECKING:  # imported late at runtime to avoid a cycle with engine.py
    from physcheck.engine.engine import Finding

__all__ = ["PLUGIN_RULES", "cross_findings"]

#: id -> (layer, severity, title, citation)
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    "FRI-024": (
        "L1",
        "error",
        "Friction scale not monotone in road wetness across environment states",
        "Robert Bosch GmbH, Automotive Handbook, 4th ed., p. 330 (friction "
        "monotone in water film depth at all speeds); Gallaway et al., "
        "FHWA-RD-79-31, FHWA (1979)",
    ),
}

_WETNESS_SEVERITY = {
    "dry": 0,
    "moist": 1,
    "wetWithPuddles": 2,
    "lowFlooded": 3,
    "highFlooded": 4,
}


def cross_findings(scenario: Scenario) -> list[Finding]:
    from physcheck.engine.engine import Finding

    states: list[tuple[str, int, float]] = []
    for env in scenario.environments:
        road = env.road_condition
        if road is None or road.wetness is None or road.friction_scale_factor is None:
            continue
        severity = _WETNESS_SEVERITY.get(road.wetness)
        if severity is not None:
            states.append((env.label, severity, road.friction_scale_factor))

    findings: list[Finding] = []
    layer, sev, title, citation = PLUGIN_RULES["FRI-024"]
    for i, (label_a, sev_a, fric_a) in enumerate(states):
        for label_b, sev_b, fric_b in states[i + 1 :]:
            drier, wetter = ((label_a, sev_a, fric_a), (label_b, sev_b, fric_b))
            if sev_a > sev_b:
                drier, wetter = wetter, drier
            if drier[1] == wetter[1] or wetter[2] <= drier[2]:
                continue
            findings.append(
                Finding(
                    rule_id="FRI-024",
                    severity=sev,
                    layer=layer,
                    title=title,
                    message=(
                        f"Environment '{wetter[0]}' declares a wetter road "
                        f"(severity {wetter[1]}) with HIGHER frictionScaleFactor "
                        f"({wetter[2]}) than environment '{drier[0]}' "
                        f"(severity {drier[1]}, frictionScaleFactor {drier[2]}): "
                        "friction is monotonically decreasing in water film depth."
                    ),
                    file=scenario.source_path,
                    context=f"{drier[0]} vs {wetter[0]}",
                    values={
                        "drier.friction_scale": drier[2],
                        "wetter.friction_scale": wetter[2],
                    },
                    citation=citation,
                )
            )
    return findings
