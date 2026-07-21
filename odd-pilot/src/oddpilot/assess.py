"""PWCC — probability-weighted combinatorial coverage with a risk-calibrated
stopping rule (design brief §Component 3).

For every t-way feature-value combination c:
  P~(c)     credited operational mass, estimated by forward-sampling the
            operational model:  P~(c) ≈ Σ_{s ~ BN} 1[s ⊨ c] / (n_samples · K),
            K = C(#features, t), so Σ_c P~(c) ≈ 1.
  E(c)      exposure: summed duration (hours) of executed runs consistent
            with c.
  E_min(c)  = -ln(α) · P~(c) / ρ — the exposure needed to bound the residual
            event rate of c below risk budget ρ (events/h) with confidence
            1-α. α and ρ only enter through F = -ln(α)/ρ.
  c is SUFFICIENT iff E(c) ≥ E_min(c).
  PWCC_t = Σ_{c sufficient} P~(c);  adequate iff 1 - PWCC_t < ε.

Adequacy is a coverage claim, not a fault-absence claim. The PWCC study's
parameter sweep showed ε is the well-behaved knob (lowering ρ lifts the
irreducible uncovered floor and can never certify) and that mass fragments as
t grows, so ε should SHRINK with t — pass per-t epsilons for that.

Ported from the validated PWCC research implementation (methods/pwcc/pwcc.py;
credited-mass estimator from the vectorised fast_credited_mass of
evaluation/param_sweep_stopping.py, which mirrors the reference exactly).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import pandas as pd

from oddpilot.opmodel import OperationalModel

__all__ = ["Combo", "AssessmentResult", "assess", "credited_mass", "exposure"]

#: A combination key: ((feature, value), ...) sorted by feature position.
Combo = tuple[tuple[str, str], ...]


@dataclass
class AssessmentResult:
    t: int
    alpha: float
    rho: float
    epsilon: float
    n_samples: int
    credited: dict[Combo, float]
    exposure_h: dict[Combo, float]
    min_exposure_h: dict[Combo, float]
    sufficient: dict[Combo, bool] = field(init=False)
    covered_mass: float = field(init=False)
    uncovered_mass: float = field(init=False)

    def __post_init__(self) -> None:
        self.sufficient = {
            c: self.exposure_h.get(c, 0.0) >= self.min_exposure_h[c]
            for c in self.credited
        }
        self.covered_mass = sum(
            m for c, m in self.credited.items() if self.sufficient[c]
        )
        self.uncovered_mass = sum(
            m for c, m in self.credited.items() if not self.sufficient[c]
        )

    @property
    def is_adequate(self) -> bool:
        return self.uncovered_mass < self.epsilon

    @property
    def factor(self) -> float:
        """F = -ln(α)/ρ — the single knob α and ρ collapse into."""
        return -math.log(self.alpha) / self.rho

    def gaps(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Insufficient combinations ranked by residual mass — the
        gap-targeted generator's input."""
        rows: list[dict[str, Any]] = [
            {
                "combination": " & ".join(f"{k}={v}" for k, v in combo),
                "residual_mass": mass,
                "actual_exposure_h": round(self.exposure_h.get(combo, 0.0), 6),
                "required_exposure_h": round(self.min_exposure_h[combo], 6),
                "combo": combo,
            }
            for combo, mass in self.credited.items()
            if not self.sufficient[combo]
        ]
        rows.sort(key=lambda r: float(r["residual_mass"]), reverse=True)
        return rows[:limit] if limit is not None else rows

    def summary(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "alpha": self.alpha,
            "rho": self.rho,
            "factor_F": round(self.factor, 4),
            "epsilon": self.epsilon,
            "n_bn_samples": self.n_samples,
            "n_combinations": len(self.credited),
            "n_sufficient": sum(self.sufficient.values()),
            "n_insufficient": sum(1 for v in self.sufficient.values() if not v),
            "covered_mass": round(self.covered_mass, 6),
            "uncovered_mass": round(self.uncovered_mass, 6),
            "is_adequate": self.is_adequate,
            "verdict": "ADEQUATE" if self.is_adequate else "INADEQUATE",
        }

    def ledger(self) -> pd.DataFrame:
        """Per-combination exposure ledger, heaviest mass first."""
        rows = []
        for combo, mass in self.credited.items():
            actual = self.exposure_h.get(combo, 0.0)
            required = self.min_exposure_h[combo]
            rows.append(
                {
                    "combination": " & ".join(f"{k}={v}" for k, v in combo),
                    "credited_mass": mass,
                    "actual_exposure_h": actual,
                    "required_exposure_h": required,
                    "exposure_ratio": actual / required if required > 0 else math.inf,
                    "sufficient": self.sufficient[combo],
                }
            )
        return pd.DataFrame(rows).sort_values(
            "credited_mass", ascending=False, ignore_index=True
        )


