# Catalog report — how the physcheck rule catalog was derived

**Version 0.1.0 · 2026-07-20**

This document records the research phase behind `physcheck/catalog/*.yaml`: the sources
mined per physical domain, how candidate constraints became machine-checkable rules, the
threshold decisions taken, candidates that are **not encodable** over the OpenSCENARIO 1.x
attribute vocabulary (kept for the L2+ roadmap), and — per the project's ground rule that
nothing is dropped silently — a full **rejected appendix** of candidates that could not be
grounded in a citable source.

Method: for each attribute group of `docs/attribute_space.md` with a plausible physical or
statistical dependency, the primary literature was mined (atmospheric optics and
meteorology, tire–road friction, vehicle dynamics, solar geometry and photometry,
precipitation microphysics, road-user biomechanics, vehicle regulations). Each validated
relationship became a rule with `id`, `layer`, `severity` (`error` = physically
impossible, `warning` = implausible/never observed, `info` = notable), a predicate over
the canonical attribute vocabulary, units, and a full citation. Every shipped rule is
covered by a violating fixture under `physcheck/tests/fixtures/violating/<ID>.xosc`.

Severity philosophy: `error` is reserved for violations of definitional identities,
normative schema ranges, record extremes (WMO-ratified or equivalently documented), or
hard physical limits (μg friction bound, luminous solar constant, homogeneous freezing).
Class boundaries, climatological 95% ranges, and capability envelopes are `warning`.

---

## Atmosphere & visibility (`atmosphere.yaml`, ATM-001…007)

Primary sources: Koschmieder (1924) via Middleton, *Vision Through the Atmosphere* (1952);
WMO-No. 8 Vol. I Ch. 9 (MOR, contrast threshold ε=0.05); AMS Glossary (fog/mist
definitions); Penndorf (1957, JOSA — Rayleigh scattering of pure air); Atlas (1953, J.
Meteor. — rain extinction σ = a·R^b); Rasmussen et al. (1999, JAM — snow visibility);
Pruppacher & Klett (1997 — homogeneous freezing); CIE S 011/E:2003 + IESNA Handbook +
Littlefair (1985) for overcast illuminance; Gultepe et al. (2007, PAGEOPH review).

Key decisions:
- **ATM-001 is a warning, not an error.** WMO/AMS define fog as visibility < 1 km, but
  corpus practice (esmini, CARLA ScenarioRunner) uses the `Fog` element as the *generic
  visibility carrier*, with `visualRange` up to 100 km meaning "clear". Flagging that as
  an error would fail most real suites on an idiom; as a warning it still surfaces the
  brief's flagship "dense fog with unlimited visibility" pattern. See decisions.md D8.
- ATM-003/004 use the *weakest-extinction* published coefficients with an extra 2×/10×
  tolerance, so only unambiguous contradictions fire.
- Illuminance-vs-elevation and below-horizon checks live in `solar.yaml` (SOL-005/006)
  because the OSC field is Sun illuminance, not ambient illuminance.

Not encodable over OSC 1.x attributes (no humidity, dew point, LWC, droplet number,
extinction, or phenomenon labels in the schema) — retained for future layers/formats:
- Fog requires RH ≥ ~90% (NWS fog guide; Cuxart et al. 2021).
- Mist/haze RH discrimination (Met Office practice, RH ≈ 95% boundary).
- Koschmieder closure V·β ∈ [3.0, 3.912] (needs declared extinction).
- Kunkel (1984) LWC–visibility and Gultepe et al. (2006) LWC·Nd–visibility closures.
- Geometric-optics extinction β = 3·LWC/(2·ρ_w·r_eff) (Petty 2006).
- Fog dew-point spread ≤ 2.5 °C (NWS); freezing-fog typing at T ≤ 0 °C (METAR FZFG).
- Rain-only visibility floor ~100 m (needs a visibility attribute independent of Fog).
- Class-label consistency rules (heavy rain > 7.6 mm/h etc.) — OSC has no label fields;
  the numeric class bounds are used in PRE-003 instead.

