# physcheck

Standalone, layered physical-plausibility linter for ASAM OpenSCENARIO 1.x scenarios.
Pure Python ≥ 3.10; no simulator dependencies; the only runtime dependency is PyYAML.

```bash
pip install -e .
physcheck lint suite/ --format sarif -o lint.sarif --fail-on error
physcheck lint suite/ --map town04.xodr        # L2 map cross-checks + solar_geo
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

**physcheck 0.2.0:**

| Corpus (real data) | Files | Tool false positives | Specificity | Conversion-artifact findings¹ | Seeded mutants | Detected | Sensitivity |
|---|---|---|---|---|---|---|---|
| corner_case_ndd | 25 | 0 | 100.0% | 0 | 76 | 76 | 100.0% |
| dlr_ht | 1 | 0 | 100.0% | 0 | — | — | — |
| dlr_ut | 4 | 0 | 100.0% | 0 | — | — | — |
| sctrans_real | 1079 | 0 | 100.0% | 1079 files | 1545 | 1545 | 100.0% |

¹ Error findings manually verified as TRUE defects of the corpus's conversion
pipeline — CARLA template metadata (maxAcceleration = 200 m/s², copy-pasted
suns, 5×2 m pedestrian bounding boxes) and under-covering converted maps —
not tool mistakes. Per-finding triage evidence, corpora provenance and the
full protocol live in the benchmark repo
([physcheck-benchmark](https://github.com/BorhaneddineHamadou/physcheck-benchmark)).
The benchmark's first catch was in physcheck itself: SCTrans's wrong-case
`<OpenScenario>` root made the parser abort before the physics layers
(fixed in 0.2.0).

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
