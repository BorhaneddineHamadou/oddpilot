"""odd-pilot model/assess/gaps: the PWCC port.

Small synthetic operational world with a known dependency so structure
learning has something to find, plus hand-computed checks of the exposure
ledger and the E_min formula.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pandas as pd
import pytest

from oddpilot import assess as pwcc
from oddpilot import opmodel
from oddpilot.cli import _parse_sweep, main

N_SAMPLES = 4000  # BN forward samples: small but stable for 3 binary-ish nodes


@pytest.fixture(scope="module")
def profiling() -> pd.DataFrame:
    """400 observed segments: rain makes the road wet, night is independent."""
    rng = random.Random(7)
    rows = []
    for _ in range(400):
        rain = rng.random() < 0.3
        wet = rng.random() < (0.9 if rain else 0.1)
        rows.append(
            {
                "feature_weather": "rain" if rain else "clear",
                "feature_road": "wet" if wet else "dry",
                "feature_time": "night" if rng.random() < 0.4 else "day",
                "run_duration": 60.0,  # non-feature column must be ignored
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def model(profiling: pd.DataFrame) -> opmodel.OperationalModel:
    return opmodel.fit(profiling, seed=7, n_restarts=1)


def _runs(rows: list[tuple[str, str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "feature_weather": w,
                "feature_road": r,
                "feature_time": t,
                "run_duration": d,
            }
            for w, r, t, d in rows
        ]
    )


# ── model ───────────────────────────────────────────────────────────────────


def test_fit_validates_and_reports(model: opmodel.OperationalModel) -> None:
    meta = model.meta
    assert meta["model_valid"] and meta["cpd_sums_ok"] and meta["no_zero_probs"]
    assert meta["n_nodes"] == 3
    assert sorted(model.feature_cols) == [
        "feature_road", "feature_time", "feature_weather",
    ]


def test_save_load_roundtrip(
    model: opmodel.OperationalModel, tmp_path: Path
) -> None:
    path = tmp_path / "odd.bn"
    model.save(path)
    loaded = opmodel.load(path)
    assert loaded.feature_cols == model.feature_cols
    assert loaded.meta["edges"] == model.meta["edges"]


def test_fit_rejects_featureless_frame() -> None:
    with pytest.raises(ValueError, match="feature_"):
        opmodel.fit(pd.DataFrame({"speed": [1, 2]}))


# ── credited mass ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("t", [1, 2, 3])
def test_credited_mass_sums_to_one(
    model: opmodel.OperationalModel, t: int
) -> None:
    credited, cols = pwcc.credited_mass(model, t, n_samples=N_SAMPLES, seed=1)
    assert len(cols) == 3
    assert sum(credited.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(len(combo) == t for combo in credited)


def test_credited_mass_reflects_the_dependency(
    model: opmodel.OperationalModel,
) -> None:
    credited, _ = pwcc.credited_mass(model, 2, n_samples=N_SAMPLES, seed=1)
    # combo keys follow the model's feature-column order (weather, road, time)
    rain_wet = credited.get(
        (("feature_weather", "rain"), ("feature_road", "wet")), 0.0
    )
    rain_dry = credited.get(
        (("feature_weather", "rain"), ("feature_road", "dry")), 0.0
    )
    assert rain_wet > rain_dry  # rain → wet dominates rain → dry


def test_t_out_of_range(model: opmodel.OperationalModel) -> None:
    with pytest.raises(ValueError, match="out of range"):
        pwcc.credited_mass(model, 4, n_samples=100)


# ── exposure (hand-computed, no BN involved) ────────────────────────────────


def test_exposure_ledger_hours() -> None:
    cols = ["feature_weather", "feature_road"]
    combo: pwcc.Combo = (("feature_weather", "rain"), ("feature_road", "wet"))
    credited = {combo: 0.5}
    runs = _runs(
        [
            ("rain", "wet", "day", 1800.0),
            ("rain", "wet", "night", 900.0),
            ("clear", "dry", "day", 7200.0),  # different combo: not tracked
        ]
    )
    exp = pwcc.exposure(runs, cols, credited, t=2, duration_col="run_duration")
    assert exp[combo] == pytest.approx((1800.0 + 900.0) / 3600.0)
    assert len(exp) == 1


def test_exposure_requires_columns() -> None:
    runs = _runs([("rain", "wet", "day", 60.0)])
    with pytest.raises(ValueError, match="duration column"):
        pwcc.exposure(runs, ["feature_weather"], {}, 1, duration_col="nope")
    with pytest.raises(ValueError, match="lacks feature"):
        pwcc.exposure(runs, ["feature_missing"], {}, 1)


# ── assessment ──────────────────────────────────────────────────────────────


def test_min_exposure_formula(model: opmodel.OperationalModel) -> None:
    r = pwcc.assess(
        model, _runs([("rain", "wet", "day", 60.0)]),
        t=2, alpha=0.05, rho=0.01, n_samples=N_SAMPLES, seed=1,
    )
    factor = -math.log(0.05) / 0.01
    assert r.factor == pytest.approx(factor)
    for combo, mass in r.credited.items():
        assert r.min_exposure_h[combo] == pytest.approx(factor * mass)


def test_short_log_is_inadequate(model: opmodel.OperationalModel) -> None:
    r = pwcc.assess(
        model, _runs([("rain", "wet", "day", 60.0)]),
        t=2, n_samples=N_SAMPLES, seed=1,
    )
    assert not r.is_adequate
    assert r.uncovered_mass == pytest.approx(1.0 - r.covered_mass, abs=1e-9)


def test_saturated_log_is_adequate(model: opmodel.OperationalModel) -> None:
    # Every value combination of the 3 features, each with 10^6 hours.
    rows = [
        (w, ro, ti, 3.6e9)
        for w in ("rain", "clear")
        for ro in ("wet", "dry")
        for ti in ("night", "day")
    ]
    r = pwcc.assess(model, _runs(rows), t=2, n_samples=N_SAMPLES, seed=1)
    assert r.is_adequate
    assert r.covered_mass == pytest.approx(1.0, abs=1e-9)
    assert r.summary()["n_insufficient"] == 0


def test_gaps_ranked_by_residual_mass(model: opmodel.OperationalModel) -> None:
    r = pwcc.assess(
        model, _runs([("rain", "wet", "day", 60.0)]),
        t=2, n_samples=N_SAMPLES, seed=1,
    )
    gaps = r.gaps()
    masses = [g["residual_mass"] for g in gaps]
    assert masses == sorted(masses, reverse=True)
    assert sum(masses) == pytest.approx(r.uncovered_mass, abs=1e-9)
    assert len(r.gaps(limit=2)) == 2


# ── CLI ─────────────────────────────────────────────────────────────────────


def test_parse_sweep() -> None:
    grid = _parse_sweep("eps=0.01:0.05:0.01")
    assert grid == pytest.approx([0.01, 0.02, 0.03, 0.04, 0.05])
    with pytest.raises(ValueError):
        _parse_sweep("rho=0.1:0.2:0.1")


def test_cli_end_to_end(
    profiling: pd.DataFrame, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "profiling.csv"
    profiling.to_csv(data, index=False)
    bn = tmp_path / "odd.bn"
    assert main(
        ["model", "fit", "--data", str(data), "-o", str(bn),
         "--restarts", "0", "--seed", "7"]
    ) == 0
    assert main(["model", "info", str(bn)]) == 0

    log = tmp_path / "runs.csv"
    profiling.head(3).to_csv(log, index=False)  # tiny log: inadequate
    out_json = tmp_path / "assess.json"
    ledger = tmp_path / "ledger.csv"
    code = main(
        ["assess", "--model", str(bn), "--log", str(log), "--t", "2",
         "--n-samples", str(N_SAMPLES), "--seed", "1",
         "--fail-if-inadequate", "--json", str(out_json),
         "--ledger", str(ledger), "--sweep", "eps=0.05:0.20:0.05"]
    )
    assert code == 2  # inadequate with --fail-if-inadequate
    payload = json.loads(out_json.read_text())
    assert payload["results"][0]["verdict"] == "INADEQUATE"
    assert ledger.exists() and "combination" in ledger.read_text().splitlines()[0]
    assert "verdict sensitivity" in capsys.readouterr().out

    assert main(
        ["gaps", "--model", str(bn), "--log", str(log), "--t", "2",
         "--n-samples", str(N_SAMPLES), "--seed", "1", "-n", "3"]
    ) == 0


def test_cli_per_t_epsilon_mismatch(
    profiling: pd.DataFrame, tmp_path: Path
) -> None:
    data = tmp_path / "p.csv"
    profiling.to_csv(data, index=False)
    bn = tmp_path / "odd.bn"
    main(["model", "fit", "--data", str(data), "-o", str(bn), "--restarts", "0"])
    log = tmp_path / "runs.csv"
    profiling.head(2).to_csv(log, index=False)
    code = main(
        ["assess", "--model", str(bn), "--log", str(log),
         "--t", "1", "2", "--epsilon", "0.05", "0.03", "0.01",
         "--n-samples", "500"]
    )
    assert code == 1  # 3 epsilons for 2 t values → input error


def test_cli_stub_commands_signal() -> None:
    assert main(["report"]) == 3