Rejected (uncitable / unsound — reasons verbatim from the research pass):
1. *Fog impossible above N m/s wind* — radiation fog needs light wind but advection/sea
   fog persists at 10+ m/s (Gultepe et al. 2007); no single threshold exists.
2. *Surface rain implies RH ≥ 0.5* — no authoritative quantitative surface-RH floor for
   rain reaching the ground.
3. *Dense fog + heavy rain impossible (error)* — precipitation/frontal fog genuinely
   co-occurs with rain (Tardif & Rasmussen 2007); kept only as a mechanism-restricted
   warning candidate (radiation fog), itself not encodable (no fog-type attribute).
4. *Kruse/Kim wavelength-exponent haze relations* — restatement of Koschmieder plus a
   wavelength scaling irrelevant to broadband visual range.
5. *Time-of-day vs sun-elevation without location* — polar day breaks any latitude-free
   version; kept only as the guarded night-hours warning SOL-007.
6. *Radiation fog restricted to night hours* — strong climatological tendency but daytime
   winter persistence is common; no defensible hard window.
7. *Illuminance as a continuous function of cloud fraction* — transmittance depends on
   cloud type/optical depth, not fraction alone; only the binary overcast bound (ATM-006)
   is defensible.
8. *Snow visibility floor (~50 m)* — factor-10 scatter in Rasmussen et al. plus the
   blowing-snow confound.
9. *Moon-phase vs night illuminance* — no moon attributes in any scenario schema.

## Solar geometry & illumination (`solar.yaml`, SOL-001…008)

Primary sources: Meeus, *Astronomical Algorithms* 2nd ed. (1998) Chs. 7/12/13/15/16/22/25/28;
Reda & Andreas (2004, Solar Energy — NREL SPA, ±0.0003°); NOAA GML solar calculator
(Meeus-based, ±0.0167°); Bennett (1982, J. Navigation — refraction); USNO twilight
definitions; Darula, Kittler & Gueymard (2005, Solar Energy — luminous solar constant
133.8 klx); IES daylight-availability model (1984); Kyba, Mohar & Posch (2017 — moonlight);
Spencer (1971) declination series.

Key decisions:
- OSC 1.x does not define the timezone of `TimeOfDay@dateTime` and `.xosc` carries no
  geodetic position (that lives in the OpenDRIVE `geoReference`, an L2 input). All
  **location-dependent** consistency rules are therefore documented here but deferred:
  declination-bound check sin δ = sin φ sin h + cos φ cos h cos A with |δ| ≤ 23.44°
  (date-free!), max-elevation bound h ≤ 90° − max(0, |φ| − 23.44°), full
  elevation/azimuth-vs-ephemeris checks with min-over-{UTC, local±DST} interpretation and
  0.7° warning / 5° error tolerances, noon-azimuth and midnight-sun checks. These form the
  planned `solar_geo` L2 pack; the pure-Python Meeus/NOAA algorithm chain (Julian day →
  solar coordinates → equation of time → hour angle → elevation/azimuth, with Saemundsson/
  Bennett refraction) is specified in the research notes and is implementable without
  dependencies (accuracy 0.01°, far tighter than the 0.57° refraction-dominated
  tolerance; the full ~2300-line NREL SPA is unnecessary — cited as the cross-validation
  standard).
- SOL-007/008 (night-hours checks) assume `dateTime` ≈ local time and are warnings only
  (decisions.md D5).
- The sun-illuminance ceiling uses the luminous solar constant (133.8 klx, error) plus a
  120 klx plausibility warning; an "ambient illuminance ≤ 200 klx incl. cloud-edge
  enhancement" variant was superseded because the OSC field is *sun* illuminance.

Rejected:
1. *Azimuth rotation-direction rule* — the ASAM 1.0 Sun doc says azimuth is "counted
   counterclockwise" yet enumerates 0=north, π/2=east, π=south (clockwise from above);
   spec self-contradiction, ungroundable. The explicit enumeration (compass) is trusted.
