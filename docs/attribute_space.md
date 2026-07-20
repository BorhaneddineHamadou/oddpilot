# The scenario attribute space

**Version 0.1.0 · 2026-07-20**

This document enumerates the attribute space a scenario-plausibility linter must speak:
the **union** of (1) the ASAM OpenSCENARIO 1.x schema, (2) the ODD taxonomies of ISO
34503:2023 and BSI PAS 1883:2020, (3) the environment APIs of driving simulators (CARLA,
esmini, SVL, BeamNG.tech), and (4) the feature schemas of open scenario corpora
(DeepScenario, ASAM OSC-ALKS, esmini resources, CARLA ScenarioRunner, Safety Pool). Every
attribute is recorded with provenance, type, units and range. The final section maps the
union onto physcheck's canonical attribute vocabulary and lists what falls outside
OpenSCENARIO 1.x entirely.

Sources are cited inline; the full derivation of *rules* over these attributes is in
[`catalog_report.md`](catalog_report.md).

---

## 1. OpenSCENARIO 1.x schema (concrete scenario format)

Sources: ASAM OpenSCENARIO model documentation — 1.0.0 and 1.1.0 at
`releases.asam.net/OpenSCENARIO/<v>/…`, 1.2.0 at
`asam.net/static_downloads/ASAM_OpenSCENARIO_V1.2.0_Model_Documentation/…`, 1.3.0 at
`publications.pages.asam.net/…/v1.3.0/` (~35 class pages verified per attribute).
Version-attribution corrections found during verification: `temperature`,
`atmosphericPressure` and `Wind` are **since 1.1** (not 1.2); `Sun@intensity` was
specified in **lux** already in 1.0 ("direct sunlight is around 100,000 lx");
`Performance@maxAccelerationRate/maxDecelerationRate` (jerk, m/s³) are **1.2**;
`${expression}` support is **since 1.1** (1.2 added round/floor/ceil/sqrt/pow, 1.3 added
trig/abs/min/max/sign and boolean operators).

### 1.1 Environment