def credited_mass(
    model: OperationalModel,
    t: int,
    n_samples: int = 50_000,
    seed: int | None = None,
) -> tuple[dict[Combo, float], list[str]]:
    """P~(c) for every observed t-way combination, by BN forward sampling.

    weight = 1/(n_samples·K); each sampled scenario credits each of its K
    projections once, so Σ_c P~(c) ≈ 1. Vectorised: one groupby per
    variable combination instead of a Python double loop.
    """
    cols = list(model.feature_cols)
    if not 1 <= t <= len(cols):
        raise ValueError(f"t={t} out of range for {len(cols)} feature columns")
    samples = model.bn.simulate(
        n_samples=n_samples, seed=seed, show_progress=False
    )
    samples = samples[[c for c in cols if c in samples.columns]].astype(str)
    k = math.comb(len(cols), t)
    weight = 1.0 / (n_samples * k)
    credited: dict[Combo, float] = {}
    for var_combo in combinations(cols, t):
        vcl = list(var_combo)
        counts = samples.groupby(vcl, sort=False).size()
        for key, cnt in counts.items():
            values = (key,) if len(vcl) == 1 else key
            combo: Combo = tuple(zip(vcl, values, strict=True))
            credited[combo] = cnt * weight
    return credited, cols


def exposure(
    runs: pd.DataFrame,
    feature_cols: list[str],
    credited: dict[Combo, float],
    t: int,
    duration_col: str = "run_duration",
) -> dict[Combo, float]:
    """E(c) in hours over the execution log; only combinations carrying
    credited mass are tracked (others hold no mass by construction)."""
    if duration_col not in runs.columns:
        raise ValueError(
            f"duration column '{duration_col}' not in run log; available: "
            f"{list(runs.columns)}"
        )
    missing = [c for c in feature_cols if c not in runs.columns]
    if missing:
        raise ValueError(f"run log lacks feature column(s): {missing}")
    frame = runs[feature_cols].astype(str).copy()
    frame["__hours"] = pd.to_numeric(runs[duration_col]) / 3600.0
    exp: dict[Combo, float] = {}
    for var_combo in combinations(feature_cols, t):
        vcl = list(var_combo)
        sums = frame.groupby(vcl, sort=False)["__hours"].sum()
        for key, hours in sums.items():
            values = (key,) if len(vcl) == 1 else key
            combo: Combo = tuple(zip(vcl, values, strict=True))
            if combo in credited:
                exp[combo] = exp.get(combo, 0.0) + float(hours)
    return exp


def assess(
    model: OperationalModel,
    runs: pd.DataFrame,
    *,
    t: int,
    alpha: float = 0.05,
    rho: float = 0.01,
    epsilon: float = 0.05,
    duration_col: str = "run_duration",
    n_samples: int = 50_000,
    seed: int | None = None,
) -> AssessmentResult:
    """Full PWCC assessment of an execution log for one t."""
    credited, cols = credited_mass(model, t, n_samples, seed)
    exp = exposure(runs, cols, credited, t, duration_col)
    factor = -math.log(alpha) / rho
    min_exp = {combo: factor * mass for combo, mass in credited.items()}
    return AssessmentResult(
        t=t,
        alpha=alpha,
        rho=rho,
        epsilon=epsilon,
        n_samples=n_samples,
        credited=credited,
        exposure_h=exp,
        min_exposure_h=min_exp,
    )