2. *Fixed twilight illuminance thresholds (e.g. civil twilight = 3.4 lx)* — widely quoted
   figures lack a single authoritative primary source; only angular definitions kept.
3. *Hard lower illuminance bound vs elevation* — overcast/fog/eclipse attenuate >20×
   with no universal floor; kept only as a guarded low-confidence warning candidate (not
   encoded — needs clear-sky knowledge).
4. *Sun color temperature vs elevation* — no CCT field in OSC.
5. *UTC-vs-local disambiguation as its own rule* — no citable normative statement.
6. *Quantitative sun-illuminance attenuation from fog/cloud attributes* — no validated
   transfer model.
7. *Standalone equation-of-time bound* — subsumed by the deferred ephemeris check.
8. *Moonlight/starlight night floor* — moon state unobservable in the schema.

## Precipitation & thermodynamics (`precipitation.yaml`, PRE-001…017)

Primary sources: Met Office Fact Sheet 3 + WMO aviation-hazards intensity classes; AMS
Glossary (rain classes 2.5/7.6 mm/h; serein); Lott (1954, MWR — Holt 42-min record);
US Weather Bureau (1959, MWR — Unionville 1-min record) + WMO Extremes Archive;
Rasmussen et al. (1999 — snow rates); Cortinas et al. (2004, WAF — freezing rain);
Lu et al. (2022, JGR-A); Jennings et al. (2018, Nat. Commun. — rain–snow threshold);
Auer (1974, Weatherwise); WMO-No. 407 Cloud Atlas (precipitation requires cloud);
WMO Beaufort equivalents; Coleman & Baker (1994, JWEIA — crosswind); Courtney et al.
(2012 — record gust); WMO extremes archive (temperature records).

Key decisions:
- Phase-vs-temperature: warning at snow > 2.4 °C (Jennings 95% range), error at snow >
  6.1 °C (Auer: ~0% snow probability; rare desert-dry exceptions need humidity, which
  OSC cannot declare — noted in the rule message). Rain: warning < 0 °C (freezing rain),
  error < −12 °C (conservative cut below the documented freezing-rain tail).
- OSC 1.0's unitless intensity ∈ [0,1] has **no principled mm/h mapping** (see rejected
  list); rules therefore branch on which intensity attribute is present, and mm/h-based
  rules never fire on 1.0-style files.
- Wind thresholds: info at 17.5 m/s (control difficulty), warning at 32.7 m/s (Beaufort
  12), error at 113.3 m/s (WMO record gust).
- Duplicates across domains were merged: snow-at-warm-temperature appeared in three
  research streams (Auer cited by all); it ships once as PRE-010/011. The freezing-rain
  friction consequence ships as FRI-021; the phase implausibility as PRE-008/009.

Rejected:
1. *Principled mapping of OSC 1.0 intensity [0,1] to mm/h* — no normative or
   peer-reviewed calibration exists; CARLA's 0–100 "precipitation" is explicitly a visual
   parameter (Tremblay et al., IJCV 2021, built a physically parameterized renderer
   precisely because engine sliders are uncalibrated). Only a round-trip consistency
   check would be defensible, and it needs simulator-side attributes.
2. *Precipitation requires ≥ 6 oktas (error)* — no published okta threshold conditional
   on precipitation; kept as the weaker PRE-013 warning (≥10 mm/h with <4 oktas).
3. *Serein as a clear-sky-rain exemption* — AMS labels it "doubtful"; does not license
   cloud-free precipitation.
4. *RH ≥ 95% required during rain (error)* — contradicted by observation (rain onset at
   ~72% RH, LIAISE campaign); RH is anyway absent from OSC.
5. *Exact minimum temperature for freezing rain* — no ratified record minimum; −12 °C is
   a conservative synthesis (PRE-009), sharper bounds uncitable.
6. *Separate sustained-wind record cap* — WMO ratifies only the 3-s gust record; used as
   the absolute cap.
7. *Visibility-derived snow classes as hard rules* — factor 1.5–2 scatter; label fields
   absent from OSC.
