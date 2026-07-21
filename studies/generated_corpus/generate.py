#!/usr/bin/env python3
"""Generated-corpus study: five generation strategies, one shared template.

Strategies (all seeded, all writing corpora/<name>/NNN.xosc):
  random        uniform independent sampling per attribute, each value
                individually schema-legal — the naive fuzzer.
  pairwise      greedy 2-way covering array over discretised levels — classic
                combinatorial testing (values still chosen independently).
  search        (mu+lambda) evolutionary search maximising a criticality
                proxy (poor visibility, low friction, high speed, darkness,
                heavy precipitation) with NO physics constraints — the
                adversarial-search archetype. Corpus = top-N of all evaluated.
  opmodel       forward samples of a Bayesian network fitted on coherent
                simulated operation (odd-pilot `model fit` + simulate) —
                dependency-aware generation WITHOUT the lint gate.
  opmodel_gated the same samples filtered through the physcheck L0–L3 gate —
                what odd-pilot `plan` actually emits.

Every strategy fills the SAME ParameterDeclaration slots of template.xosc, so
the only experimental variable is how values are chosen. `fog_present=False`
removes the <Fog> element after instantiation (a generator that omits fog),
otherwise the sampled visualRange stands.

Usage:
    python3 generate.py --map Town04.xodr [--n 500] [--seed 7] [--out corpora]
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
import xml.etree.ElementTree as ET
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.xosc"

# ── attribute space (all values individually schema-legal) ──────────────────

CONT: dict[str, tuple[float, float]] = {
    "fog_visual_range": (10, 50_000),
    "precip_intensity": (0, 40),
    "temperature": (233, 323),
    "pressure": (85_000, 110_000),
    "sun_azimuth": (0, 6.283),
    "sun_elevation": (-1.4, 1.4),
    "sun_illuminance": (0, 110_000),
    "wind_speed": (0, 35),
    "friction_scale": (0.1, 1.25),
    "max_speed": (15, 90),
    "max_accel": (1, 11),
    "max_decel": (3, 11.5),
    "mass": (700, 3500),
    "target_speed": (0, 45),
    "lane_change_time": (1.2, 8),
    "ped_speed": (0.5, 12.0),
    "spawn_s": (5, 240),
}
ENUM: dict[str, list[str]] = {
    "precip_type": ["dry", "rain", "snow"],
    "cloud_cover": ["zeroOktas", "twoOktas", "fourOktas", "sixOktas", "eightOktas"],
    "wetness": ["dry", "moist", "wetWithPuddles", "lowFlooded", "highFlooded"],
}

PAIRWISE_LEVELS: dict[str, list] = {
    "fog_present": [True, False],
    "fog_visual_range": [50, 500, 5000, 20000],
    "precip_type": ["dry", "rain", "snow"],
    "precip_intensity": [0, 2, 15, 35],
    "cloud_cover": ["zeroOktas", "fourOktas", "eightOktas"],
    "temperature": [243, 268, 288, 313],
    "pressure": [87_000, 101_000, 108_000],
    "sun_azimuth": [0.5, 2.4, 4.2],
    "sun_elevation": [-1.2, -0.3, 0.35, 1.2],
    "sun_illuminance": [50, 5000, 40_000, 100_000],
    "wind_speed": [0, 8, 20, 33],
    "wetness": ["dry", "moist", "wetWithPuddles", "highFlooded"],
    "friction_scale": [0.15, 0.5, 0.85, 1.2],
    "max_speed": [20, 45, 85],
    "max_accel": [2, 6, 10.5],
    "max_decel": [4, 8, 11],
    "mass": [900, 1600, 3200],
    "target_speed": [5, 18, 32, 44],
    "lane_change_time": [1.3, 2.5, 6],
    "ped_speed": [1.2, 4, 9, 11.8],
    "spawn_s": [10, 80, 150, 235],
}

_WETNESS_RANK = {"dry": 0, "moist": 0.25, "wetWithPuddles": 0.5,
                 "lowFlooded": 0.75, "highFlooded": 1.0}


# ── strategy: random ────────────────────────────────────────────────────────


def sample_random(rng: random.Random) -> dict:
    s = {name: rng.uniform(lo, hi) for name, (lo, hi) in CONT.items()}
    s |= {name: rng.choice(vals) for name, vals in ENUM.items()}
    s["fog_present"] = rng.random() < 0.5
    return s


# ── strategy: pairwise (greedy covering array) ──────────────────────────────


def pairwise_rows(rng: random.Random) -> list[dict]:
    attrs = list(PAIRWISE_LEVELS)
    uncovered: set[tuple] = {
        (a, va, b, vb)
        for a, b in combinations(attrs, 2)
        for va in PAIRWISE_LEVELS[a]
        for vb in PAIRWISE_LEVELS[b]
    }
    rows: list[dict] = []
    while uncovered:
        # Seed the row with one still-uncovered pair (guarantees progress),
        # then fill the remaining attributes greedily.
        seed_a, seed_va, seed_b, seed_vb = next(iter(uncovered))
        row: dict = {seed_a: seed_va, seed_b: seed_vb}
        for attr in rng.sample(attrs, len(attrs)):
            if attr in row:
                continue
            best_val, best_gain = None, -1
            for val in PAIRWISE_LEVELS[attr]:
                gain = sum(
                    1
                    for other, oval in row.items()
                    if (attr, val, other, oval) in uncovered
                    or (other, oval, attr, val) in uncovered
                )
                if gain > best_gain:
                    best_val, best_gain = val, gain
            row[attr] = best_val
        for a, b in combinations(sorted(row), 2):
            uncovered.discard((a, row[a], b, row[b]))
            uncovered.discard((b, row[b], a, row[a]))
        rows.append(row)
    return rows


# ── strategy: adversarial-style search ──────────────────────────────────────


def criticality(s: dict) -> float:
    fog_term = (1 - s["fog_visual_range"] / 50_000) if s["fog_present"] else 0.0
    return (
        2.0 * fog_term
        + s["precip_intensity"] / 40
        + (1.25 - s["friction_scale"]) / 1.15
        + s["target_speed"] / 45
        + (1 - s["sun_illuminance"] / 110_000)
        + s["wind_speed"] / 35
        + _WETNESS_RANK[s["wetness"]]
    )


def _mutate(s: dict, rng: random.Random) -> dict:
    out = dict(s)
    for name, (lo, hi) in CONT.items():
        if rng.random() < 0.3:
            out[name] = min(hi, max(lo, rng.gauss(out[name], 0.1 * (hi - lo))))
    for name, vals in ENUM.items():
        if rng.random() < 0.3:
            out[name] = rng.choice(vals)
    if rng.random() < 0.15:
        out["fog_present"] = not out["fog_present"]
    return out


def search_corpus(rng: random.Random, n_evals: int, top: int) -> list[dict]:
    pop = [sample_random(rng) for _ in range(20)]
    archive = list(pop)
    while len(archive) < n_evals:
        pop.sort(key=criticality, reverse=True)
        parents = pop[:10]
        children = [_mutate(rng.choice(parents), rng) for _ in range(20)]
        archive.extend(children)
        pop = parents + children
    seen: set[tuple] = set()
    unique = []
    for s in sorted(archive, key=criticality, reverse=True):
        key = tuple(sorted((k, round(v, 4) if isinstance(v, float) else v)
                           for k, v in s.items()))
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique[:top]


# ── strategy: operational model (coherent world -> BN -> samples) ───────────

#: regime name -> weight
_REGIMES = {
    "clear_day": 0.33, "cloudy_day": 0.20, "rain_day": 0.12, "heavy_rain": 0.05,
    "fog_morning": 0.08, "clear_night": 0.12, "rain_night": 0.05,
    "snow_day": 0.05,
}


def _real_sun(rng: random.Random, night: bool) -> tuple[float, float]:
    """A genuinely occurring (elevation, azimuth) pair: sampled from the
    ephemeris at the map's declared geodetic anchor (Town04: 0°N 0°E), so the
    pair always lies on the solar locus — the way a real sky behaves."""
    import datetime as _dt

    from physcheck.ephemeris import solar_position_deg

    for _ in range(200):
        when = _dt.datetime(2026, 1, 1) + _dt.timedelta(
            days=rng.uniform(0, 365), hours=rng.uniform(0, 24)
        )
        el_deg, az_deg = solar_position_deg(when, 0.0, 0.0)
        if (el_deg < -9.0) if night else (el_deg > 9.0):
            return math.radians(el_deg), math.radians(az_deg)
    raise RuntimeError("no matching sun found (unreachable)")


def coherent_world(rng: random.Random) -> dict:
    """One physically coherent operation profile (what real driving offers)."""
    regime = rng.choices(list(_REGIMES), weights=list(_REGIMES.values()))[0]
    night = "night" in regime
    s: dict = {}
    s["sun_elevation"], s["sun_azimuth"] = _real_sun(rng, night)
    if "rain" in regime:
        heavy = regime == "heavy_rain"
        s["precip_type"] = "rain"
        s["precip_intensity"] = rng.uniform(8, 30) if heavy else rng.uniform(0.8, 8)
        s["cloud_cover"] = "eightOktas"
        s["wetness"] = rng.choice(
            ["lowFlooded", "highFlooded"] if heavy else ["moist", "wetWithPuddles"]
        )
        s["temperature"] = rng.uniform(276, 296)
    elif regime == "snow_day":
        s["precip_type"] = "snow"
        s["precip_intensity"] = rng.uniform(0.5, 6)
        s["cloud_cover"] = rng.choice(["sixOktas", "eightOktas"])
        s["wetness"] = "moist"
        s["temperature"] = rng.uniform(258, 272)
    else:
        s["precip_type"] = "dry"
        s["precip_intensity"] = 0.0
        s["cloud_cover"] = (
            rng.choice(["fourOktas", "sixOktas", "eightOktas"])
            if regime == "cloudy_day" else rng.choice(["zeroOktas", "twoOktas"])
        )
        s["wetness"] = "dry"
        s["temperature"] = rng.uniform(263, 305)
    s["fog_present"] = regime == "fog_morning"
    s["fog_visual_range"] = rng.uniform(120, 1500) if s["fog_present"] else 0.0
    _MU = {"dry": (0.9, 1.15), "moist": (0.6, 0.85), "wetWithPuddles": (0.45, 0.7),
           "lowFlooded": (0.35, 0.6), "highFlooded": (0.25, 0.45)}
    if s["precip_type"] == "snow":
        s["friction_scale"] = rng.uniform(0.2, 0.4)
    else:
        s["friction_scale"] = rng.uniform(*_MU[s["wetness"]])
    cloud_factor = {"zeroOktas": 1.0, "twoOktas": 0.9, "fourOktas": 0.7,
                    "sixOktas": 0.45, "eightOktas": 0.25}[s["cloud_cover"]]
    fog_factor = 0.3 if s["fog_present"] else 1.0
    base = max(0.0, math.sin(s["sun_elevation"]))
    s["sun_illuminance"] = base * 105_000 * cloud_factor * fog_factor * rng.uniform(0.8, 1.0)
    s["pressure"] = rng.uniform(99_000, 103_500)
    s["wind_speed"] = rng.uniform(0, 14) if "rain" not in regime else rng.uniform(2, 20)
    mu_ceiling = {"dry": 1.2, "moist": 1.0, "wetWithPuddles": 0.9,
                  "lowFlooded": 0.7, "highFlooded": 0.4}[s["wetness"]]
    if s["precip_type"] == "snow":
        mu_ceiling = 0.5
    # Braking/acceleration capability bounded by the DECLARED surface friction
    # (FRI-013/023 semantics), not the wetness-class ceiling.
    tire_limit = s["friction_scale"] * 0.9 * 9.81 * 1.35
    s["max_decel"] = max(2.0, rng.uniform(0.45, 0.85) * tire_limit)
    s["max_accel"] = max(1.2, rng.uniform(0.2, 0.45) * tire_limit)
    s["max_speed"] = rng.uniform(35, 62)
    s["mass"] = rng.uniform(1100, 2400)
    v_surface = 0.9 * math.sqrt(mu_ceiling * 9.81 * 54 * 1.2)
    s["target_speed"] = rng.uniform(3, min(22.0, v_surface))
    s["lane_change_time"] = rng.uniform(2.5, 6.0)
    s["ped_speed"] = rng.uniform(0.6, 2.2)
    s["spawn_s"] = rng.uniform(5, 240)
    return s


#: attribute -> ordered (label, representative value) bins for the BN.
def _bins(lo: float, hi: float, n: int) -> list[tuple[str, float]]:
    step = (hi - lo) / n
    return [(f"b{i}", lo + (i + 0.5) * step) for i in range(n)]


_BIN_SPECS: dict[str, list[tuple[str, float]]] = {
    "fog_visual_range": [("none", 0.0), ("dense", 250.0), ("haze", 1000.0)],
    "precip_intensity": [("none", 0.0), ("light", 3.0), ("mod", 12.0), ("heavy", 24.0)],
    "temperature": _bins(255, 305, 5),
    "pressure": _bins(99_000, 103_500, 3),
    "sun_illuminance": [("night", 5.0), ("dim", 8000.0), ("mid", 30_000.0),
                        ("bright", 65_000.0), ("full", 95_000.0)],
    "wind_speed": _bins(0, 20, 4),
    "friction_scale": _bins(0.2, 1.15, 6),
    "max_speed": _bins(35, 62, 3),
    "max_accel": _bins(2.0, 5.5, 3),
    "max_decel": _bins(2.0, 11.0, 5),
    "mass": _bins(1100, 2400, 3),
    "target_speed": _bins(3, 22, 5),
    "lane_change_time": _bins(2.5, 6.0, 3),
    "ped_speed": _bins(0.6, 2.2, 3),
    "spawn_s": _bins(5, 240, 5),
}


def _to_label(name: str, value: float) -> str:
    if name == "fog_visual_range" and value <= 0:
        return "none"
    spec = _BIN_SPECS[name]
    best = min(spec, key=lambda lb: abs(lb[1] - value))
    return best[0]


def _from_label(name: str, label: str) -> float:
    for lb, rep in _BIN_SPECS[name]:
        if lb == label:
            return rep
    raise KeyError(f"{name}: unknown bin {label!r}")


def _sun_label(el_rad: float, az_rad: float) -> str:
    """Composite sun category: the elevation↔azimuth coupling is a curve no
    pair of independent discrete features can represent, so the sun is ONE
    feature whose representative values are real ephemeris pairs."""
    el = math.degrees(el_rad)
    band = "night" if el < 0 else "low" if el < 25 else "mid" if el < 50 else "high"
    side = "E" if math.degrees(az_rad) % 360 < 180 else "W"
    return f"{band}_{side}"


def opmodel_corpus(rng: random.Random, n: int, seed: int) -> list[dict]:
    import pandas as pd

    from oddpilot import opmodel

    rows = []
    sun_repr: dict[str, tuple[float, float]] = {}
    for _ in range(2000):
        w = coherent_world(rng)
        row = {f"feature_{k}": _to_label(k, w[k]) for k in _BIN_SPECS}
        sun = _sun_label(w["sun_elevation"], w["sun_azimuth"])
        sun_repr.setdefault(sun, (w["sun_elevation"], w["sun_azimuth"]))
        row["feature_sun"] = sun
        for enum_attr in ("precip_type", "cloud_cover", "wetness"):
            row[f"feature_{enum_attr}"] = w[enum_attr]
        rows.append(row)
    model = opmodel.fit(pd.DataFrame(rows), seed=seed, n_restarts=1, max_indegree=3)
    samples = model.bn.simulate(n_samples=n, seed=seed, show_progress=False)
    out = []
    for _, sample in samples.iterrows():
        s: dict = {}
        for k in _BIN_SPECS:
            s[k] = _from_label(k, str(sample[f"feature_{k}"]))
        s["sun_elevation"], s["sun_azimuth"] = sun_repr[str(sample["feature_sun"])]
        for enum_attr in ("precip_type", "cloud_cover", "wetness"):
            s[enum_attr] = str(sample[f"feature_{enum_attr}"])
        s["fog_present"] = s["fog_visual_range"] > 0
        if not s["fog_present"]:
            s["fog_visual_range"] = 10_000  # removed from the file anyway
        out.append(s)
    return out


# ── instantiation ───────────────────────────────────────────────────────────


def write_scenario(sample: dict, out_path: Path) -> None:
    from oddpilot.plan import instantiate

    values = {
        k: (f"{v:.4f}" if isinstance(v, float) else str(v))
        for k, v in sample.items()
        if k != "fog_present"
    }
    instantiate(TEMPLATE, values, out_path)
    if not sample.get("fog_present", True):
        tree = ET.parse(out_path)
        for weather in tree.getroot().iter("Weather"):
            fog = weather.find("Fog")
            if fog is not None:
                weather.remove(fog)
        tree.write(out_path, encoding="unicode", xml_declaration=True)


def emit(corpus: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for s in corpus for k in s})
    with open(out_dir / "params.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["scenario", *keys])
        writer.writeheader()
        for i, sample in enumerate(corpus):
            name = f"{i:04d}.xosc"
            write_scenario(sample, out_dir / name)
            writer.writerow({"scenario": name, **sample})


# ── the gate (for opmodel_gated) ────────────────────────────────────────────


class Gate:
    def __init__(self, map_path: Path) -> None:
        from physcheck.engine.catalog import load_default_packs
        from physcheck.xodr import load_map

        rules, errors = load_default_packs()
        assert not errors, errors
        self.rules = rules
        self.xmap = load_map(map_path)

    def ok(self, path: Path) -> bool:
        from physcheck.engine.engine import lint_scenario
        from physcheck.ir.osc_parser import parse_file

        result = lint_scenario(
            parse_file(path), self.rules, {"L0", "L1", "L2", "L3"},
            xodr_map=self.xmap,
        )
        return not any(f.severity == "error" for f in result.findings)


# ── main ────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", type=Path, required=True, help="Town04.xodr")
    ap.add_argument("--out", type=Path, default=HERE / "corpora")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    print(f"[random] {args.n} scenarios")
    emit([sample_random(rng) for _ in range(args.n)], args.out / "random")

    rng = random.Random(args.seed)
    rows = pairwise_rows(rng)
    print(f"[pairwise] covering array of {len(rows)} scenarios")
    emit(rows, args.out / "pairwise")

    rng = random.Random(args.seed)
    top = search_corpus(rng, n_evals=args.n, top=200)
    print(f"[search] top {len(top)} of {args.n} evaluated")
    emit(top, args.out / "search")

    rng = random.Random(args.seed)
    bn_samples = opmodel_corpus(rng, args.n, args.seed)
    print(f"[opmodel] {len(bn_samples)} BN samples")
    emit(bn_samples, args.out / "opmodel")

    gate = Gate(args.map)
    gated_dir = args.out / "opmodel_gated"
    gated_dir.mkdir(parents=True, exist_ok=True)
    kept = 0
    for path in sorted((args.out / "opmodel").glob("*.xosc")):
        target = gated_dir / path.name
        target.write_bytes(path.read_bytes())
        if gate.ok(target):
            kept += 1
        else:
            target.unlink()
    print(f"[opmodel_gated] {kept}/{len(bn_samples)} pass the physcheck gate "
          f"(yield {kept / len(bn_samples):.0%})")


if __name__ == "__main__":
    sys.exit(main())
