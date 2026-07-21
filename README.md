# odd-pilot

[![CI](https://github.com/BorhaneddineHamadou/oddpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/BorhaneddineHamadou/oddpilot/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python ≥3.10](https://img.shields.io/badge/python-3.10%2B-blue.svg)](physcheck/pyproject.toml)

**An ODD-aware copilot for scenario-based testing of autonomous driving systems.**

`odd-pilot` is a Python toolkit (library + CLI) that drives a scenario-based test
campaign end to end. It **validates** every OpenSCENARIO file against a versioned,
fully cited catalog of physical-plausibility rules before a single simulation minute is
spent (`physcheck`), **assesses** how much of the expected real-world operation the
executed tests have adequately exercised — probability-weighted coverage over a learned
operational model, with a risk-calibrated stopping rule — and **plans** the next batch
of scenarios to close precisely the coverage gap it measured. One campaign iteration:
**lint → execute (external) → assess → plan → lint → …**

The core is simulator-agnostic and pure Python: scenarios go in as ASAM
OpenSCENARIO 1.x, reports come out as SARIF, JSON, HTML or SOTIF-style evidence
artifacts, and execution stays in whatever simulator or test bench you already use.

This is a monorepo hosting two Python distributions:

| Package | Status | Contents |
|---|---|---|
| [`physcheck/`](physcheck/) | **v0.3 — implemented** | Standalone layered plausibility linter for ASAM OpenSCENARIO 1.x: typed Scenario IR, YAML rule catalog with full literature citations, OpenDRIVE map cross-checks (L2) incl. solar ephemeris, kinematic feasibility (L3) incl. trajectory physics, `lint` / `rules` CLI, SARIF/HTML/JSON output. |
| [`odd-pilot/`](odd-pilot/) | **v0.2 — model/assess/gaps/plan implemented** | Campaign copilot: learned operational model (BN), PWCC probability-weighted coverage & risk-calibrated adequacy (`assess`, exit-code CI gate, ε-sweep), ranked coverage gaps, and gap-targeted generation (`plan`: conditional BN sampling, max–min diversity, `--rarity` mode, physcheck-gated instantiation). `report`/`loop` on the roadmap. Depends on `physcheck`. |

## Quick start (physcheck)

```bash
pip install -e physcheck/

physcheck lint examples/                     # lint a directory of .xosc files (layers L0–L1)
physcheck lint suite/ --map town04.xodr      # enable L2 map cross-checks + L3 kinematics
physcheck lint suite/ --layers L0,L1,L2,L3   # maps via each scenario's RoadNetwork/LogicFile
physcheck lint s.xosc --format sarif -o l.sarif   # CI-ready output
physcheck lint suite/ --fail-on error        # exit 1 on any error → CI quality gate
physcheck lint s.xosc --explain ATM-001      # rule text, citation, offending values
physcheck rules list --layer L1              # enumerate the catalog: id, severity, source
physcheck rules show SOL-001                 # predicate, thresholds, citation
physcheck rules lint my_rules.yaml           # validate a custom rule pack
physcheck lint suite/ --rules my_rules.yaml  # extend the catalog with custom rules
```

Exit codes: `0` success, `1` findings at/above the `--fail-on` threshold, `3` usage/config error.

## The rule catalog is a deliverable

Every rule in [`physcheck/catalog/`](physcheck/catalog/) carries an id, layer, severity,
machine-checkable predicate, units, and a **full citation to primary literature**
(atmospheric optics, tire–road friction, solar geometry, precipitation microphysics,
road-user biomechanics, regulations). The research behind it is documented in:

- [`docs/attribute_space.md`](docs/attribute_space.md) — the scenario attribute space as the
  union of the OpenSCENARIO 1.x schema, ISO 34503 / BSI PAS 1883 ODD taxonomies, simulator
  APIs (CARLA, esmini, …), and open scenario-dataset schemas; with provenance, type, units,
  range per attribute.
- [`docs/catalog_report.md`](docs/catalog_report.md) — how each rule was derived, grouped by
  physical domain, including a **rejected-candidates appendix** (nothing is dropped silently).
- [`docs/first_findings.md`](docs/first_findings.md) — results of linting a public scenario
  corpus (esmini, ASAM OSC-ALKS, CARLA ScenarioRunner examples).
- [`docs/decisions.md`](docs/decisions.md) — interpretation decisions taken during implementation.

## Layers

| Layer | Content | Status |
|---|---|---|
| L0 | Schema & ranges: XML/OSC validity, unit sanity, enum membership, dangling references | ✅ v0.1 |
| L1 | Environmental & physical rules (researched, cited catalog) | ✅ v0.1 |
| L2 | Map cross-checks (OpenDRIVE: roads/lanes exist, drivable spawns, interpenetration, route connectivity, speed limits) + `solar_geo` ephemeris pack | ✅ v0.2 |
| L3 | Kinematic & dynamic feasibility: friction circle v²≤µgr vs map curvature with µ from the L1 environment, lane-change lateral acceleration, trajectory continuity/teleports, VRU sustained speeds | ✅ v0.3 |
| L4 | Storyboard logic (static analysis) | roadmap |
| L5 | ODD conformance (ASAM OpenODD) | roadmap |
| L6 | Statistical plausibility (learned operational model) | roadmap |

Map-independent kinematic bounds (VRU speeds, performance envelopes) are checkable from the
`.xosc` alone and are shipped in v0.1 as part of the researched catalog.

## Development

```bash
pip install -e "physcheck/[dev]"
ruff check physcheck && mypy physcheck/src && pytest physcheck/tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under [Apache-2.0](LICENSE).
