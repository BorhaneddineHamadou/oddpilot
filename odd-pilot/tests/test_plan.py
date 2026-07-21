"""odd-pilot plan: gap-targeted generation with the physcheck gate."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd
import pytest

from oddpilot import opmodel
from oddpilot import plan as planner
from oddpilot.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEMPLATE = FIXTURES / "template.xosc"


@pytest.fixture(scope="module")
def profiling() -> pd.DataFrame:
    """Rain wets the road; values are OpenSCENARIO enum literals so the
    template instantiates into valid scenarios."""
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
                "run_duration": 60.0,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def model(profiling: pd.DataFrame) -> opmodel.OperationalModel:
    return opmodel.fit(profiling, seed=7, n_restarts=1)


def _gap(pairs: list[tuple[str, str]], mass: float) -> dict:
    return {"combo": tuple(pairs), "residual_mass": mass}


# ── allocation ──────────────────────────────────────────────────────────────


def test_allocate_proportional_and_exact() -> None:
    gaps = [_gap([("a", "1")], 0.6), _gap([("b", "1")], 0.3), _gap([("c", "1")], 0.1)]
    alloc = planner.allocate(gaps, 10)
    assert sum(n for _, n in alloc) == 10
    masses = [g["residual_mass"] for g, _ in alloc]
    assert masses == sorted(masses, reverse=True)
    counts = {g["combo"][0][0]: n for g, n in alloc}
    assert counts["a"] >= counts["b"] >= counts["c"] >= 1


def test_allocate_more_gaps_than_budget() -> None:
    gaps = [_gap([(f"g{i}", "1")], 1.0 / (i + 1)) for i in range(8)]
    alloc = planner.allocate(gaps, 3)
    assert sum(n for _, n in alloc) == 3
    assert [g["combo"][0][0] for g, _ in alloc] == ["g0", "g1", "g2"]


# ── conditional sampling + diversity ────────────────────────────────────────


def test_planned_scenarios_satisfy_their_target(
    model: opmodel.OperationalModel, tmp_path: Path
) -> None:
    combo = (("feature_weather", "rain"), ("feature_time", "night"))
    result = planner.plan(
        model, [_gap(list(combo), 0.5)], 2,
        out_dir=tmp_path, pool_size=60, seed=3,
    )
    assert len(result.planned) == 2
    for p in result.planned:
        assert p.assignment["feature_weather"] == "rain"
        assert p.assignment["feature_time"] == "night"
    # max–min diversity: all assignments distinct
    keys = [tuple(sorted(p.assignment.items())) for p in result.planned]
    assert len(set(keys)) == len(keys)
    assert (tmp_path / "plan.csv").exists()


def test_exhausted_domain_reported_unfillable(
    model: opmodel.OperationalModel, tmp_path: Path
) -> None:
    # With weather and time pinned, only feature_road varies: 2 distinct
    # scenarios exist. Asking for 4 yields 2 + an explicit shortfall note
    # (duplicates add exposure but are the campaign owner's call, not the
    # planner's).
    combo = (("feature_weather", "rain"), ("feature_time", "night"))
    result = planner.plan(
        model, [_gap(list(combo), 0.5)], 4,
        out_dir=tmp_path, pool_size=60, seed=3,
    )
    assert len(result.planned) == 2
    assert result.unfillable == [(combo, 0.5, 2)]


def test_rarity_prefers_tail_conditions(
    model: opmodel.OperationalModel, tmp_path: Path
) -> None:
    gap = [_gap([("feature_weather", "rain")], 0.5)]
    common = planner.plan(
        model, gap, 1, out_dir=tmp_path / "n", pool_size=80, seed=3
    ).planned[0]
    rare = planner.plan(
        model, gap, 1, out_dir=tmp_path / "r", pool_size=80, seed=3, rarity=True
    ).planned[0]
    # naturalistic first pick: rain -> wet (dominant); rarity: the tail branch
    assert common.assignment["feature_road"] == "wetWithPuddles"
    assert rare.assignment != common.assignment


# ── instantiation ───────────────────────────────────────────────────────────


def test_instantiate_substitutes_parameters(tmp_path: Path) -> None:
    out = tmp_path / "s.xosc"
    n = planner.instantiate(
        TEMPLATE,
        {"feature_road": "wetWithPuddles", "feature_time": "night",
         "feature_weather": "rain", "feature_unknown": "x"},
        out,
    )
    assert n == 3  # unknown feature has no slot
    text = out.read_text()
    assert 'name="road" parameterType="string" value="wetWithPuddles"' in text
    assert 'name="time" parameterType="string" value="night"' in text


# ── the physcheck gate ──────────────────────────────────────────────────────


def test_gate_discards_physics_violations(
    model: opmodel.OperationalModel, tmp_path: Path
) -> None:
    # frictionScaleFactor 1.05 in the template: wetWithPuddles -> FRI-001
    # error (wet road above dry-baseline friction), dry -> clean. A gap
    # conditioned on wet roads is therefore unfillable...
    result = planner.plan(
        model, [_gap([("feature_road", "wetWithPuddles")], 0.4)], 2,
        out_dir=tmp_path / "wet", template=TEMPLATE, pool_size=40, seed=3,
    )
    assert result.planned == []
    assert result.n_discarded > 0
    assert len(result.unfillable) == 1
    assert not list((tmp_path / "wet").glob("*.xosc"))  # discards deleted

    # ...while a dry-road gap instantiates and passes the gate.
    ok = planner.plan(
        model, [_gap([("feature_road", "dry")], 0.4)], 2,
        out_dir=tmp_path / "dry", template=TEMPLATE, pool_size=40, seed=3,
    )
    assert len(ok.planned) == 2
    assert all(p.file is not None and p.file.exists() for p in ok.planned)


def test_no_lint_keeps_violating_candidates(
    model: opmodel.OperationalModel, tmp_path: Path
) -> None:
    result = planner.plan(
        model, [_gap([("feature_road", "wetWithPuddles")], 0.4)], 2,
        out_dir=tmp_path, template=TEMPLATE, lint=False, pool_size=40, seed=3,
    )
    assert len(result.planned) == 2
    assert result.n_discarded == 0


# ── adequacy JSON adapter ───────────────────────────────────────────────────


def test_gaps_from_json_picks_first_inadequate() -> None:
    payload = {
        "results": [
            {"t": 2, "is_adequate": True, "gaps": []},
            {
                "t": 3,
                "is_adequate": False,
                "gaps": [
                    {"combo": [["feature_weather", "rain"]], "residual_mass": 0.2}
                ],
            },
        ]
    }
    gaps = planner.gaps_from_json(payload)
    assert gaps == [
        {"combo": (("feature_weather", "rain"),), "residual_mass": 0.2}
    ]
    with pytest.raises(ValueError, match="no t=4"):
        planner.gaps_from_json(payload, t=4)


# ── CLI end-to-end: assess --json → plan -a ─────────────────────────────────


def test_cli_assess_then_plan(
    profiling: pd.DataFrame, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "profiling.csv"
    profiling.to_csv(data, index=False)
    bn = tmp_path / "odd.bn"
    assert main(
        ["model", "fit", "--data", str(data), "-o", str(bn),
         "--restarts", "0", "--seed", "7"]
    ) == 0
    log = tmp_path / "runs.csv"
    profiling.head(3).to_csv(log, index=False)
    adequacy = tmp_path / "adequacy.json"
    main(
        ["assess", "--model", str(bn), "--log", str(log), "--t", "2",
         "--n-samples", "4000", "--seed", "1", "--json", str(adequacy)]
    )
    payload = json.loads(adequacy.read_text())
    assert payload["results"][0]["gaps"]  # machine-readable gaps present

    out = tmp_path / "batch"
    assert main(
        ["plan", "--model", str(bn), "-a", str(adequacy), "-k", "5",
         "-o", str(out), "--template", str(TEMPLATE),
         "--pool", "40", "--seed", "3"]
    ) == 0
    assert (out / "plan.csv").exists()
    plan_df = pd.read_csv(out / "plan.csv")
    assert 0 < len(plan_df) <= 5
    for f in plan_df["file"].dropna():
        assert Path(f).exists()
    assert "planned" in capsys.readouterr().out
