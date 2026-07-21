"""Gap-targeted generation (design brief §Component 4).

For each insufficient combination c, highest residual mass first:
  1. condition the operational BN and draw a candidate pool from P(X | c) —
     candidates satisfy the target condition while inheriting naturalistic
     dependencies;
  2. lint every candidate with physcheck (L0–L3) after instantiating it into
     the user's OpenSCENARIO template — rarity-tail sampling stretches soft
     dependencies, so linting inside generation is mandatory, not cosmetic;
  3. select by max–min diversity in normalised parameter space,
     s* = argmax_{s in pool} min_{s' in selected} d(s, s'), with candidate
     ordering by pool frequency (naturalistic) or inverted (--rarity);
  4. instantiate via the template's ParameterDeclarations: a feature column
     ``feature_weather`` fills the parameter named ``weather`` (or
     ``feature_weather``).

Violating candidates are discarded and replaced by the next diverse valid
one; a gap whose entire pool violates is reported as unfillable, never
silently dropped.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from oddpilot.assess import AssessmentResult, Combo
from oddpilot.opmodel import OperationalModel

__all__ = ["Planned", "PlanResult", "allocate", "plan"]

#: One concrete scenario: feature column -> value.
Assignment = tuple[tuple[str, str], ...]


@dataclass
class Planned:
    scenario_id: str
    target: Combo
    residual_mass: float
    assignment: dict[str, str]
    file: Path | None = None
    discarded_before: int = 0


@dataclass
class PlanResult:
    planned: list[Planned] = field(default_factory=list)
    #: (combo, residual_mass, allocated) for gaps whose pool had no valid candidate left.
    unfillable: list[tuple[Combo, float, int]] = field(default_factory=list)
    n_discarded: int = 0

    def frame(self) -> pd.DataFrame:
        rows = []
        for p in self.planned:
            rows.append(
                {
                    "scenario_id": p.scenario_id,
                    "target_combination": " & ".join(f"{k}={v}" for k, v in p.target),
                    "residual_mass": p.residual_mass,
                    **p.assignment,
                    "file": str(p.file) if p.file else "",
                }
            )
        return pd.DataFrame(rows)


def allocate(gaps: list[dict[str, Any]], k: int) -> list[tuple[dict[str, Any], int]]:
    """Distribute a budget of k scenarios over gaps, proportional to residual
    mass, largest first, at least one each while budget remains."""
    if k <= 0 or not gaps:
        return []
    gaps = sorted(gaps, key=lambda g: float(g["residual_mass"]), reverse=True)
    gaps = gaps[:k]  # more gaps than budget: top-k by mass get one each
    total = sum(float(g["residual_mass"]) for g in gaps) or 1.0
    raw = [k * float(g["residual_mass"]) / total for g in gaps]
    alloc = [max(1, int(r)) for r in raw]
    # Trim overshoot from the smallest gaps, grow undershoot on the largest
    # fractional remainders — deterministic and budget-exact.
    while sum(alloc) > k:
        for i in range(len(alloc) - 1, -1, -1):
            if alloc[i] > 1:
                alloc[i] -= 1
                break
        else:
            break
    remainders = sorted(
        range(len(alloc)), key=lambda i: raw[i] - int(raw[i]), reverse=True
    )
    ri = 0
    while sum(alloc) < k and remainders:
        alloc[remainders[ri % len(remainders)]] += 1
        ri += 1
    return list(zip(gaps, alloc, strict=True))


def _sample_pool(
    model: OperationalModel, combo: Combo, pool_size: int, seed: int | None
) -> list[Assignment]:
    evidence = dict(combo)
    samples = model.bn.simulate(
        n_samples=pool_size, evidence=evidence, seed=seed, show_progress=False
    )
    cols = [c for c in model.feature_cols if c in samples.columns]
    samples = samples[cols].astype(str)
    out: list[Assignment] = []
    for _, row in samples.iterrows():
        assignment = dict(zip(cols, (str(v) for v in row), strict=True))
        assignment.update(evidence)  # evidence columns may be absent from sample
        out.append(tuple(sorted(assignment.items())))
    return out


def _distance(a: Assignment, b: Assignment) -> float:
    """Normalised Hamming distance over the shared feature space."""
    if not a:
        return 0.0
    diff = sum(1 for (_, va), (_, vb) in zip(a, b, strict=True) if va != vb)
    return diff / len(a)


def _ordered_candidates(
    pool: list[Assignment], rarity: bool
) -> list[tuple[Assignment, int]]:
    """Unique candidates ordered by pool frequency: most frequent first
    (naturalistic), or least frequent first in rarity mode. Lexicographic
    tie-break keeps the ordering deterministic."""
    freq = Counter(pool)
    return sorted(
        freq.items(), key=lambda kv: ((kv[1] if rarity else -kv[1]), kv[0])
    )


def _pick(
    candidates: list[tuple[Assignment, int]],
    taken: set[Assignment],
    selected: list[Assignment],
) -> Assignment | None:
    """Max–min diversity pick: the candidate farthest from everything already
    selected; candidate order (frequency/rarity) breaks ties."""
    best: Assignment | None = None
    best_score = -1.0
    for cand, _ in candidates:
        if cand in taken:
            continue
        score = (
            min(_distance(cand, s) for s in selected) if selected else 1.0
        )
        if score > best_score:
            best, best_score = cand, score
    return best


# ── template instantiation + lint gate ──────────────────────────────────────


def instantiate(
    template: Path, assignment: dict[str, str], out_path: Path
) -> int:
    """Write the template with its ParameterDeclaration defaults replaced by
    the assignment. ``feature_x`` fills the parameter named ``x`` or
    ``feature_x``. Returns the number of substituted parameters."""
    tree = ET.parse(template)
    by_name = {}
    for feature, value in assignment.items():
        by_name[feature] = value
        if feature.startswith("feature_"):
            by_name[feature[len("feature_"):]] = value
    substituted = 0
    for decl in tree.getroot().iter("ParameterDeclaration"):
        name = decl.get("name", "")
        if name in by_name:
            decl.set("value", by_name[name])
            substituted += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="unicode", xml_declaration=True)
    return substituted


class _LintGate:
    """physcheck L0–L3 over instantiated candidates; the map (if any) is
    resolved relative to the TEMPLATE, since instantiated copies live in the
    batch directory."""

    def __init__(self, template: Path) -> None:
        from physcheck.engine.catalog import load_default_packs
        from physcheck.ir.osc_parser import parse_file
        from physcheck.xodr import load_map

        self._parse_file = parse_file
        rules, errors = load_default_packs()
        if errors:
            raise ValueError(f"physcheck rule packs failed to load: {errors}")
        self._rules = rules
        self._xmap = None
        scenario = parse_file(template)
        logic = scenario.road_network_logic_file
        if logic and (template.parent / logic).is_file():
            self._xmap = load_map(template.parent / logic)

    def errors(self, path: Path) -> list[str]:
        from physcheck.engine.engine import lint_scenario

        result = lint_scenario(
            self._parse_file(path),
            self._rules,
            {"L0", "L1", "L2", "L3"},
            xodr_map=self._xmap,
        )
        return [
            f"{f.rule_id}: {f.title}"
            for f in result.findings
            if f.severity == "error"
        ]


# ── the planner ─────────────────────────────────────────────────────────────


def plan(
    model: OperationalModel,
    gaps: list[dict[str, Any]],
    k: int,
    *,
    out_dir: Path,
    template: Path | None = None,
    lint: bool = True,
    rarity: bool = False,
    pool_size: int = 100,
    seed: int | None = None,
) -> PlanResult:
    """Generate the next batch: k scenarios closing the measured gaps."""
    result = PlanResult()
    gate = _LintGate(template) if (template is not None and lint) else None
    selected: list[Assignment] = []
    taken: set[Assignment] = set()
    counter = 0

    for gap, quota in allocate(gaps, k):
        combo: Combo = tuple(gap["combo"])
        mass = float(gap["residual_mass"])
        pool = _sample_pool(model, combo, pool_size, seed)
        candidates = _ordered_candidates(pool, rarity)
        produced = 0
        discarded = 0
        while produced < quota:
            cand = _pick(candidates, taken, selected)
            if cand is None:
                result.unfillable.append((combo, mass, quota - produced))
                break
            taken.add(cand)
            counter += 1
            scenario_id = f"planned_{counter:04d}"
            assignment = dict(cand)
            file: Path | None = None
            if template is not None:
                file = out_dir / f"{scenario_id}.xosc"
                instantiate(template, assignment, file)
                if gate is not None:
                    errs = gate.errors(file)
                    if errs:
                        file.unlink()
                        counter -= 1
                        discarded += 1
                        result.n_discarded += 1
                        continue
            selected.append(cand)
            result.planned.append(
                Planned(
                    scenario_id=scenario_id,
                    target=combo,
                    residual_mass=mass,
                    assignment=assignment,
                    file=file,
                    discarded_before=discarded,
                )
            )
            produced += 1
    out_dir.mkdir(parents=True, exist_ok=True)
    result.frame().to_csv(out_dir / "plan.csv", index=False)
    return result


def gaps_from_assessment(result: AssessmentResult) -> list[dict[str, Any]]:
    """Adapter: AssessmentResult.gaps() rows already carry combo + mass."""
    return result.gaps()


def gaps_from_json(payload: dict[str, Any], t: int | None = None) -> list[dict[str, Any]]:
    """Read gaps from an ``assess --json`` file; picks the requested t, else
    the first inadequate t, else the highest t present."""
    entries = payload.get("results", [])
    if not entries:
        raise ValueError("adequacy JSON contains no results")
    chosen = None
    if t is not None:
        chosen = next((e for e in entries if e.get("t") == t), None)
        if chosen is None:
            raise ValueError(f"no t={t} entry in adequacy JSON")
    else:
        chosen = next(
            (e for e in entries if not e.get("is_adequate", True)), entries[-1]
        )
    gaps = chosen.get("gaps")
    if gaps is None:
        raise ValueError(
            "adequacy JSON has no 'gaps' — re-run assess with --json using "
            "odd-pilot >= 0.2"
        )
    return [
        {
            "combo": tuple((str(f), str(v)) for f, v in g["combo"]),
            "residual_mass": float(g["residual_mass"]),
        }
        for g in gaps
    ]