8. *Jurisdictional wind closure limits* — administrative, not physical.
9. *Minimum humidity during snowfall* — snow legitimately reaches ground in very dry air.
10. *Guadeloupe 38 mm/min as instantaneous ceiling* — not WMO-ratified; Unionville used.
11. *Hail constraints* — no hail type in the OSC PrecipitationType enum.
12. *Clausius–Clapeyron max-rain-vs-temperature scaling* — needs column moisture, not 2-m
    attributes.

## Friction & road surface (`friction_road.yaml`, FRI-001…023)

Primary sources: Bosch *Automotive Handbook* 4th ed. p. 330 (friction tables incl. water
film columns); Warner et al. (SAE 830612 — accident-reconstruction drag factors); Hall et
al. (NCHRP Web Doc 108 — pavement friction guide); Wallman & Åström (VTI Meddelande 911A
— winter friction); Horne & Dreher (NASA TN D-2056 — hydroplaning, V_p = 9√p); Gallaway
et al. (FHWA-RD-79-31 — water film); Anderson et al. (PAVDRN, TRR 1599); Kummer & Meyer
(NCHRP Report 37 — friction–speed); Gillespie (SAE R-114 — μg bounds); Pacejka (2012);
UN R13-H / R13 (braking type-approval); ISO 15622 (ACC deceleration limits); Ketcham et
al. (FHWA-RD-95-202 — anti-icing, NaCl eutectic); Cortinas et al. (2004); Auer (1974);
Bokare & Maurya (2017, TRP — field accel/decel).

Key decisions:
- The dry reference μ is 0.9, so `frictionScaleFactor` ≈ μ/0.9; the friction-circle
  rules (FRI-013/023) include a 10 % tolerance absorbing road grade up to ~6 % and ABS
  peak utilization.
- FRI-011 needs the scenario-wide maximum speed; the attribute view provides
  `scenario.max_speed_mps` = max over entities of initial/commanded speeds.
- Acceleration absolute caps were reconciled across research streams: the friction
  stream proposed error > 10.5 m/s², the kinematics stream error > 13 m/s² (record EV
  launches peak ~1.2–1.3 g). Resolution: **error at 13** (beyond any production vehicle,
  KIN-018), warning at 9 (car, KIN-019); the friction-coupled bound FRI-023 handles the
  surface-conditional case. Deceleration: error at 11.8 m/s² (1.2 g, KIN-014).
- Comfort/ACC deceleration ≤ 3.5 m/s² (ISO 15622) is *not* encodable: OSC does not mark
  a braking action as "comfort" vs "emergency". Documented for L4 storyboard analysis.
- Cross-environment wetness/friction monotonicity (drier state must not have lower
  friction than wetter state *within one scenario*) needs cross-context comparison the
  v0.1 engine does not do; deferred.

Rejected:
1. *Exact Gallaway water-film computation* — needs cross-slope, drainage length, texture
   depth; none are OSC attributes.
2. *Hydroplaning speed from tire pressure* — tire pressure not declared; folded into
   FRI-011 at 240 kPa typical (note: NASA TN D-2056 derives from aircraft tires;
   car extrapolation is standard practice per FHWA-RD-79-31 but adds uncertainty).
3. *Minimum rain duration before dry→wet transition* — no validated closed-form wetting
   time; road-weather models (METRo; Crevier & Delage 2001) treat it as an energy-balance
   simulation.
4. *Studded-tire/chain friction uplift* — tire equipment not declared.
5. *Wet friction vs water temperature* — a few percent per 10 °C, inconsistent across
   studies, below lint resolution.
6. *Lateral-acceleration comfort bound / friction-circle over trajectories* — needs
   curvature and speed profiles (L3, map-dependent).
7. *Grade-adjusted deceleration bound* — grade not declared; absorbed in the 10 %
   tolerance.
8. *Air-temperature ↔ road-surface-temperature identity* — RWIS literature (Norrman
   2000; Shao & Lister 1996) shows several-°C divergence either way; rules use
   conservative air-temperature margins instead.
9. *Precipitation intensity cap ~200 mm/h (friction stream)* — superseded by the
   record-based PRE-004/005.
