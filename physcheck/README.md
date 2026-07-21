# physcheck

Standalone, layered physical-plausibility linter for ASAM OpenSCENARIO 1.x scenarios.
Pure Python ≥ 3.10; no simulator dependencies; the only runtime dependency is PyYAML.

```bash
pip install -e .
physcheck lint suite/ --format sarif -o lint.sarif --fail-on error
physcheck lint suite/ --map town04.xodr        # L2 map cross-checks + L3 kinematics
physcheck lint suite/ --odd odd.yaml           # L5 ODD conformance (in/out/undeclared)
physcheck rules list --layer L2
physcheck rules show ATM-001
```

## Architecture

- **Scenario IR** (`physcheck.ir`): a typed, engine-agnostic intermediate representation.
  `physcheck.ir.osc_parser` maps OpenSCENARIO 1.0–1.3 XML into the IR (with
  ParameterDeclaration / `$param` / `${expr}` resolution). Rules never see raw XML — they
  read a flat, canonically named **attribute view** (`physcheck.ir.attributes`), documented
  in `../docs/attribute_space.md`.
- **OpenDRIVE maps** (`physcheck.xodr`): stdlib-only `.xodr` frontend — roads, lane
  sections/types/widths, links & junctions, speed records, plan-view geometry
  (line/arc/spiral/poly3/paramPoly3) with world↔road projection, and the `geoReference`
  geodetic anchor. Powers layer L2: `--map FILE`, or automatic resolution of each
  scenario's `RoadNetwork/LogicFile`.
- **Solar ephemeris** (`physcheck.ephemeris`): dependency-free NOAA/Meeus solar position
  (~0.01°), used by the L2 `solar_geo` rules (GEO-001…006).
- **L4 storyboard logic** (`l4_storyboard`, STB-001…007): static analysis of the
  control structure — dead triggers (delay-aware simulation-time bounds), empty act
  intervals, conflicting simultaneous actions on one control channel, actor-less
  groups with private actions, zero execution counts, missing termination,
  type-incompatible parameter comparisons (D35).
- **L6 statistical plausibility** (`l6_statistical`, STA-001): scenarios scored
  under an injected operational-model scorer (odd-pilot provides one from its BN);
  combinations below a configurable quantile of real operation are flagged
  `warning: never-observed` — never blocks execution (D36).
- **L5 ODD conformance** (`physcheck.odd` + `l5_odd`, ODD-000…002): scenario
  attributes against a YAML ODD definition with OpenODD include/exclude condition
  semantics — out-of-ODD is an error, ODD-constrained-but-undeclared a warning (D34).
- **L3 kinematic feasibility** (`physcheck.engine.plugins.l3_kinematics`, DYN-001…007):
  motion against tire physics and the map — friction-circle bound v²≤µgr on the road's
  curvature with µ composed from the L1 environment state (layers compose: 9 m/s²
  braking is valid on dry asphalt, impossible on a flooded road), lane-change lateral
  acceleration over the actual lane width, and `FollowTrajectoryAction` feasibility
  (time monotonicity, teleport segments, friction circle, VRU sustained speeds) on a
  new trajectory IR that scales to replayed-recording corpora with 10⁵+ vertices.
- **Rule engine** (`physcheck.engine`): loads YAML rule packs (`catalog/*.yaml`) and Python
  plugin rules (`physcheck.engine.plugins`), evaluates predicates in a safe expression
  language, and emits findings.
- **Reports** (`physcheck.report`): `table` (terminal), `json`, `sarif` (2.1.0, GitHub code
  scanning ready), `html` (self-contained page).

## Benchmark: real-world data

physcheck is evaluated on every release against an independent benchmark of
OpenSCENARIO files derived from **real recorded driving** (inD/highD drone
recordings, NGSIM camera data, DLR infrastructure-sensor measurements,
naturalistic corner cases). Real scenarios are physically plausible by
construction, so error findings on them measure the false-positive rate; the
false-negative rate is measured on mutants of the same files, each seeded with
one certainly-impossible violation (sun above the zenith, 0-dimension bounding
boxes, spawns 2 km off the map, ...).

**physcheck 0.3.0** (layers L0–L3):

| Corpus (real data) | Files | Tool false positives | Specificity | Conversion-artifact findings¹ | Seeded mutants | Detected | Sensitivity |
|---|---|---|---|---|---|---|---|
| corner_case_ndd | 25 | 0 | 100.0% | 1 file | 154 | 154 | 100.0% |
| dlr_ht | 1 | 0 | 100.0% | 0 | — | — | — |
| dlr_ut | 4 | 0 | 100.0% | 4 files | — | — | — |
| sctrans_real | 1079 | 0 | 100.0% | 1079 files | 1665 | 1665 | 100.0% |

¹ Error findings manually verified as TRUE defects of the corpus's
conversion/reconstruction pipeline, not tool mistakes: CARLA template metadata
(maxAcceleration = 200 m/s², copy-pasted suns, 5×2 m pedestrian bounding
boxes), under-covering converted maps, and — new with L3, which reads the
declared *motion* — placeholder first-frame teleports and synthetic eased
stops in RoadRunner exports, and instantaneous speed steps from track
re-association in infrastructure-sensor replays. Per-finding triage evidence,
corpora provenance and the full protocol live in the benchmark repo
([physcheck-benchmark](https://github.com/BorhaneddineHamadou/physcheck-benchmark)).
Each release the benchmark has caught defects in physcheck itself before they
shipped: SCTrans's wrong-case `<OpenScenario>` root aborting the parser
(fixed in 0.2.0); L3 mis-attributing curved roads to world-positioned spawns
at junctions, and phantom accelerations from 0.1 m position quantisation
(both fixed in 0.3.0, see TRIAGE_v0.3.0.md).

## Rule YAML schema

```yaml
pack: atmosphere            # pack name
version: "0.1.0"
rules:
  - id: ATM-001             # stable unique id
    layer: L1               # L0..L6
    severity: error         # error | warning | info
    title: Dense fog implies short visual range
    scope: scenario         # scenario | entity | entity:pedestrian | entity:vehicle ...
    when: "env.fog.present"           # guard (optional): rule applies when true
    assert: "env.fog.visual_range_m < 2000"   # must hold, else finding
    message: "Fog is declared but visualRange={env.fog.visual_range_m} m ..."
    units: {env.fog.visual_range_m: m}
    citation:
      source: "..."
      authors: "..."
      year: 2024
      doi_or_url: "..."
    quantitative_basis: "..."
```

### Predicate expression language

A safe subset of Python expressions evaluated over the attribute view — names
(dotted attribute paths), numeric/string/bool literals, arithmetic (`+ - * / % **`),
comparisons (incl. chained), `and/or/not`, `in` over lists, function calls limited to
`abs, min, max, exists, sin, cos, tan, asin, acos, atan2, sqrt, log, exp, radians, degrees`.
Attributes that are absent make the enclosing `when` guard false (three-valued semantics)
unless tested with `exists(...)`; an `assert` that cannot be evaluated because of missing
attributes is skipped, never reported. See `../docs/decisions.md` (D7).

## Exit codes

`0` success (no findings at/above `--fail-on`), `1` findings at/above threshold,
`3` usage/config error.
