# Generated-corpus study: do standard scenario generators respect physics?

The motivating claim of the odd-pilot design brief: standard scenario
generators — random, combinatorial, adversarial search — produce scenarios
that violate basic physics in the large majority of cases (e.g. dense fog
with unlimited visibility, rain on a bone-dry road), so failures found under
them are simulation artifacts, not deployment risks. This study reproduces
that finding with physcheck as the auditor, and quantifies what
dependency-aware generation (odd-pilot's operational model, with and without
the lint gate) changes.

## Design

**One template, five value-selection strategies.** All strategies fill the
same 21 `ParameterDeclaration` slots of `template.xosc` (CARLA Town04 road
38: one ego with performance/speed/lane-change, one pedestrian, a full
weather/road environment), so the *only* experimental variable is how
parameter values are chosen:

| Strategy | Archetype | Values chosen by |
|---|---|---|
| `random` | naive fuzzer | uniform, independent per attribute |
| `pairwise` | combinatorial testing | greedy 2-way covering array over discretised levels |
| `search` | adversarial / criticality search | (µ+λ) evolution maximising a criticality proxy (poor visibility, low friction, high speed, darkness, heavy precipitation); corpus = top-200 of 500 evaluated |
| `opmodel` | odd-pilot without the gate | forward samples of a BN fitted on 2,000 coherent operation profiles |
| `opmodel_gated` | odd-pilot `plan` | the same samples, filtered by the physcheck L0–L3 gate |

**Crucially, every sampled value is individually schema-legal** (inside the
L0 range checks: temperature within [233, 323] K, sun elevation within
±1.4 rad, friction in [0.1, 1.25], pedestrian ≤ 12 m/s, lane change
≥ 1.2 s, …). Nothing is nonsense on its own; invalidity can only arise from
*combinations* — rain on a dry road, a sun that outshines its own elevation,
snowfall in summer heat, highway speed into a 54 m bend on a flooded
surface. That is precisely the class of defect per-attribute range checking
cannot see and physcheck's L1–L3 cross-checks target.

**Audit:** `physcheck lint <corpus> --map Town04.xodr --layers L0,L1,L2,L3`.
A scenario is *physics-invalid* when it carries at least one error-severity
finding. (Warnings are recorded but not counted.)

## Reproduce

```bash
# Town04.xodr from the CARLA 0.9.16 distribution
#   (CarlaUE4/Content/Carla/Maps/OpenDrive/Town04.xodr)
python3 generate.py --map Town04.xodr --n 500 --seed 7
python3 analyze.py  --map Town04.xodr
```

Requires `pip install -e physcheck/ -e odd-pilot/` from the monorepo root
(the opmodel strategies use odd-pilot's `model fit`; instantiation reuses
`oddpilot.plan.instantiate`).

## Results

The audit (`results/table.md`, physcheck 0.3.0, seed 7):

| Strategy | Scenarios | Physics-invalid | % invalid | Error files by layer | Top violated rules |
|---|---|---|---|---|---|
| random | 500 | 493 | **98.6 %** | L1: 492, L2: 221, L3: 60 | SOL-005 (247), FRI-013 (222), GEO-001 (221), PRE-001 (176), FRI-023 (172) |
| pairwise | 41 | 41 | **100 %** | L1: 40, L2: 12, L3: 23 | FRI-013 (25), FRI-023 (21), DYN-002 (19), SOL-005 (13), PRE-001 (13) |
| search | 200 | 200 | **100 %** | L1: 200, L2: 151, L3: 162 | FRI-013 (195), DYN-002 (162), GEO-001 (151), SOL-005 (136), FRI-023 (90) |
| opmodel (ungated) | 500 | 6 | **1.2 %** | L1: 4, L3: 2 | PRE-001 (2), DYN-001 (2), FRI-016 (1), PRE-012 (1) |
| opmodel + gate (`plan`) | 494 | 0 | **0 %** | — | — |

Gate yield on the operational-model samples: 494/500 (99 %).

## Reading of the results

1. **The headline claim reproduces.** With every value individually
   schema-legal, naive random sampling yields **98.6 %** physically
   impossible scenarios, and combinatorial and adversarial-search suites
   reach **100 %**. The brief's 93–94 % figure is, if anything,
   conservative for parameter spaces this size.
2. **Adversarial search is the worst offender in kind, not just degree.**
   Its criticality objective actively drives into impossibility: it has by
   far the highest L2/L3 violation share (151/200 impossible sun
   geometries, 162/200 kinematically impossible lane changes) — "critical"
   conditions that cannot occur, so every failure found under them is a
   simulation artifact.
3. **Dependency-aware generation removes ~99 % of the invalidity, not all
   of it.** The BN-based operational model (odd-pilot `model` + `simulate`)
   drops invalidity from ~99 % to **1.2 %** — but discretisation and
   BDeu smoothing still leak a residue of cross-bin impossibilities
   (summer snow, curve overspeed). This is the design brief's point that
   *linting inside generation is mandatory, not cosmetic*: the gate turns
   1.2 % into **0 %** at a 99 % yield.
4. **The instrument audits its authors too.** Our first "coherent"
   operation sampler was itself flagged by physcheck: it drew sun azimuth
   independently of elevation (GEO-001: impossible solar declination) and
   bounded braking by the wetness class rather than the declared friction
   (FRI-013/015/016). Writing physically coherent scenarios by hand is
   hard even when you are trying — which is rather the study's point. The
   fixes: sun positions sampled from the ephemeris itself, and a composite
   sun feature in the BN (the elevation↔azimuth locus is a curve that no
   pair of independently-discretised features can represent).

## Threats to validity

- The template fixes the scenario *skeleton*; strategies only choose
  parameter values. Generators that also synthesise roads or maneuvers face
  additional validity risks (map/storyboard consistency) that this study
  does not measure — the numbers here are a *lower* bound on their exposure.
- The criticality proxy for `search` is synthetic (no simulator in the
  loop), but it rewards exactly the conditions adversarial weather/criticality
  searches seek, and its physics-blindness — not its fitness landscape — is
  what the study measures.
- The `opmodel` strategies depend on a synthetic-but-coherent operation
  sampler standing in for real drive data; with real profiling data (e.g.
  the SCTrans/DLR corpora of the physcheck benchmark) the BN would inherit
  real-world dependency structure instead.
- physcheck itself is the measurement instrument; its false-positive rate is
  independently benchmarked at 0 tool FPs over 1,109 real-data files
  (physcheck-benchmark v0.3.0), so invalid verdicts here are unlikely to be
  tool artifacts.