10. *R13-H minimum as error* — a scenario may legitimately model a degraded vehicle;
    warning (FRI-014).
11. *Bosch table cited to current edition* — only the 4th ed. (1996, p. 330) pagination
    could be verified; cited to the verified edition.

## Kinematics & road users (`kinematics.yaml`, KIN-001…024)

Primary sources: Krzysztof & Mero (2013, J. Hum. Kinetics) + Graubner & Nixdorf (2011) —
sprint records; Weyand et al. (2000, JAP); Bohannon (1997, Age & Ageing — walking
speeds); di Prampero et al. (2005, JEB — sprint acceleration); IHPVA/WHPSC records —
bicycle; Schleinitz et al. (2017, Safety Science — naturalistic cycling); Kutsch et al.
(2025, TRR) + Parkin & Rotheram (2010) — cyclist acceleration; Usherwood & Wilson (2005,
Nature) + Sharp (1997, J. Zool.) — animal speeds; production-car speed/acceleration
records; Directive 92/6/EEC — heavy-vehicle limiters; UNECE R13; Wilson & Schmidt,
*Bicycling Science* (2020); Toledo & Zohar (2007, TRR 1999 — lane-change durations);
Bokare & Maurya (2017); ASAM model documentation (Performance semantics, KIN-023).

Key decisions:
- Pedestrian "running" (>3 m/s) is `info`, not warning: running pedestrians are plausible
  and common in test scenarios; the class boundary is still worth surfacing.
- Car maxSpeed warning threshold set at 100 m/s (360 km/h — beyond all but a handful of
  hypercars) rather than the 70 m/s limiter value proposed in research, to avoid false
  positives on legitimate sports-car models; the error stays at 140 m/s (record 136.25).
- Pedestrian acceleration uses commanded SpeedAction *rates* (OSC pedestrians have no
  Performance element).
- The implied-lateral-acceleration lane-change check (2·w/t² with lane width w) needs the
  map lane width; subsumed into the duration thresholds (KIN-021/022) with the 3.5 m
  standard-lane computation given in the message; exact version deferred to L3.
- KIN-023 (commanded speed > declared maxSpeed) is a definitional self-contradiction of
  the scenario, severity error, cited to the ASAM Performance semantics.

Not encodable in OSC 1.x: elderly/child pedestrian sub-envelopes (no age subtype);
e-bike class caps (no propulsion attribute); wheelchair regulatory caps (subtype support
inconsistent across OSC versions — candidate retained pending reliable attributes).

Rejected:
1. *Single global vehicle maxSpeed cap* — not per-category; adds nothing over KIN-011/013.
2. *Pedestrian minimum-speed floor* — standing/dwelling valid; no defensible bound.
3. *Pedestrian-vs-cyclist relational check* — contextual, not a per-entity bound.
4. *UCI Hour Record as cyclist cap* — a sustained average, not an instantaneous ceiling.
5. *Power-limited acceleration check* — engine power not an OSC attribute.
6. *Lane-change upper-duration bound (>13 s)* — behavioral, not physical; long tail real.
7. *Bolt block-start 1 g as standalone error* — brittle; kept only as the KIN-004 tier.
8. *E-bike motor-power limits* — power unobservable; speed-cap proxy also unencodable.
9. *Per-exotic-species animal bounds* — subtypes rarely declared; cheetah ceiling kept.
10. *maxDeceleration < 3 m/s² implausibility* — degraded vehicles legitimate; only the
    heavy-vehicle regulatory minimum (KIN-016) is defensible.
11. *Bounding-box density check (mass/volume)* — box volume is mostly air; meaningless.
12. *Wheelchair speed caps* — see above; promote when subtype+propulsion are reliable.

## Entities (`entities.yaml`, ENT-001…013)

Primary sources: Council Directive 96/53/EC (+2002/7/EC) — dimensions and weights; UNECE
R13; Regulation (EU) 2018/858 (M1 ≤ 3.5 t); Guinness (Wadlow 2.72 m); CDC/NHANES + ISO
7250 anthropometry; EN ISO 4210 bicycle geometry.

