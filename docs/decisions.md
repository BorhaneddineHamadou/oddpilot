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

**D18 — Catalog resolution (supersedes the D12 limitation).** `CatalogLocations`
directories are scanned for `*.xosc` catalog files; entries are indexed by
(`Catalog@name` *or* file stem, entry name) — the fallback covers corpora whose
catalogName refers to the file rather than the Catalog element. Entry
`ParameterDeclarations` provide defaults, overridden by the reference's
`ParameterAssignments` (resolved in scenario scope); the entry is parsed in its own
parameter namespace (shared issue sink). Vehicle/Pedestrian/MiscObject and Environment
references resolve; unresolvable references keep the SCH-007 info finding and stay
excluded from entity rules. OSC's catalog-name uniqueness subtleties (two files with the
same Catalog@name) resolve first-match in sorted filename order.

**D19 — Version gating (`version_gating.yaml`, VER-001…010).** FileHeader
revMajor/revMinor gate the vocabulary: attributes used before their introduction
(precipitationIntensity/Wind/temperature/pressure < 1.1; fractionalCloudCover/wetness/
Sun@illuminance < 1.2; Vehicle@mass < 1.1) are errors; deprecated attributes used in
newer revisions (intensity01 ≥ 1.1, cloudState ≥ 1.2, Sun@intensity ≥ 1.2) are info.
Which Sun spelling was used is tracked as `env.sun.illuminance_attr`.

