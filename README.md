# odd-pilot

[![CI](https://github.com/BorhaneddineHamadou/oddpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/BorhaneddineHamadou/oddpilot/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python ≥3.10](https://img.shields.io/badge/python-3.10%2B-blue.svg)](physcheck/pyproject.toml)

**[→ Plain-language documentation site](https://borhaneddinehamadou.github.io/oddpilot/)**

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

**Why it matters** ([`studies/generated_corpus/`](studies/generated_corpus/)): with
every parameter value individually schema-legal, standard generation strategies still
produce physically impossible scenarios almost every time — random sampling **98.6 %**,
pairwise combinatorial **100 %**, adversarial criticality search **100 %** (worst of
all: it actively optimises into impossibility). odd-pilot's operational-model sampling
brings that to **1.2 %**, and its physcheck gate to **0 %** at 99 % yield.

This is a monorepo hosting two Python distributions:

| Package | Status | Contents |
|---|---|---|
| [`physcheck/`](physcheck/) | **v0.3 — implemented** | Standalone layered plausibility linter for ASAM OpenSCENARIO 1.x: typed Scenario IR, YAML rule catalog with full literature citations, OpenDRIVE map cross-checks (L2) incl. solar ephemeris, kinematic feasibility (L3) incl. trajectory physics, `lint` / `rules` CLI, SARIF/HTML/JSON output. |
| [`odd-pilot/`](odd-pilot/) | **v0.4 — model/assess/gaps/plan/report/loop implemented** | Campaign copilot: learned operational model (BN), PWCC probability-weighted coverage & risk-calibrated adequacy (`assess`, exit-code CI gate, ε-sweep), ranked coverage gaps, and gap-targeted generation (`plan`: conditional BN sampling, max–min diversity, `--rarity` mode, physcheck-gated instantiation). `conform` (L5 OpenODD) on the roadmap. Depends on `physcheck`. |

## Installation (step by step)

```bash
# 1. get the code (or: GitHub → Code → Download ZIP)
git clone https://github.com/BorhaneddineHamadou/oddpilot.git
cd oddpilot

# 2. recommended: a virtual environment
python3 -m venv .venv && source .venv/bin/activate   # Windows: py -m venv .venv ; .venv\Scripts\Activate.ps1

# 3. install — the linter alone (one lightweight dependency) ...
pip install -e physcheck/
#    ... or the full campaign copilot (adds pandas + pgmpy)
pip install -e physcheck/ -e odd-pilot/

# 4. verify against the shipped examples
physcheck lint examples/violating   # must report errors
physcheck lint examples/valid       # must be clean
```

Requirements: Python ≥ 3.10 and git — no simulator, no GPU, no admin rights;
the tool makes no network calls at runtime. Update later with `git pull`
(editable installs pick changes up immediately). Full walkthrough with
Windows commands and troubleshooting: [installation guide](https://borhaneddinehamadou.github.io/oddpilot/install.html).

## Quick start (physcheck)

```bash

physcheck lint examples/                     # lint a directory of .xosc files (layers L0–L1)
physcheck lint suite/ --map town04.xodr      # enable L2 map cross-checks + L3 kinematics
physcheck lint suite/ --layers L0,L1,L2,L3   # maps via each scenario's RoadNetwork/LogicFile
physcheck lint suite/ --odd odd.yaml         # L5 ODD conformance (in/out/undeclared)
physcheck lint suite/ --layers L0,L1,L4      # L4 storyboard static analysis
odd-pilot lint suite/ --layers L0,L1,L6 --model odd.bn   # L6 statistical plausibility
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
| L4 | Storyboard logic: dead triggers, empty act intervals, conflicting simultaneous actions per control channel, actor-less groups, zero execution counts, non-terminating storyboards, type-incompatible comparisons | ✅ v0.5 |
| L5 | ODD conformance: scenario attributes vs a YAML ODD definition (OpenODD include/exclude semantics); verdicts in / out / undeclared | ✅ v0.4 |
| L6 | Statistical plausibility: scenario scored under the learned operational model (odd-pilot BN); never-observed combinations below a quantile floor flagged as warnings — never blocks | ✅ v0.5 |

Map-independent kinematic bounds (VRU speeds, performance envelopes) are checkable from the
`.xosc` alone and are shipped in v0.1 as part of the researched catalog.

## Development

```bash
pip install -e "physcheck/[dev]"
ruff check physcheck && mypy physcheck/src && pytest physcheck/tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under [Apache-2.0](LICENSE).