Key decisions:
- Width error at 2.60 m (not 2.55) to avoid false positives on refrigerated bodies.
- Height error at 4.95 m (tallest operating double-deckers), warning at the EU 4.0 m cap
  — the US legal 4.11 m and unregulated jurisdictions make 4.0 m too strict for error.
- Bicycle bbox height rule dropped: cyclist models often include the rider (esmini
  cyclist ~1.7 m tall); a bicycle-only height bound would false-positive.
- Pedestrian mass bound dropped (no comfortable citation for an upper bound below the
  documented ~600 kg medical extremes); only the schema positivity check ships (SCH-114).

## Schema ranges (`schema_ranges.yaml`, SCH-101…114, layer L0)

Normative ranges and enums quoted from the ASAM OpenSCENARIO model documentation
(1.0.0 through 1.3). Structural L0 checks — XML well-formedness, FileHeader presence,
supported revMajor, dangling `entityRef`s, unresolved `$parameters`, unparseable numeric
literals and dateTimes, unresolved CatalogReferences — are Python plugin rules
(`physcheck.engine.plugins.l0_structure`, ids SCH-001…0xx) because they need document
structure, not the attribute view.

---

## Cross-cutting: not encodable in v0.1 (roadmap)

| Candidate | Needs | Target layer |
|---|---|---|
| Solar ephemeris consistency (elevation/azimuth vs dateTime+lat/lon) | OpenDRIVE geoReference | L2 (`solar_geo` pack) |
| Declination bound sin δ from (φ, h, A) | geoReference | L2 |
| Friction circle v² ≤ μgr over route curvature | OpenDRIVE geometry | L3 |
| Lane-change lateral acceleration with true lane width | OpenDRIVE lanes | L3 |
| Comfort vs emergency braking classification (ISO 15622 ≤ 3.5 m/s²) | storyboard intent analysis | L4 |
| Wetness/friction monotonicity across multiple environments | cross-context engine support | L1 (engine v0.2) |
| RH/dew-point/LWC/extinction closures | attributes absent from OSC 1.x | format extension |
| Simulator-coupling vacuity (e.g. CARLA weather is rendering-only; precipitation ≠ wet road; esmini ignores wetness) | simulator-profile packs | L6/profiles |

The simulator research stream (CARLA, esmini, SVL, BeamNG) also documented decoupling
traps that motivate *profile* rule packs: CARLA's `precipitation`,
`precipitation_deposits` and `wetness` are three independent scalars affecting only the
RGB camera (weather never changes physics; friction changes only via per-wheel
`tire_friction` or trigger boxes); esmini parses Wind/Precipitation but only forwards
them to OSI (no physics), applies `frictionScaleFactor` only, and ignores `wetness`;
ScenarioRunner honors EnvironmentAction at Init only. A scenario whose *test oracle*
relies on weather→dynamics causality in these engines is physically vacuous even if it
lints clean — that check belongs to a future engine-profile tier, not to the
engine-agnostic L1 catalog.

## Corpus-motivated evidence

The dataset research stream verified a real in-the-wild instance of the class of defect
this catalog targets: CARLA ScenarioRunner's shipped examples declare
`maxAcceleration="200"` m/s² (~20 g) for all vehicles (`FollowLeadingVehicle.xosc`,
`ChangingWeather.xosc`) — caught by KIN-018. The ASAM OSC-ALKS corpus, conversely,
encodes plausibility bounds *inside* scenarios as ValueConstraintGroups (e.g. lateral
velocity < resultant speed/3.6) — a ready-made source of future rules. Literature
critiquing generated-scenario realism (Reality Bites, FORGE 2024; SaFeR; Autom. Softw.
Eng. 2025 synthetic-vs-real analysis; arXiv 2606.11989 on uncalibrated rain intensity)
confirms both the prevalence of physically infeasible generated scenarios and the absence
of a standard realism oracle — the gap this catalog addresses with citable, deterministic
checks.