| Attribute (osc_path) | Since | Depr. | Type / units | Normative range / enum | Notes |
|---|---|---|---|---|---|
| Weather@cloudState | 1.0 | 1.2 | enum | cloudy, free, overcast, rainy, skyOff | required in 1.0, optional 1.1 |
| Weather@fractionalCloudCover | 1.2 | — | enum, oktas | zeroOktas…nineOktas | nineOktas = sky obscured |
| Weather@temperature | **1.1** | — | double, K | **[170..340]** | at z=0 |
| Weather@atmosphericPressure | **1.1** | — | double, Pa | **[80000..120000]** | at z=0 |
| Sun@azimuth | 1.0 | — | double, rad | [0..2π]; 0=N, π/2=E, π=S | "counterclockwise" in 1.0 doc is a wording erratum, corrected to clockwise/compass in 1.1 |
| Sun@elevation | 1.0 | — | double, rad | **[−π..π]** (physics: [−π/2..π/2]) | 0 = horizon, π/2 = zenith |
| Sun@intensity | 1.0 | 1.2 | double, **lux** | [0..∞[ | renamed → illuminance, semantics unchanged |
| Sun@illuminance | 1.2 | — | double, lux | [0..∞[ | missing ⇒ interpreted 0 |
| Fog@visualRange | 1.0 | — | double, m | [0..∞[ | + optional BoundingBox (spatially bounded fog volume) |
| Precipitation@precipitationType | 1.0 | — | enum | dry, rain, snow | |
| Precipitation@intensity | 1.0 | **1.1** | double | **[0..1]** unitless | |
| Precipitation@precipitationIntensity | 1.1 | — | double, mm/h | [0..∞[ | valid for all types |
| Wind@direction | **1.1** | — | double, rad | [0..2π[ | **target** direction (not meteorological origin), x-axis = 0 |
| Wind@speed | **1.1** | — | double, m/s | [0..∞[ | |
| DomeImage | 1.2 | — | file + azimuthOffset rad [0..2π] | | mutually exclusive with fractionalCloudCover; may conflict with Sun |
| TimeOfDay@dateTime | 1.0 | — | xsd:dateTime | | timezone semantics undefined (decisions D5) |
| TimeOfDay@animation | 1.0 | — | boolean | | true ⇒ time progresses with simulation |
| RoadCondition@frictionScaleFactor | 1.0 | — | double | [0..∞[ | scales road-network friction |
| RoadCondition@wetness | 1.2 | — | enum | dry, moist, wetWithPuddles, lowFlooded, **highFlooded (> 5 cm water)** | |
| RoadCondition/Properties | 1.0 | — | name/value pairs | | simulator-specific escape hatch |

### 1.2 Entities

| Attribute | Since | Type / units | Range / enum | Notes |
|---|---|---|---|---|
| Vehicle@vehicleCategory | 1.0 | enum | bicycle, bus, car, motorbike, semitrailer, trailer, train, tram, truck, van | complete 10-value list |
| Vehicle@mass | **1.1** | double, kg | [0..∞[ | absent in 1.0 |
| Vehicle/Pedestrian@role | 1.2 | enum | none, ambulance, civil, fire, military, police, publicTransport, roadAssistance | |
| BoundingBox Center x/y/z; Dimensions length/width/height | 1.0 | double, m | dims [0..∞[ | entity frame x fwd/y left/z up; vehicle ref point = rear-axle center on ground |
| Performance@maxSpeed / maxAcceleration / maxDeceleration | 1.0 | double, m/s, m/s² | [0..∞[ | required |
| Performance@maxAccelerationRate / maxDecelerationRate | **1.2** | double, m/s³ | [0..∞[ | jerk; missing ⇒ ∞ |
| Axle @maxSteering | 1.0 | rad | **[0..π]** | front typ. 0.5–0.7 |
| Axle @wheelDiameter / @trackWidth / @positionX / @positionZ | 1.0 | m | wheelDiameter ]0..∞[ | positionZ ≈ wheelDiameter/2 (documented consistency) |
| Vehicle TrailerHitch/TrailerCoupler @dx,@dz; Trailer | **1.3** | m / element | | trailers modeled as Vehicles; Properties became optional in 1.3 |
| Pedestrian@pedestrianCategory | 1.0 | enum | animal, pedestrian, wheelchair | |
| Pedestrian@mass | 1.0 | kg | [0..∞[ | required (unlike Vehicle) |
| Pedestrian@model → @model3d | 1.0 → 1.1 | string | | |
| MiscObject@miscObjectCategory | 1.0 | enum | barrier, building, crosswalk, gantry, none, obstacle, parkingSpace, patch, pole, railing, roadMark, soundBarrier, streetLamp, trafficIsland, tree, vegetation, wind (depr. 1.1) | + required mass, BoundingBox |

### 1.3 Actions (physical content)

| Element | Since | Physical attributes | Lint hook |
|---|---|---|---|
| TransitionDynamics (Speed/LaneChange dynamics) | 1.0 | dynamicsShape {cubic, linear, sinusoidal, **step**}; dynamicsDimension {distance m, **rate**, time s}; value [0..∞[ | dimension=rate ⇒ commanded acceleration (m/s² for speed, lateral m/s for lane change); **step ⇒ infinite acceleration**; followingMode {follow, position} (1.2): position *ignores* performance constraints |
| AbsoluteTargetSpeed / RelativeTargetSpeed | 1.0 | value m/s [0..∞[ / delta m/s or factor; continuous flag | target ≤ Performance.maxSpeed (KIN-023) |
| LongitudinalDistanceAction + DynamicConstraints | 1.0 | distance m XOR timeGap s; maxAcceleration/maxDeceleration/maxSpeed (+ jerk 1.2) all [0..∞[, missing = ∞ | constraints should be ≤ Performance bounds |
| SpeedProfileAction | 1.2 | entries (speed m/s, time s); followingMode | successive entries imply accelerations |
| LaneChangeAction | 1.0 | targetLaneOffset m; full TransitionDynamics | time-dimension ⇒ implied lateral acceleration (KIN-021/022) |
| LaneOffsetAction | 1.0 | maxLateralAcc m/s² [0..∞[, missing = ∞ | > ~0.4 g uncomfortable, ~0.9 g friction limit |
| TeleportAction/Position | 1.0 | 10 position types (World, Relative*, Road, Lane, Route, Geo [1.1], Trajectory [1.1]); m/rad; GeoPosition 1.2: latitudeDeg [−90..90], longitudeDeg [−180..180] | mid-scenario teleports = infinite velocity |
| TrafficSwarmAction | 1.0 | semiMajor/semiMinor/innerRadius m; numberOfVehicles; velocity m/s (depr. 1.2 → InitialSpeedRange) | innerRadius < semiMinor ≤ semiMajor; density |
| VisibilityAction | 1.0 | graphics/traffic/sensors booleans (+ per-sensor set 1.2) | sensors=false but physically interacting = ghost vehicle |

### 1.4 Conditions (physical content)

SpeedCondition (m/s), AccelerationCondition (m/s²) — both + `direction`
{longitudinal, lateral, vertical} since 1.2; TimeHeadwayCondition (s),
TimeToCollisionCondition (s), DistanceCondition / RelativeDistanceCondition (m) — all
with `freespace` (bounding-box vs reference points), `coordinateSystem` {entity, lane,
road, trajectory} (1.1, replacing `alongRoute` depr. 1.1), `relativeDistanceType`
{longitudinal, lateral, euclidianDistance [sic], cartesianDistance (depr. 1.1)},
`routingAlgorithm` (1.2). Rule enum: equalTo, greaterThan, lessThan (1.0) +
greaterOrEqual, lessOrEqual, notEqualTo (1.1). Lint hooks: condition thresholds beyond
Performance limits can never trigger (dead trigger, L4); `equalTo` on continuous
quantities is fragile.

### 1.5 Parameters & expressions

`ParameterDeclaration` (name, parameterType {boolean, dateTime, double, int
[replaces `integer`, depr. 1.2], string, unsignedInt, unsignedShort}, value) with
`ValueConstraintGroup`s (1.1; groups OR-ed, constraints AND-ed; unsatisfied ⇒ scenario
must not start). Any attribute may be a literal, `$param`, or `${expr}` (1.1+;
arithmetic 1.1, round/floor/ceil/sqrt/pow 1.2, trig/abs/min/max/sign/not/and/or 1.3).

**Cross-cutting facts for linting:** (1) most `[0..∞[` ranges are *documentation
annotations, not XSD facets* — the XSD types are plain doubles union-ed with the
parameter pattern, so range enforcement is entirely the linter's job; (2) the only
closed normative environment ranges are temperature [170..340] K, pressure
[80000..120000] Pa, deprecated intensity [0..1], sun azimuth [0..2π] / elevation
[−π..π], wind direction [0..2π[, domeImage azimuthOffset [0..2π], axle maxSteering
[0..π]; (3) `revMajor`/`revMinor` gate the vocabulary — a 1.0 file using
`precipitationIntensity` or a 1.2 file with trailers is version-invalid (a candidate L0
check for v0.2).

## 2. ODD taxonomies: ISO 34503:2023 and BSI PAS 1883:2020

Sources: ISO 34503:2023 preview (front matter + Clauses 1–8 verbatim, ToC for 9–11);
**ASAM OpenODD 1.0.0 Annex B.3**, which renders the complete ISO 34503 taxonomy as YAML
with numeric bounds (ASAM, released 2025-04-03); Skoglund et al., *Formalizing
Operational Design Domains with the Pkl Language* (arXiv:2509.02221) + companion repo
(verbatim ISO clause comments); Bruce, Bruto da Costa, Khastgir & Jennings (WMG),
*Towards Robust ISO 34503 ODD Language Syntax and Semantics* (2024); Khastgir, *ODD
Standardisation activities: BSI PAS 1883 and ISO 34503* (ASAM workshop, 2020). ISO 34503
builds directly on PAS 1883 (same lead author); top-level structure is identical:
**scenery / environmental conditions / dynamic elements**. ASAM OpenODD 1.0.0 defines
*no taxonomy of its own* — it consumes the ISO 34503 vocabulary and adds measurement
attributes for value ranges.

### 2.1 Scenery (ISO 34503 §9)

| Attribute | Path | Type / units | Classes (normative where numeric) | Source |
|---|---|---|---|---|
| zone_type | scenery/zones | enum | fixed (school, environmental, industrial, parking lot), dynamic (traffic-management, mobile work), interference (urban canyon, overhead wires, dense foliage), port, freight centre; + geofenced_areas, region_or_state (shapefile) | ISO §9.2 |
| drivable_area_type | scenery/drivable_area | enum | motorways/highways; primary; radial; distributor; minor/local; slip roads/off-ramps; parking space; shared space — each ±active traffic management | ISO §9.3.2 |
| geometry_horizontal | …/geometry | enum + m | straight_lines; curves (curve radius: measurement attr, no normative bounds) | ISO §9.3.3 |
| geometry_transverse | …/geometry | enum | divided; undivided; pavements; barriers on edges; mixed lane types; superelevation/banking | ISO §9.3.3 |
| geometry_longitudinal | …/geometry | enum + % | up_slope / down_slope / level (gradient %: measurement attr) | ISO §9.3.3 |
| lane_dimensions | …/lane_specification | double, m | no normative bounds (examples: min 3.7 m; 2.6 m with trucks) + lane count (int) | ISO §9.3.4 |
| lane_marking | …/lane_specification | enum | clear; blurred; none; temporary | ISO §9.3.4 |
| lane_type | …/lane_specification | enum | bus; traffic; cycle; tram; emergency; shared; other special-purpose | ISO §9.3.4 |
| direction_of_travel | …/lane_specification | enum | right-hand; left-hand | ISO §9.3.4 |
| speed_limit | …/lane_specification | double, km/h | ODD-specific, no normative bounds | ISO §9.3.4 |
| signs | …/signs | enum | regulatory (incl. traffic lights); warning; information × movable/fixed | ISO §9.3.5 |
| edge | …/edge | enum | line markers; snowbanks; solid barriers (rails, curb, cones); temporary markers; none; shoulder: paved/gravel vs grass | ISO §9.3.6 |
| surface_type | …/surface | enum | asphalt; cement concrete; pavers; cobblestone; granite setts; gravel | ISO §9.3.7 |
| surface_features | …/surface | enum | damages (cracks, potholes, ruts, swells); artificial (speed bumps, speed-reduction obstacles) | ISO §9.3.7 |
| induced_surface_conditions | …/surface | enum | icy; flooded; standing water; snow on surface; wet; contamination (sand, leaves, debris, oil) | ISO §9.3.7 |
| **roundabout** | scenery/junctions | enum, ICD in m | **mini ≤ 28 m; compact 28–36 m; normal 36–100 m (island ≥ 4 m); large ≥ 100 m**; double; signalized / non-signalized ±yield | ISO §9.4.2 (bounds verbatim ASAM Annex B.3; UK DMRB lineage) |
| intersection | scenery/junctions | enum | T; Y; crossroad; staggered; grade-separated — each ±signalized | ISO §9.4.3 |
| basic_road_structures | scenery | enum | building; streetlight; street furniture (bollards); vegetation ("fixed road structures" in PAS 1883) | ISO §9.5 |
| special_structures | scenery | enum + m | barrier; bridge; pedestrian crossing; rail crossing; tunnel; toll plaza — dims (length/width/height/shoulder), usage on/under | ISO §9.6 |
| temporary_structures | scenery | enum | construction-site detour; refuse collection; road work; signage | ISO §9.7 |

### 2.2 Environmental conditions (ISO 34503 §10) — the quantitative core

| Attribute | Type / units | **Normative classes** | Source |
|---|---|---|---|
| ambient_air_temperature | double, °C | no normative classes (own clause since ISO 34503) | ISO §10.2.2 |
| **wind** | enum over m/s | no_wind 0; calm <0.2; light_air 0.3–1.5; light_breeze 1.6–3.3; gentle 3.4–5.4; moderate 5.5–7.9; fresh 8.0–10.7; strong 10.8–13.8; near_gale 13.9–17.1; gale 17.2–20.7; strong_gale 20.8–24.4; storm 24.5–28.4; violent_storm 28.5–32.6; **hurricane_force ≥ 32.7** (Beaufort 0–12) | ISO §10.2.3 |
| rainfall_type | enum | dynamic (frontal); convective (showery); orographic (relief) — Met Office genesis typology | ISO §10.2.4 |
| **rainfall_intensity** | enum over mm/h | no_rain 0; light < 2.5; moderate 2.5–7.6; heavy 7.6–50; violent 50–100; **cloudburst > 100** (AMS/international ladder, *not* Met Office radar classes) | ISO §10.2.4 |
| **snowfall_intensity** | enum over km visibility | light: vis ≥ 1 km; moderate: 0.5–1 km; **heavy: vis ≤ 0.5 km** (visibility-defined, not mm/h) | ISO §10.2.5 |
| particulates | enum | sand; dust; smoke/pollution; volcanic ash; water spray; **non-precipitating water droplets (mist/fog)**; blowing debris + intensity, particle size | ISO §10.3 |
| **natural_illuminance** | enum over lux | **day ≥ 2000 lx; low_ambient 1–2000 lx; night ≤ 1 lx** | ISO §10.4 |
| artificial_illumination | enum | streetlights; oncoming vehicle lights; indoor lights | ISO §10.4 |
| cloudiness | enum over oktas | clear 0–1; few 1–2; scattered 3–4; broken 5–7; overcast 8 (WMO okta scale) | ISO §10.4 |
| sun_position | double, deg | elevation + azimuth, continuous (this is how glare/low sun is expressed; no glare classes) | ISO §10.4 |
| connectivity | enum | V2V/V2I/V2P/V2N; cellular 2G–5G, satellite, 802.11p, DSRC/ITS-G5/PC5; positioning: GPS/Galileo/GLONASS/BeiDou/QZSS, RTK | ISO §10.5 |

Notes: fog sits under **particulates** with *no normative visibility bound* in either
standard — the < 1 km definition is the external WMO convention (as used by ATM-001).
Snow is the only phenomenon whose classes are visibility-defined; the illuminance ladder
(2000/1 lx) and okta ladder are ISO 34503's own.

### 2.3 Dynamic elements (ISO 34503 §11)

| Attribute | Type | Classes | Source |
|---|---|---|---|
| agent_type | enum | motor vehicle; non-motor vehicle; VRU (pedestrians, two-wheelers, bicycles, e-scooters; def. §3.5 adds motorcyclists, horse riders, reduced-mobility persons); animals | ISO §11.1 |
| agent_state | enum/rel. | stationary/moving; position relative to subject vehicle (e.g. lead-vehicle presence) | ISO §11.1 |
| traffic_density/flow | double | density (agents/distance), volume (agents past point/time), flow rate (agents/h) — continuous, **no normative class bounds** | ISO §11.1 |
| special_vehicles | enum | ambulance; police; work vehicles (fire engine, traffic management) | ISO §11.1 |
| subject_vehicle | double/bool | max_speed (km/h, ODD-specific — ISO example: 70 km/h dry vs 40 km/h rain); pre-defined routes; weight (kg) | ISO §11.2 |

PAS 1883 differences: "fixed/temporary road structures" naming; PAS 1883:**2025** is now
an implementation guide for ISO 34503 adding motor-vehicle-type and VRU attribute
extensions plus spatial/temporal wind & rainfall descriptions (paywalled; from BSI
abstract). Unverified against the PAS 1883:2020 PDF: its exact clause numbers and
whether its rain classes were worded as the Met Office slight/moderate/heavy instead of
the 2.5/7.6/50/100 ladder.

## 3. Simulator environment APIs

Sources: CARLA Python API docs (`weather.yml`, `control.yml`, `client.yml`, master =
0.9.15/0.9.16); ScenarioRunner OpenSCENARIO-support docs; esmini `osc_coverage.txt` +
user guide (v2.49.0) + release notes; SVL 2021.x Python API docs (archived); BeamNGpy
API reference.

### 3.1 CARLA `carla.WeatherParameters` (all fields)

| Field | Type / units | Range | Maps to OSC | Notes |
|---|---|---|---|---|
| cloudiness | float, % | 0–100 | fractionalCloudCover / cloudState | rendering only |
| precipitation | float, % | 0–100 | precipitationIntensity — **unit mismatch, no conversion** | rain particles only; does **not** wet the road |
| precipitation_deposits | float, % | 0–100 | ~wetness (no numeric map) | puddles at *static-noise* fixed locations |
| wind_intensity | float, % | 0–100 | Wind@speed (m/s) — unit mismatch | affects rain direction/leaves only |
| sun_azimuth_angle | float, **deg** | 0–360 | Sun@azimuth (**rad**) | degree/radian trap |
| sun_altitude_angle | float, **deg** | −90–90 | Sun@elevation (rad) | CARLA's only time-of-day control |
| fog_density | float, % | 0–100 | — (OSC has visualRange) | RGB camera only |
| fog_distance | float, m | 0–∞ | ~Fog@visualRange | fog *start* distance ≠ visual range |
| fog_falloff | float | 0–∞ | — | vertical extent (1 ≈ air density) |
| wetness | float, % | 0–100 | Wetness enum (no numeric map) | RGB camera only |
| scattering_intensity / mie_scattering_scale / rayleigh_scattering_scale | float | ≥ 0 | — | volumetric light |
| dust_storm | float, % | 0–100 | — (no OSC concept) | |

Vehicle side: `VehiclePhysicsControl` (mass kg, drag, torque curve RPM/Nm, MOI, gears,
CoM, steering curve), `WheelPhysicsControl` (tire_friction unitless ≈ 3.5 default,
radius in **centimeters**, max_steer deg, brake torques N·m, PhysX stiffness);
`WalkerControl.speed` m/s (AI default 1.4 m/s); TrafficManager percent-of-speed-limit
model (default 30% under; negatives exceed limit), `set_desired_speed` m/s, lane offset
sign **opposite** to OSC.

Documented decouplings (motivating profile packs, see catalog_report): weather affects
**only** `sensor.camera.rgb` — never physics, never lidar/radar; precipitation, deposits
and wetness are three independent scalars; friction changes only via per-wheel
`tire_friction` or `static.trigger.friction` boxes; ScenarioRunner applies
EnvironmentAction **at Init only**; CARLA cannot represent wall-clock date/time,
temperature, pressure, wind m/s, snow, DomeImage.

### 3.2 esmini (v2.49.0)

Consumes OSC natively; `osc_coverage.txt`: Environment **Yes** (from v2.49.0, 2025-06),
Weather "limited visualization", RoadCondition "**frictionScaleFactor only**" (wetness
accepted but unapplied), DomeImage No, TimeOfDayCondition No. TimeOfDay maps to sky
illuminance (00:00 → 0 lx, 12:00 → 100 000 lx); Sun azimuth/elevation parsed but "no
visual effect"; Sun illuminance drives sky color (100 000 = brightest blue sky);
fractionalCloudCover shifts sky blue→gray; fog visualRange visualized; Precipitation and
Wind parsed and forwarded to **OSI ground truth only** (no rendering, no physics).
OpenDRIVE lane `<material friction>` (v2.37.0) computed per wheel into OSI, visualized
(blue = slippery), scaled by frictionScaleFactor — but default controllers are kinematic
(friction is data-out).

### 3.3 SVL (LGSVL, archived 2022) and BeamNG.tech

SVL `WeatherState`: rain, fog, wetness, cloudiness, damage — each unitless 0–1
(wetness decoupled from rain, same pattern as CARLA); `time_of_day` 0–24 h with real
sun-position computation from date. BeamNG.tech: physics always coupled (soft-body) but
environment exposed only as opaque **weather presets** + time-of-day scalar 0–1 (0/1 =
midday, 0.5 = midnight — inverted convention) + settable gravity; no scalar fog/rain
API. (AWSIM rejected: no comparable documented weather API.)

## 4. Open scenario corpora feature schemas

Sources: DeepScenario repo + MSR 2023 paper (Lu, Yue, Ali); asam-oss/OSC-ALKS-scenarios;
esmini resources/xosc; carla-simulator/scenario_runner examples; Safety Pool SDL docs.

- **DeepScenario** (33 530 scenarios, custom `.deepscenario` XML on SVL+Apollo): 0.5 s
  waypoint trajectories with full 3D velocity **and angular velocity** per waypoint,
  Unity y-up frame, Euler **degrees**; GPS (lat/lon/alt + UTM); weather referenced to a
  real **OpenWeather database** by unix timestamp (directory-encoded rain/sunny ×
  day/night); per-scenario oracle labels TTC, DTO, jerk, collision type,
  speed-at-collision; ego marked via `ObjectType=Ego`, RGB color vectors, simulator asset
  GUIDs.
- **OSC-ALKS** (15 templates + 15 ParameterValueDistribution variations, OSC 1.3.1):
  parameter naming convention `<Actor>_<Quantity>_<Symbol>_<unit>` (units in *names*:
  `_kph`, `_mps2`); **plausibility bounds inside scenarios** as ValueConstraintGroups
  (e.g. lateral velocity < resultant speed/3.6, relative speed > −ego speed);
  cross-parameter constraint expressions; catalogs for all entities; no Environment use.
- **esmini resources** (~79 files, revMinor 0–3): broadest OSC action coverage —
  trajectories (polyline/clothoid/spline), SynchronizeAction, SpeedProfileAction,
  TrafficSwarmAction (radii, numberOfVehicles, velocity), VisibilityAction
  (graphics/sensors/traffic), controller overrides, trailers (1.3), light states (1.2),
  environment showcase file with full OSC 1.3 Weather.
- **ScenarioRunner examples** (OSC 1.0): deprecated vocabulary in the wild (cloudState,
  unitless sun `intensity` 0.85→0.05 day→night, intensity 0–1 precipitation); simulator
  contract smuggled through `Properties` (module=external_control, type=ego_vehicle,
  RGB color); the shipped `maxAcceleration="200"` defect (see first_findings.md).
- **Safety Pool** (250 k+ scenarios, WMG/Deepen): SDL Level 2 DSL; full field list gated,
  but exports to OSC 1.1 + OpenDRIVE 1.6 and is taxonomy-aligned with ISO 34503 — the
  ISO attribute vocabulary is its schema proxy.

### Attributes real corpora express that OSC 1.x lacks natively

1. 3D velocity / **angular velocity** initialization and per-waypoint kinematic state
   (DeepScenario).
2. Geographic positions in the scenario file itself (lat/lon/UTM) — OSC 1.x has no
   GeoPosition; georeferencing lives in OpenDRIVE.
3. Weather-by-reference to recorded real data (OpenWeather DB + timestamp).
4. Ego designation, control-stack binding, vehicle color — via untyped `Properties`
   conventions.
5. Simulator asset identity (GUIDs, blueprint ids like `vehicle.tesla.model3`).
6. Units embedded in parameter *names* + cross-parameter value constraints (ALKS).
7. Outcome/oracle labels (TTC, DTO, jerk, collision) — OSC has trigger conditions, no
   result vocabulary.
8. Road damage scalar (SVL), dust storms (CARLA), gravity (BeamNG).

## 5. physcheck canonical attribute vocabulary (v0.1)

The flat names rules are written against (`physcheck.ir.attributes`); each maps 1:1 to
an OSC source above. Absent information = absent key (docs/decisions.md D7).

| Canonical name | Type/units | OSC source | Notes |
|---|---|---|---|
| `osc.version` | str | FileHeader revMajor.revMinor | |
| `env.present` | bool | Environment declared | one context per environment state |
| `env.time.iso` / `env.time.hour` / `env.time.month` | str / h / int | TimeOfDay@dateTime | timezone undefined → D5 |
| `env.cloud.state` | enum str | Weather@cloudState (≤1.1) | |
| `env.cloud.oktas` | float 0–9 | Weather@fractionalCloudCover (1.2+) | enum → oktas |
| `env.temperature_k` / `env.temperature_c` | K / °C | Weather@temperature (1.1+), range [170..340] K | |
| `env.pressure_pa` | Pa | Weather@atmosphericPressure (1.1+), [80000..120000] | |
| `env.sun.azimuth_rad` | rad [0..2π] | Sun@azimuth (0=N, π/2=E) | |
| `env.sun.elevation_rad` | rad [−π..π] schema | Sun@elevation | physics: [−π/2..π/2] (SOL-001) |
| `env.sun.illuminance_lux` | lux ≥ 0 | Sun@illuminance (1.2+) / @intensity (≤1.1, lux per spec) | D13 |
| `env.fog.present` | bool | Fog element | corpus uses as visibility carrier → D8 |
| `env.fog.visual_range_m` | m ≥ 0 | Fog@visualRange | |
| `env.precip.type` | dry\|rain\|snow | Precipitation@precipitationType | |
| `env.precip.intensity01` | [0..1] | @intensity (1.0, deprecated 1.1) | no mm/h mapping → D6 |
| `env.precip.intensity_mmh` | mm/h ≥ 0 | @precipitationIntensity (1.1+) | |
| `env.wind.speed_mps` / `env.wind.direction_rad` | m/s / rad | Wind (1.1+) | |
| `env.road.friction_scale` | >0, dry ref μ≈0.9 | RoadCondition@frictionScaleFactor | |
| `env.road.wetness` | enum | RoadCondition@wetness (1.2+): dry\|moist\|wetWithPuddles\|lowFlooded\|highFlooded | |
| `entity.name` / `entity.kind` / `entity.category` | str | ScenarioObject; Vehicle/Pedestrian/MiscObject categories | |
| `entity.length_m` / `width_m` / `height_m` | m > 0 | BoundingBox/Dimensions | |
| `entity.mass_kg` | kg > 0 | Vehicle/Pedestrian@mass | |
| `entity.max_speed_mps` / `max_accel_mps2` / `max_decel_mps2` | m/s, m/s² ≥ 0 | Performance | |
| `entity.initial_speed_mps` | m/s | Init SpeedAction AbsoluteTargetSpeed | |
| `entity.max_target_speed_mps` | m/s | max(initial, story absolute speed targets) | |
| `entity.max_speed_change_rate_mps2` | m/s² | SpeedActionDynamics dimension=rate | |
| `entity.min_lane_change_time_s` | s | LaneChangeActionDynamics dimension=time | |
| `scenario.max_speed_mps` | m/s | max over all entities | |

**Out-of-vocabulary in v0.1** (union members with no OSC 1.x carrier): humidity, dew
point, fog LWC/droplet spectrum, extinction coefficient, non-fog visibility, phenomenon
labels (mist/haze/freezing-rain), road surface *type* and damage, gradient/curvature
(OpenDRIVE, L2), geodetic location (OpenDRIVE geoReference, L2), traffic
density classes, connectivity state, angular velocity, oracle labels. These bound what
the catalog can check (see catalog_report "not encodable" tables) and define the
extension surface for L2+ and for non-OSC frontends of the IR.
