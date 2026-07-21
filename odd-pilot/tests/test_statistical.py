"""odd-pilot L6 scorer: joint probability + empirical quantile from the BN."""

from __future__ import annotations

import math
import random
from pathlib import Path

import pandas as pd
import pytest

from oddpilot import opmodel
from oddpilot.statistical import joint_logp, scorer_for

ATTRIBUTE_MAP = {
    "feature_precip": {"attribute": "env.precip.type"},
    "feature_temp": {
        "attribute": "env.temperature_k",
        "bins": [
            {"label": "cold", "max": 268},
            {"label": "mild", "min": 268, "max": 298},
            {"label": "warm", "min": 298},
        ],
    },
}


@pytest.fixture(scope="module")
def model_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Warm rain never occurs in this world; mild dry weather dominates."""
    rng = random.Random(7)
    rows = []
    for _ in range(600):
        rain = rng.random() < 0.25
        temp = "cold" if (not rain and rng.random() < 0.2) else "mild"
        rows.append({"feature_precip": "rain" if rain else "dry",
                     "feature_temp": temp})
    model = opmodel.fit(
        pd.DataFrame(rows), seed=7, n_restarts=1, attribute_map=ATTRIBUTE_MAP
    )
    path = tmp_path_factory.mktemp("model") / "odd.bn"
    model.save(path)
    return path


def test_reference_sample_travels_with_the_model(model_path: Path) -> None:
    meta = opmodel.load(model_path).meta
    assert meta["attribute_map"] == ATTRIBUTE_MAP
    assert len(meta["reference_logps"]) == 2000
    assert meta["reference_logps"] == sorted(meta["reference_logps"])


def test_joint_logp_orders_common_above_rare(model_path: Path) -> None:
    model = opmodel.load(model_path)
    common = joint_logp(model, {"feature_precip": "dry", "feature_temp": "mild"})
    # rain+cold: both states observed individually, never together — BDeu
    # smoothing keeps the combination possible but tiny.
    rare = joint_logp(model, {"feature_precip": "rain", "feature_temp": "cold"})
    assert common > rare
    assert rare > -math.inf
    # 'warm'/'hail' are states the training data never contained at all:
    # outside the CPD state space entirely -> impossible under the model.
    assert joint_logp(model, {"feature_precip": "rain", "feature_temp": "warm"}) == -math.inf
    assert joint_logp(model, {"feature_precip": "hail", "feature_temp": "mild"}) == -math.inf


def test_scorer_quantiles(model_path: Path) -> None:
    scorer = scorer_for(model_path)
    common = scorer({"env.precip.type": "dry", "env.temperature_k": 288.0})
    rare = scorer({"env.precip.type": "rain", "env.temperature_k": 260.0})
    unseen = scorer({"env.precip.type": "rain", "env.temperature_k": 305.0})
    assert common is not None and rare is not None and unseen is not None
    assert common[1] > 0.2         # the dominant regime sits mid-distribution
    assert rare[1] <= 0.02         # observed states, never-observed combination
    assert unseen == (-math.inf, 0.0)  # 'warm' outside the model's state space
    assert scorer({"env.temperature_k": 288.0}) is None  # precip undeclared


def test_scorer_requires_attribute_map(tmp_path: Path) -> None:
    model = opmodel.fit(
        pd.DataFrame({"feature_a": ["x", "y"] * 30}), seed=1, n_restarts=0
    )
    path = tmp_path / "bare.bn"
    model.save(path)
    with pytest.raises(ValueError, match="attribute_map"):
        scorer_for(path)
