"""odd-pilot loop: plan -> execute -> append -> assess orchestration."""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd
import pytest

from oddpilot import opmodel
from oddpilot.cli import main
from oddpilot.loop import parse_duration, run_loop

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEMPLATE = FIXTURES / "template.xosc"
N_SAMPLES = 2000


@pytest.fixture(scope="module")
def model() -> opmodel.OperationalModel:
    rng = random.Random(7)
    rows = []
    for _ in range(400):
        rain = rng.random() < 0.3
        wet = rng.random() < (0.9 if rain else 0.1)
        rows.append(
            {
                "feature_weather": "rain" if rain else "dry",
                "feature_road": "wetWithPuddles" if wet else "dry",
                "feature_time": "night" if rng.random() < 0.4 else "day",
            }
        )
    return opmodel.fit(pd.DataFrame(rows), seed=7, n_restarts=1)


def test_parse_duration() -> None:
    assert parse_duration("booting\nrun_duration=1800\n") == 1800.0
    assert parse_duration("run_duration: 90.5") == 90.5
    assert parse_duration("run_duration=10\nrun_duration=20") == 20.0
    assert parse_duration("no duration here") is None


def test_loop_reaches_adequacy(
    model: opmodel.OperationalModel, tmp_path: Path,
) -> None:
    # Executor reports 10^6 h per run: a handful of runs saturates every
    # combination's E_min, so the loop must certify and stop early.
    log = tmp_path / "runs.csv"
    outcome = run_loop(
        model, log, "echo run_duration=3600000000", TEMPLATE,
        t=1, epsilon=0.05, k=6, max_iter=4,
        batches_dir=tmp_path / "batches", pool_size=60, seed=3,
        lint=False, n_samples=N_SAMPLES, log_line=lambda _msg: None,
    )
    assert outcome.adequate
    assert outcome.iterations  # did not certify before executing anything
    assert outcome.iterations[-1].adequate
    # the run log holds one row per executed scenario with the reported hours
    df = pd.read_csv(log)
    assert len(df) == sum(i.executed for i in outcome.iterations)
    assert (df["run_duration"] == 3600000000.0).all()
    assert set(model.feature_cols) <= set(df.columns)
    # batches materialised on disk
    assert (tmp_path / "batches" / "001" / "plan.csv").exists()


def test_loop_stops_when_already_adequate(
    model: opmodel.OperationalModel, tmp_path: Path,
) -> None:
    # A pre-existing log with astronomic exposure on every value.
    rows = [
        {"feature_weather": w, "feature_road": r, "feature_time": t,
         "run_duration": 3.6e12}
        for w in ("rain", "dry") for r in ("wetWithPuddles", "dry")
        for t in ("night", "day")
    ]
    log = tmp_path / "runs.csv"
    pd.DataFrame(rows).to_csv(log, index=False)
    outcome = run_loop(
        model, log, "false", TEMPLATE,
        t=1, epsilon=0.05, max_iter=3, batches_dir=tmp_path / "b",
        n_samples=N_SAMPLES, seed=3, log_line=lambda _msg: None,
    )
    assert outcome.adequate
    assert outcome.iterations == []  # never needed the (failing) executor
    assert "already adequate" in outcome.stop_reason


def test_loop_aborts_when_executor_always_fails(
    model: opmodel.OperationalModel, tmp_path: Path,
) -> None:
    log = tmp_path / "runs.csv"
    outcome = run_loop(
        model, log, "false", TEMPLATE,
        t=1, epsilon=0.05, k=3, max_iter=5,
        batches_dir=tmp_path / "batches", pool_size=60, seed=3,
        lint=False, n_samples=N_SAMPLES, log_line=lambda _msg: None,
    )
    assert not outcome.adequate
    assert len(outcome.iterations) == 1  # aborted, not burned through max_iter
    assert outcome.iterations[0].failed == outcome.iterations[0].planned
    assert "every execution" in outcome.stop_reason
    assert not log.exists()  # failed runs earn no exposure


def test_cli_loop_until_adequate_exit_codes(
    model: opmodel.OperationalModel, tmp_path: Path,
) -> None:
    bn = tmp_path / "odd.bn"
    model.save(bn)
    log = tmp_path / "runs.csv"
    code = main(
        ["loop", "--model", str(bn), "--log", str(log),
         "--template", str(TEMPLATE), "--exec", "false {scenario}",
         "--t", "1", "-k", "2", "--max-iter", "2",
         "--batches-dir", str(tmp_path / "b"), "--pool", "40",
         "--seed", "3", "--no-lint", "--n-samples", str(N_SAMPLES),
         "--until-adequate"]
    )
    assert code == 2  # ended inadequate under --until-adequate

    code = main(
        ["loop", "--model", str(bn), "--log", str(log),
         "--template", str(TEMPLATE),
         "--exec", "echo run_duration=3600000000 # {scenario}",
         "--t", "1", "-k", "6", "--max-iter", "4",
         "--batches-dir", str(tmp_path / "b2"), "--pool", "60",
         "--seed", "3", "--no-lint", "--n-samples", str(N_SAMPLES),
         "--until-adequate"]
    )
    assert code == 0


def test_cli_loop_requires_placeholder(tmp_path: Path) -> None:
    code = main(
        ["loop", "--model", "x.bn", "--log", str(tmp_path / "r.csv"),
         "--template", str(TEMPLATE), "--exec", "true"]
    )
    assert code == 1
