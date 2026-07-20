# Interpretation decisions

Non-obvious semantic and engineering decisions taken while building physcheck v0.1.
Numbered for cross-reference from code, catalog packs and reports.

**D1 — Monorepo layout.** Two distributions per the brief (`physcheck`, `odd-pilot`);
only physcheck is implemented in v0.1, `odd-pilot/` is an explicit skeleton whose stub
subcommands raise `NotImplementedError` (except `lint`, which delegates to physcheck).

**D2 — Catalog location & packaging.** The rule packs live at `physcheck/catalog/` (the
visible, community-maintained location required by the project layout);
`src/physcheck/catalog` is a relative symlink to it so setuptools ships the packs as
package data in the src layout. The loader falls back to the repo-layout path if package
data is missing.

**D3 — Severity vocabulary.** `error` = physically impossible or normatively invalid
(definitional identities, WMO-ratified records, hard physical limits, ASAM schema
ranges); `warning` = implausible / outside everything observed (class boundaries,
climatological 95% ranges, capability envelopes); `info` = notable but plausible
(running pedestrian, adverse-weather wind). Reporting default is `--severity error`
(per the brief's "(default: error)"); suppressed lower-severity counts are announced so
warnings are discoverable.

**D4 — Exit codes.** `0` ok, `1` findings at/above `--fail-on` (default `error`), `3`
usage/config error (argparse subclass maps its usual exit 2 to 3). Exit `2` is reserved
for odd-pilot's "campaign not adequate".

**D5 — TimeOfDay timezone.** OSC 1.x does not define the timezone of
`TimeOfDay@dateTime` and a `.xosc` carries no geodetic location (that is in the
OpenDRIVE `geoReference`, an L2 input). All time-of-day-based solar rules (SOL-007/008)
therefore assume `dateTime` ≈ local time and are capped at `warning` severity. Full
ephemeris consistency checks are specified in `catalog_report.md` §Solar for the L2
`solar_geo` pack.

**D6 — OSC 1.0 precipitation intensity.** The 1.0 unitless `intensity ∈ [0,1]` has no
citable mapping to mm/h (CARLA's 0–100 is an explicitly visual parameter). mm/h-based
rules never fire on 1.0-style files; only the dry/rain contradiction rules and the
schema range apply to `intensity01`.

**D7 — Missing-attribute semantics (three-valued logic).** A `when` guard referencing an
absent attribute makes the rule *not applicable* (no finding, not counted as skipped).
An `assert` that cannot be evaluated (absent attribute or type error) is *skipped* and
counted in `rules_skipped` — a rule never fires on missing data. `exists('a.b')` lets
predicates opt into explicit presence checks; disjunctive asserts over alternative
attributes must guard each arm with `exists()` (see PRE-001/002/012), because `or`
evaluates both operands when the first is false.

**D8 — Fog element as visibility carrier.** Corpus practice (esmini, ScenarioRunner)
uses `Fog@visualRange` with huge values as a "clear sky" idiom, while WMO defines fog as
visibility < 1 km. ATM-001 is therefore a `warning`, not an `error`; the Rayleigh cap
(ATM-002, > 350 km) stays an error.

**D9 — Entity contexts see the Init environment.** Friction- and weather-coupled entity
rules (FRI-013…) evaluate against the *first* declared environment. Scenarios with
mid-story environment changes get one scenario-context per environment state, but entity
couplings are only checked against Init in v0.1 (cross-context checks, e.g. wetness/
friction monotonicity, are an engine v0.2 item).

**D10 — Parameter scoping flattened.** `ParameterDeclaration`s from every level
(scenario, Story, ManeuverGroup, Maneuver) are collected into one namespace (first
declaration wins). physcheck needs values, not OSC's lexical scoping; a name collision
with different values could in principle mis-resolve, accepted for v0.1. Parameter
values that are themselves `${…}` expressions are resolved recursively (depth-capped).

**D11 — Fixtures are minimal, not XSD-complete.** Violating/valid fixtures carry only
the elements physcheck reads (e.g. vehicles without Axles). Full XSD validation is an
explicit non-goal of the built-in L0 ("reuse existing OpenSCENARIO tooling where
possible" per the brief); physcheck's L0 checks well-formedness, header/version,
references, parameters and normative ranges/enums.

**D12 — Catalogs and ParameterValueDistributions are not resolved.** Entities or
environments from `CatalogReference` yield SCH-007 (info) and are excluded from entity
rules; PVD documents are recognized and skipped. This is the main v0.1 blind spot
(quantified in first_findings.md) and the top L0 item for v0.2.

**D13 — Sun `intensity` (OSC 1.0/1.1) is read as illuminance.** The ASAM 1.0 model doc
gives lux for `intensity`; it is mapped to `env.sun.illuminance_lux`. Files that misuse
it as a [0,1] scalar (ScenarioRunner) simply fall below all illuminance thresholds — no
false positives, but low-side checks are impossible (a hard illuminance floor was
rejected in research anyway, see catalog_report §Solar R3).

**D14 — Friction-circle tolerance 1.35.** `frictionScaleFactor` multiplies a dry
reference μ≈0.9, but tire peak μ spans ~0.9–1.2 on the same surface. FRI-013/023 use
`μ·g·1.35` so that scale-1.0 roads admit up to ~11.9 m/s² (consistent with the 11.8
absolute cap) and only genuinely surface-inconsistent capabilities fire (e.g. 9 m/s² on
a 0.3-scale surface). Initially 1.1; widened after it flagged
`maxDeceleration=10` on a scale-1.0 road, which peak street tires can achieve.

**D15 — Thresholds reconciled across research streams.** Where independent literature
streams proposed different bounds, the reconciliation is recorded in
`catalog_report.md` (acceleration error at 13 m/s² not 10.5; car maxSpeed warning at
100 m/s not 70; vehicle height error at 4.95 m not 4.0; snow-temperature error at
6.1 °C with the desert-air caveat in the message).

**D16 — Local toolchain quirks (HPC).** The cluster Python lacks `_sqlite3`, which
crashes mypy ≥ 1.12's sqlite metadata cache; dev extra pins `mypy<2` and CI (ubuntu,
sqlite present) is the source of truth. All checks (pytest 177 passed, `ruff check`
clean, `mypy --strict` clean on 14 source files) were run locally with Python 3.10.19,
mypy 1.11.2, ruff 0.15.22, pytest 9.1.1, hypothesis 6.157.0.

**D17 — Message templating.** `{dotted.attr}` placeholders are substituted from the
attribute view (unknown names left verbatim); templates in YAML are whitespace-folded.
Findings carry the raw offending values separately (`values`), which `--explain` prints.
