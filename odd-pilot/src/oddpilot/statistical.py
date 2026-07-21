"""L6 scorer: probability of a scenario's attributes under the operational BN.

The model must carry an ``attribute_map`` (stored by ``model fit
--attribute-map map.yaml``) that binds each BN feature column to a physcheck
attribute-view name, with optional bins for continuous attributes:

    feature_precip:
      attribute: env.precip.type          # enum: value used as-is
    feature_temp:
      attribute: env.temperature_k
      bins:                               # continuous: label by range
        - {label: cold, max: 268}
        - {label: mild, min: 268, max: 298}
        - {label: warm, min: 298}

``scorer_for`` returns the callable physcheck's L6 tier injects: attribute
view -> (joint log probability, empirical quantile within the model's own
reference sample) — or None when the scenario does not declare every mapped
attribute. Assignments outside the BN's state space score -inf / quantile 0.
The reference sample (sorted log-probabilities of forward samples) is
computed once at fit time and travels inside the model file (D36).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable
from pathlib import Path
from typing import Any

from oddpilot.opmodel import OperationalModel, load

__all__ = ["joint_logp", "reference_logps", "scorer_for"]


def joint_logp(model: OperationalModel, assignment: dict[str, str]) -> float:
    """log P(assignment) via the chain rule over the BN's CPDs; -inf when the
    assignment uses a state the network has never seen."""
    logp = 0.0
    for cpd in model.bn.get_cpds():
        var = cpd.variable
        states = {var: assignment[var]}
        for parent in cpd.get_evidence():
            states[parent] = assignment[parent]
        try:
            p = float(cpd.get_value(**states))
        except (KeyError, ValueError, IndexError, TypeError):
            return -math.inf  # a state the network has never seen
        if p <= 0.0:
            return -math.inf
        logp += math.log(p)
    return logp


def reference_logps(
    model: OperationalModel, n_samples: int = 2000, seed: int | None = None
) -> list[float]:
    """Sorted joint log-probabilities of forward samples — the empirical
    distribution 'real operation' induces over its own scores."""
    samples = model.bn.simulate(n_samples=n_samples, seed=seed, show_progress=False)
    scores = [
        joint_logp(model, {c: str(v) for c, v in row.items()})
        for _, row in samples.iterrows()
    ]
    return sorted(scores)


def _label(spec: dict[str, Any], value: object) -> str | None:
    bins = spec.get("bins")
    if not bins:
        return str(value)
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    for entry in bins:
        lo = entry.get("min")
        hi = entry.get("max")
        if (lo is None or number >= float(lo)) and (hi is None or number <= float(hi)):
            return str(entry["label"])
    return None


def scorer_for(
    model_path: str | Path,
) -> Callable[[dict[str, object]], tuple[float, float] | None]:
    """Build physcheck's L6 scorer from a saved operational model."""
    model = load(model_path)
    attribute_map: dict[str, dict[str, Any]] | None = model.meta.get("attribute_map")
    reference: list[float] | None = model.meta.get("reference_logps")
    if not attribute_map:
        raise ValueError(
            f"model {model_path} carries no attribute_map — refit with "
            "'odd-pilot model fit --attribute-map map.yaml' to enable L6"
        )
    if not reference:
        raise ValueError(
            f"model {model_path} carries no reference score sample — refit "
            "with odd-pilot >= 0.6"
        )

    def scorer(attrs: dict[str, object]) -> tuple[float, float] | None:
        assignment: dict[str, str] = {}
        for feature, spec in attribute_map.items():
            value = attrs.get(str(spec.get("attribute")))
            if value is None:
                return None  # scenario does not declare this attribute
            label = _label(spec, value)
            if label is None:
                return -math.inf, 0.0  # declared, but outside every bin
            assignment[feature] = label
        logp = joint_logp(model, assignment)
        if math.isinf(logp):
            return logp, 0.0
        rank = bisect_right(reference, logp)
        return logp, rank / len(reference)

    return scorer
