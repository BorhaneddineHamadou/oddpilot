"""Operational model: a discrete Bayesian network over ODD feature columns.

Learned from a profiling table of real operation (one row per observed
scenario/segment, columns ``feature_*`` categorical). The BN is the
operational distribution P(s) that PWCC weights coverage with: structure via
Hill-Climb Search (BIC by default, several random restarts against local
optima), parameters via BDeu smoothing so every scenario keeps non-zero
probability — a PWCC requirement.

Ported from the validated PWCC research implementation
(scripts/train_bayesian_networks.py of the PWCC study).
"""

from __future__ import annotations

import pickle
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from pgmpy.base import DAG
from pgmpy.estimators import BayesianEstimator, BicScore, HillClimbSearch, K2Score
from pgmpy.models import BayesianNetwork

__all__ = [
    "OperationalModel",
    "extract_feature_columns",
    "fit",
    "load",
]

#: On-disk format version for the pickled model container.
_FORMAT = 1


@dataclass
class OperationalModel:
    """A fitted BN plus the metadata needed to reuse it faithfully."""

    bn: BayesianNetwork
    feature_cols: list[str]
    meta: dict[str, Any] = field(default_factory=dict)

    def save(self, path: str | Path) -> None:
        payload = {
            "format": _FORMAT,
            "bn": self.bn,
            "feature_cols": self.feature_cols,
            "meta": self.meta,
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(payload, fh)


def load(path: str | Path) -> OperationalModel:
    with open(path, "rb") as fh:
        payload = pickle.load(fh)
    if isinstance(payload, BayesianNetwork):  # bare research-repo pickle
        return OperationalModel(
            bn=payload, feature_cols=sorted(payload.nodes()), meta={"format": 0}
        )
    return OperationalModel(
        bn=payload["bn"],
        feature_cols=list(payload["feature_cols"]),
        meta=dict(payload.get("meta", {})),
    )


def extract_feature_columns(df: pd.DataFrame) -> list[str]:
    cols = [c for c in df.columns if c.startswith("feature_")]
    if not cols:
        raise ValueError(
            "no columns starting with 'feature_' found; available: "
            f"{list(df.columns)}"
        )
    return cols


def _feature_frame(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Feature columns only, rows with missing values dropped, all values as
    str so pgmpy treats every node as discrete."""
    data = df[feature_cols].dropna().copy()
    if data.empty:
        raise ValueError("no complete rows to fit on after dropping missing values")
    for col in data.columns:
        data[col] = data[col].astype(str)
    return data


def _random_dag(nodes: list[str], max_indegree: int, rng: random.Random) -> DAG:
    """Random sparse DAG — acyclic by construction (parents precede children)."""
    dag = DAG()
    dag.add_nodes_from(nodes)
    order = nodes[:]
    rng.shuffle(order)
    for j, child in enumerate(order):
        pool = order[:j]
        rng.shuffle(pool)
        for parent in pool[: rng.randint(0, min(max_indegree, len(pool)))]:
            dag.add_edge(parent, child)
    return dag


def fit(
    df: pd.DataFrame,
    feature_cols: list[str] | None = None,
    *,
    scoring: str = "bic",
    max_indegree: int = 4,
    n_restarts: int = 3,
    ess: float = 5.0,
    seed: int | None = None,
    attribute_map: dict[str, Any] | None = None,
) -> OperationalModel:
    """Learn structure + parameters and return a validated OperationalModel.

    Raises ValueError when the fitted model fails pgmpy validation or any CPT
    contains a zero probability (which would break PWCC's mass estimates).
    """
    if feature_cols is None:
        feature_cols = extract_feature_columns(df)
    data = _feature_frame(df, feature_cols)
    rng = random.Random(seed)

    score_fn = BicScore(data) if scoring == "bic" else K2Score(data)
    hc = HillClimbSearch(data)
    nodes = list(data.columns)

    t0 = time.perf_counter()
    best_dag: DAG | None = None
    best_score = -float("inf")
    starts: list[DAG | None] = [None] + [
        _random_dag(nodes, max_indegree, rng) for _ in range(n_restarts)
    ]
    errors: list[str] = []
    for start in starts:
        try:
            dag = hc.estimate(
                scoring_method=score_fn,
                max_indegree=max_indegree,
                start_dag=start,
                show_progress=False,
            )
        except Exception as exc:  # a single failed restart is not fatal
            errors.append(str(exc))
            continue
        score = sum(
            score_fn.local_score(node, list(dag.predecessors(node)))
            for node in dag.nodes()
        )
        if score > best_score:
            best_score, best_dag = score, dag
    if best_dag is None:
        raise RuntimeError(f"all structure-learning runs failed: {errors}")
    t_structure = time.perf_counter() - t0

    t0 = time.perf_counter()
    bn = BayesianNetwork(list(best_dag.edges()))
    for col in nodes:  # isolated nodes still carry their marginal
        if col not in bn.nodes():
            bn.add_node(col)
    bn.fit(
        data,
        estimator=BayesianEstimator,
        prior_type="BDeu",
        equivalent_sample_size=ess,
    )
    t_params = time.perf_counter() - t0

    validation = _validate(bn, data, score_fn)
    if not validation["model_valid"]:
        raise ValueError("fitted BN failed pgmpy validation")
    if not validation["no_zero_probs"]:
        raise ValueError(
            "fitted BN contains zero probabilities — increase --ess; PWCC "
            "requires P(s) > 0 for every scenario"
        )

    meta = {
        "n_rows": len(data),
        "scoring": scoring,
        "max_indegree": max_indegree,
        "n_restarts": n_restarts,
        "ess": ess,
        "seed": seed,
        "structure_score": round(float(best_score), 4),
        "structure_learning_s": round(t_structure, 4),
        "parameter_fitting_s": round(t_params, 4),
        "edges": sorted((str(a), str(b)) for a, b in bn.edges()),
        **validation,
    }
    model = OperationalModel(bn=bn, feature_cols=list(nodes), meta=meta)
    if attribute_map is not None:
        missing = [f for f in attribute_map if f not in nodes]
        if missing:
            raise ValueError(
                f"attribute_map references feature column(s) not in the "
                f"model: {missing}"
            )
        from oddpilot.statistical import reference_logps

        meta["attribute_map"] = attribute_map
        meta["reference_logps"] = reference_logps(model, seed=seed)
    return model


def _validate(
    bn: BayesianNetwork, data: pd.DataFrame, score_fn: BicScore | K2Score
) -> dict[str, Any]:
    cpds = bn.get_cpds()
    min_prob = min(float(cpd.get_values().min()) for cpd in cpds)
    return {
        "model_valid": bool(bn.check_model()),
        "cpd_sums_ok": all(
            abs(cpd.get_values().sum(axis=0) - 1.0).max() < 1e-6 for cpd in cpds
        ),
        "no_zero_probs": min_prob > 0.0,
        "min_prob": round(min_prob, 10),
        "fit_score": round(
            float(
                sum(
                    score_fn.local_score(n, list(bn.predecessors(n)))
                    for n in bn.nodes()
                )
            ),
            4,
        ),
        "n_nodes": bn.number_of_nodes(),
        "n_edges": bn.number_of_edges(),
    }