**D20 — Cross-environment checks are plugin rules.** FRI-024 (friction scale must be
non-increasing in wetness severity across a scenario's environment states) needs all
environment states at once, which the per-context YAML engine cannot express; it ships
as the first L1 plugin rule (`physcheck.engine.plugins.l1_cross`), with plugin metadata
unified across layers so `rules list/show` covers it.

**D21 — OpenDRIVE geometry by sampling (`physcheck.xodr`).** Reference lines (line,
arc, spiral, poly3, paramPoly3) are sampled at ~0.5 m (spirals/polys integrated at
≤0.25 m then thinned); world→road projection is nearest-sample; poly3-family s-values
are chord-length approximations. Positional error is centimetre-level — far below the
half-lane-width tolerances any L2 rule uses. Elevation profiles, superelevation and
lateral shape records are NOT modelled: all checks are planar, and `z` is ignored
except where noted (D27). Speed records: `max` with units m/s ("m/s"/"ms"), km/h, mph;
"no limit"/"undefined" mean no record.

**D22 — Route connectivity is direction-agnostic (MAP-006).** The road graph joins
road↔road links plus junction (incomingRoad, connectingRoad) pairs, undirected; a route
is flagged only when NO path exists between consecutive waypoints' roads. Modelling
travel direction (lane sign, contactPoint) would catch wrong-way routes but risks false
positives on unusual junctions; existence-of-path errs on the safe side — what it
flags (typically waypoints on a disconnected road or the wrong map) is indefensible.

**D23 — Drivable lane types (MAP-004).** Motor vehicles: driving, exit, entry, onRamp,
offRamp, connectingRamp, slipLane, bus, taxi, HOV, mwyEntry, mwyExit (OpenDRIVE 1.4-1.8
vocabularies merged), plus parking and stop (legitimate spawn locations). Bicycles
additionally: biking, shoulder, border, sidewalk, walking — cyclists plausibly stage on
sidewalks in crossing scenarios (srunner CyclistCrossing). Pedestrians and misc objects
are never spawn-checked (a pedestrian on a driving lane is the scenario's point).
A WorldPosition is checked against every road whose reference line passes within 25 m;
the spawn is accepted if ANY overlapping road offers an allowed lane (junction overlaps).
When the point is off-lane but its y-mirror lies on an allowed lane, the finding notes
that the scenario appears to use CARLA's left-handed frame instead of the OpenDRIVE
inertial frame ASAM OpenSCENARIO mandates (all 13 srunner MAP-004 findings are of this
class) — still an error: such scenarios are not portable across engines.

**D24 — Speed-vs-limit slack (MAP-007).** Warning only when the maximum commanded
absolute speed exceeds 110% of the road-type speed record at the spawn point —
tolerating mild overshoot and flagging only clear unintentional speeding (the esmini
hit commands 216% of the limit). Deliberate speeding scenarios should carry the speed
as an explicit parameter, which linting surfaces for review either way.

**D25 — solar_geo interpretation (GEO-001…006).** The map's `geoReference`
(+lat_0/+lon_0) is taken at face value as the scenario's geodetic anchor — CARLA towns
declare (0°, 0°), so their suns are judged at Null Island; that is a statement the
scenario+map pair actually makes. In-map position offsets are ignored (town-scale maps
move the sun <0.1°). Naive dateTimes are tried as {UTC, local standard = round(lon/15),
local DST = +1 h} and the minimum discrepancy is scored (D5); tz-aware dateTimes are
taken literally. Tolerances 0.7° warning / 5° error (refraction-dominated, per
catalog_report §Solar). When both declared and computed sun are below the horizon the
ephemeris check passes (night is night; exact below-horizon position is irrelevant).
Ephemeris: NOAA/Meeus chain in `physcheck.ephemeris`, ~0.01° in 1900-2100, validated
against the NOAA calculator in tests.

**D26 — L2 map resolution.** `--map FILE` applies one map to all files and implies
layer L2; without `--map`, each scenario's `RoadNetwork/LogicFile` (now
parameter-resolved — ALKS uses `$Road`) is tried relative to the scenario directory,
with per-run caching. Files with no resolvable map skip L2 with a stderr note — never
an error, since suites routinely mix mapped and unmapped scenarios (srunner references
engine-internal "Town01" with no file).

**D27 — Interpenetration scope (MAP-005).** Planar oriented-bbox (length×width)
separating-axis test over Init teleport poses; WorldPosition headings default to 0 when
`h` is absent, bbox Center offsets are ignored. Pairs linked by a Relative* init
position are exempt — that is the attachment idiom (esmini drop-bike mounts a bike on
a car via RelativeObjectPosition). Entities placed at the SAME absolute pose remain
flagged (esmini trailers.xosc stacks tractor+trailers; the hitch coupling that
un-overlaps them is engine-side, invisible at OSC level — physically impossible as
declared, cf. the engine-coupling vacuity discussion in catalog_report).

**D28 — Trajectory IR scope (v0.3).** `FollowTrajectoryAction` Polyline vertices are
captured as float-only `TrajVertex` records (time, x, y, z), never as
Position/PositionUse: a replayed recording carries 10^5-10^6 vertices — they are motion
samples, not placement declarations, so L2 spawn/interpenetration semantics do not
apply to them and memory stays bounded. Non-world vertices are counted
(`total_vertices`) but not kept; Clothoid/Nurbs shapes are recorded by name and skipped.
Inline `Trajectory` (OSC 1.0), `TrajectoryRef` (>= 1.1) and `CatalogReference`
trajectories are all resolved.

**D29 — Effective friction ceiling (DYN rules).** L3 composes with the L1 environment
via an UPPER bound of plausible peak tire-road friction: declared
`frictionScaleFactor` × 0.9 × 4/3 (FRI-013's convention and tolerance), else a generous
class ceiling from the declared state — dry 1.2, moist 1.0, wetWithPuddles 0.9,
lowFlooded 0.7, highFlooded 0.4, falling snow 0.5, freezing+wet (ice) 0.35 (top of the
published ranges: Wallman & Åström VTI 911A; Bosch handbook p. 330). With several
environment states the MOST favourable is used; with none, dry. Exceeding
mu_ceiling × g is therefore certainly impossible on the declared surface — the checks
under-report rather than guess.

**D30 — Lane-change lateral acceleration (DYN-002).** Peak lateral acceleration of the
sinusoidal lateral profile y(t) = w/2·(1−cos(πt/T)): a_peak = wπ²/(2T²), with w the
widest driving-lane width at the entity's spawn (map available) else 3.5 m, and T the
commanded duration — a distance-dimension lane change is converted with the entity's
MINIMUM commanded speed (longest plausible duration; conservative). Fires at
a_peak > mu_ceiling·g·1.2. Complements KIN-021/022, which bound the duration absolutely
without surface or width knowledge.

**D31 — Trajectory feasibility statistics (DYN-004..007).** Speeds and accelerations
for DYN-006 (friction circle, sqrt(a_lat²+a_long²) > mu·g·1.35) are estimated over a
>= 0.4 s window on each side of a vertex (path length / elapsed time, curvature from
the window endpoints), never from adjacent raw samples: recorded corpora quantise
positions (a 0.1 m grid at 25 Hz was measured in corner_case_ndd), and
adjacent-sample differencing turns that grid into +-62 m/s² of phantom acceleration,
while the window bounds the quantisation error to ~1 m/s². Sparse keyframe
trajectories (local dt >= window) resolve to their raw segments. On top of the
window, DYN-006 requires TWO consecutive violating vertices with mid-dt in
[0.02 s, 10 s]. DYN-005 deliberately stays per-raw-segment (a declared teleport IS an
instantaneous jump; its thresholds sit far above quantisation noise); segments with
dt < 1 ms are treated as unmeasurable (None), not as infinite speed. DYN-006 applies to vehicles only (tire traction physics; legs/pedals
excluded). DYN-005 reuses the L1 class record ceilings (vehicle 140, bicycle 39,
pedestrian 12.5 m/s); a violating segment is a teleport, reported once per trajectory
at its worst segment. DYN-007 (warning) bounds SUSTAINED VRU speed — max windowed
average over ~30 s (>= 80% of the window observed), pedestrian 6.0 m/s (marathon WR
pace 5.83), bicycle 16.0 m/s (UCI hour record 15.8) — on trajectories >= 10 s. After a
DYN-004 time-axis violation the remaining trajectory checks are suppressed (speeds are
meaningless on a broken time axis).

**D32 — DYN-001 trusts declared positions only.** The curve-speed check runs only for
RoadPosition/LanePosition spawns (explicit roadId). World positions are NOT projected
onto the nearest road: at junctions, short corner-arc roads (r ~4-9 m) overlap the
through path, and nearest-reference-line projection routinely assigns a
straight-through vehicle to a curved road it never drives — verified on SCTrans's
converted inD intersection maps, where projection produced 69 spurious curve-speed
findings across 57 files (benchmark v0.3.0 triage). Declared road/lane spawns carry
the file's own claim about which road the vehicle occupies, which is the only claim
v² > mu·g·r can safely refute.

**D33 — Teleport segments are data breaks.** A raw trajectory segment whose implied
speed exceeds the class record ceiling is DYN-005's finding — an impossible position
jump. Downstream kinematic statistics (DYN-006 friction circle, DYN-007 sustained
speed) split the trajectory at such segments and analyse each run separately:
estimation windows straddling the jump would otherwise re-report the same single
defect as phantom sustained acceleration (observed with corner_case_ndd's
placeholder-first-frame exports). Instantaneous speed *steps* below the teleport
ceiling (e.g. DLR-UT track re-associations, Δv 7 m/s in one 50 ms sample) are NOT
breaks — they genuinely violate the friction circle and stay DYN-006 findings.
