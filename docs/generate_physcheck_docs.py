#!/usr/bin/env python3
"""Generate docs/physcheck.html — the practitioner reference — from the live
rule catalog, so the documentation can never drift from the code.

    python3 docs/generate_physcheck_docs.py     # from the repo root

Re-run on every release (rule counts, predicates and citations are read from
the installed packs and plugin registries).
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "physcheck" / "src"))

from physcheck import __version__  # noqa: E402
from physcheck.engine.catalog import load_default_packs  # noqa: E402
from physcheck.engine.plugins import (  # noqa: E402
    l0_structure, l1_cross, l2_map, l2_solar_geo,
    l3_kinematics, l4_storyboard, l5_odd, l6_statistical,
)

e = html.escape

# ── plain-language pack introductions ───────────────────────────────────────

YAML_PACK_META = {
    "schema_ranges": ("L0 · Schema & ranges", "Value sanity, one attribute at a "
        "time: is each number inside the range that is physically meaningful at "
        "all (temperature between 170 and 340 K, pressure between 800 and "
        "1200 hPa, no negative visual range)? These checks need no cross-"
        "reasoning — they catch typos, wrong units and placeholder values."),
    "atmosphere": ("L1 · Atmosphere", "Atmospheric optics and thermodynamics: "
        "fog versus visual range, cloud cover versus sunlight, temperature "
        "versus pressure. Derived from meteorology and atmospheric-optics "
        "literature."),
    "precipitation": ("L1 · Precipitation", "Rain and snow microphysics: "
        "precipitation type versus temperature, intensity versus cloud state, "
        "wind extremes. The classic catch: snowfall at +30 °C."),
    "friction_road": ("L1 · Road friction", "The precipitation → wetness → "
        "friction chain: what tire–road friction is possible on the declared "
        "surface, and what braking/acceleration that permits. Grounded in "
        "vehicle-dynamics handbooks (Pacejka, Gillespie, Bosch) and road-"
        "friction measurement studies."),
    "kinematics": ("L1 · Kinematics", "Motion envelopes per road-user class: "
        "how fast a pedestrian, cyclist, car or truck can go, accelerate, "
        "brake and change lanes — each bound cited to biomechanics, records "
        "or regulation."),
    "solar": ("L1 · Solar", "Internal consistency of the declared sun: "
        "elevation versus illuminance versus time of day, without needing a "
        "map (map-anchored sun geometry lives in L2)."),
    "entities": ("L1 · Entities", "Physical plausibility of the actors "
        "themselves: bounding-box dimensions, masses and performance limits "
        "per category — no 5 m-long pedestrians, no 1 kg trucks."),
    "version_gating": ("L0 · Version gating", "Attributes used before the "
        "OpenSCENARIO revision that introduced them (e.g. "
        "precipitationIntensity needs ≥ 1.1) — silent portability bugs "
        "between simulators."),
}

PLUGIN_PACKS = [
    ("plugin-l0", "L0 · Structural checks (plugin)", l0_structure.PLUGIN_RULES,
     "Checks that need the document structure rather than attribute values: "
     "well-formedness, header completeness, dangling references, unresolved "
     "parameters. Implemented over the parser's issue stream — the parser "
     "never throws; everything it cannot interpret becomes a finding here."),
    ("plugin-l1", "L1 · Cross-state checks (plugin)", l1_cross.PLUGIN_RULES,
     "Consistency across multiple declared environment states of one scenario "
     "— relationships no single-state predicate can express."),
    ("plugin-map", "L2 · Map cross-checks", l2_map.PLUGIN_RULES,
     "The scenario against its OpenDRIVE map. physcheck ships its own "
     "dependency-free map frontend: road reference lines (line / arc / spiral "
     "/ polynomial geometry, sampled at ~0.5 m), lane sections with types and "
     "widths, road/junction connectivity, speed records and the geodetic "
     "anchor. Positions are resolved to world coordinates exactly as a "
     "simulator would."),
    ("plugin-geo", "L2 · Solar geometry", l2_solar_geo.PLUGIN_RULES,
     "The declared sun against a built-in NOAA/Meeus solar ephemeris "
     "(accurate to ~0.01°, validated against the NOAA calculator) at the "
     "map's geodetic anchor: is this sun position possible at this latitude "
     "at all, and does it match the declared date and time?"),
    ("plugin-dyn", "L3 · Kinematic feasibility", l3_kinematics.PLUGIN_RULES,
     "Motion against tire physics and the map, with the friction ceiling "
     "composed from the L1 environment (layers compose: 9 m/s² braking is "
     "valid on dry asphalt, impossible on a flooded road). Trajectories are "
     "analysed with windowed estimators (≥ 0.4 s) so position quantisation "
     "in recorded data cannot fabricate phantom accelerations, and teleport "
     "segments split a trajectory rather than contaminating the statistics "
     "around them."),
    ("plugin-stb", "L4 · Storyboard logic", l4_storyboard.PLUGIN_RULES,
     "Static analysis of the scenario's control flow — acts, events, "
     "triggers. Deliberately conservative: every rule fires only on "
     "statically certain defects, with trigger timing computed from "
     "simulation-time conditions including their delay attribute."),
    ("plugin-odd", "L5 · ODD conformance", l5_odd.PLUGIN_RULES,
     "Scenario attributes against a YAML ODD definition using OpenODD-style "
     "include/exclude conditions. Verdict per constrained attribute: in / "
     "out / undeclared — out-of-ODD is an error, undeclared a warning "
     "(conformance cannot be established for unspecified conditions)."),
    ("plugin-sta", "L6 · Statistical plausibility", l6_statistical.PLUGIN_RULES,
     "The scenario's environmental assignment scored under a learned "
     "operational model (odd-pilot's Bayesian network). The verdict is the "
     "scenario's quantile within the model's own reference distribution — "
     "combinations real operation essentially never offers are flagged. "
     "Warnings only: statistical rarity never blocks execution."),
]

#: id -> one-sentence "how it decides", for plugin rules (YAML rules carry
#: their predicate instead).
HOW = {
    "SCH-001": "The XML failed to parse as an OpenSCENARIO document (including wrong-case root elements, which are flagged but still parsed).",
    "SCH-002": "FileHeader is absent or lacks the mandatory revision attributes.",
    "SCH-003": "revMajor is not a supported major revision (1.x).",
    "SCH-004": "An entityRef names an entity that is not declared under Entities.",
    "SCH-005": "A $parameter or ${expression} could not be resolved to a value.",
    "SCH-006": "An attribute's text could not be parsed as its declared type (e.g. a non-numeric speed).",
    "SCH-007": "A CatalogReference points to a catalog or entry that could not be found next to the scenario.",
    "SCH-008": "A TimeOfDay dateTime is not valid ISO 8601.",
    "FRI-024": "Compares frictionScaleFactor across all declared environment states: a wetter state must never declare higher friction than a drier one.",
    "MAP-000": "The OpenDRIVE file parsed with problems; map checks run on the parseable part only.",
    "MAP-001": "A RoadPosition/LanePosition roadId does not exist in the map.",
    "MAP-002": "The laneId does not exist in the road's lane section at the given s-coordinate.",
    "MAP-003": "The s-coordinate lies beyond the road's length (0.5 m tolerance).",
    "MAP-004": "The entity's resolved world position lies on no vehicle-passable lane — including detection of coordinates mirrored into CARLA's left-handed frame.",
    "MAP-005": "Oriented bounding boxes of two entities overlap at t=0 (separating-axis test); pairs linked by Relative positions are exempt (attachment idiom).",
    "MAP-006": "Consecutive route waypoints resolve to roads with no path between them in the road/junction connectivity graph.",
    "MAP-007": "The entity's top commanded speed exceeds the road's legal speed record by more than 10 %.",
    "GEO-001": "The (elevation, azimuth) pair implies a solar declination outside ±23.44° at the map's latitude — no date can produce it (error beyond 5°).",
    "GEO-002": "Same computation as GEO-001, within the 0.7°–5° implausibility band.",
    "GEO-003": "Elevation alone exceeds the annual maximum for the map's latitude (error beyond 5°).",
    "GEO-004": "Same as GEO-003, within the 0.7°–5° band.",
    "GEO-005": "With a declared dateTime, the ephemeris sun and the declared sun differ by more than 5° (naive times are tried as UTC, local standard and DST; the minimum discrepancy is scored).",
    "GEO-006": "Same as GEO-005, within the 0.7°–5° band.",
    "DYN-001": "For declared road/lane spawns: commanded speed² × the road's curvature at that point exceeds µ·g (µ from the declared surface, generous class ceilings).",
    "DYN-002": "Peak lateral acceleration of the sinusoidal lane-change profile over the actual lane width (map) at the commanded duration exceeds µ·g.",
    "DYN-003": "A SpeedAction's rate exceeds what the declared surface's friction can transfer through the tires (µ·g with FRI-013's tolerance).",
    "DYN-004": "Vertex time stamps of a followed trajectory decrease or repeat — the motion runs backwards in time.",
    "DYN-005": "A raw trajectory segment implies a speed beyond the class record ceiling (car 140, cyclist 39, pedestrian 12.5 m/s) — a position jump, not motion.",
    "DYN-006": "Windowed (≥ 0.4 s) longitudinal + lateral acceleration along the trajectory exceeds the friction circle µ·g sustainedly (two consecutive windows).",
    "DYN-007": "A pedestrian/cyclist trajectory sustains a windowed average speed beyond human endurance (marathon record pace / cycling hour record) for ≥ 30 s.",
    "STB-001": "The act's certain stop time (simulation-time conditions + delay) is at or before its earliest possible start — the activity interval is empty.",
    "STB-002": "The trigger's earliest possible firing time is at or after the storyboard's certain stop time — dead code.",
    "STB-003": "One event starts two or more actions on the same motion channel (longitudinal or lateral) of the same actor simultaneously.",
    "STB-004": "An event or maneuver group declares maximumExecutionCount=\"0\".",
    "STB-005": "A maneuver group contains events with private actions but declares no actors (groups holding only global actions are fine).",
    "STB-006": "The storyboard has no stop-trigger condition — no declared termination.",
    "STB-007": "A ParameterCondition applies a numeric comparison (greaterThan, …) but the parameter's declared value or the comparison value is not a number.",
    "ODD-000": "The ODD YAML parsed with problems; conformance runs on the parseable constraints only.",
    "ODD-001": "A declared attribute value violates the ODD's include condition or hits an exclude condition.",
    "ODD-002": "The ODD constrains an attribute the scenario does not declare at all.",
    "STA-001": "The scenario's assignment sits below the configured quantile (default 1 %) of the operational model's own score distribution.",
}

SEV_CLASS = {"error": "err", "warning": "warn", "info": "info"}


def citation_html(citation: object) -> str:
    if isinstance(citation, dict):
        src = e(str(citation.get("source", "")))
        year = citation.get("year")
        url = citation.get("doi_or_url")
        out = src + (f" ({year})" if year else "")
        if url:
            out += f' — <a href="{e(str(url))}">{e(str(url))}</a>'
        return out
    return e(str(citation))


def yaml_rule_card(r) -> str:  # noqa: ANN001
    when = (
        f'<div class="cond"><span>Applies when</span><code>{e(r.when)}</code></div>'
        if r.when else ""
    )
    basis = (
        f'<p class="basis">{e(r.quantitative_basis.strip())}</p>'
        if r.quantitative_basis else ""
    )
    return f"""<article class="rule" id="{r.id}">
  <div class="rule-head"><span class="rid">{r.id}</span>
    <span class="sev {SEV_CLASS[r.severity]}">{r.severity}</span>
    <span class="scope">{e(r.layer)} · per {e(r.scope)}</span></div>
  <h4>{e(r.title)}</h4>
  {when}
  <div class="cond"><span>Requires</span><code>{e(r.assert_expr or "—")}</code></div>
  {basis}
  <p class="src"><span>Source</span> {citation_html(r.citation)}</p>
</article>"""


def plugin_rule_card(rid: str, meta: tuple) -> str:  # noqa: ANN001
    layer, severity, title, citation = meta
    how = HOW.get(rid, "")
    return f"""<article class="rule" id="{rid}">
  <div class="rule-head"><span class="rid">{rid}</span>
    <span class="sev {SEV_CLASS[severity]}">{severity}</span>
    <span class="scope">{e(layer)} · built-in analysis</span></div>
  <h4>{e(title)}</h4>
  <p class="basis">{e(how)}</p>
  <p class="src"><span>Source</span> {e(citation)}</p>
</article>"""


def build() -> str:
    rules, errors = load_default_packs()
    assert not errors, errors
    by_pack: dict[str, list] = {}
    for r in rules:
        by_pack.setdefault(r.pack, []).append(r)

    nav_packs = []
    body_packs = []
    for pack, (label, intro) in YAML_PACK_META.items():
        pack_rules = sorted(by_pack.get(pack, []), key=lambda r: r.id)
        if not pack_rules:
            continue
        nav_packs.append(
            f'<a href="#pack-{pack}">{e(label)} <em>{len(pack_rules)}</em></a>'
        )
        cards = "\n".join(yaml_rule_card(r) for r in pack_rules)
        body_packs.append(f"""<section class="pack" id="pack-{pack}">
<h3>{e(label)} <span class="count">{len(pack_rules)} rules · YAML pack <code>{pack}.yaml</code></span></h3>
<p class="intro">{e(intro)}</p>
{cards}
</section>""")
    for anchor, label, plugin_rules, intro in PLUGIN_PACKS:
        nav_packs.append(
            f'<a href="#{anchor}">{e(label)} <em>{len(plugin_rules)}</em></a>'
        )
        cards = "\n".join(
            plugin_rule_card(rid, meta) for rid, meta in sorted(plugin_rules.items())
        )
        body_packs.append(f"""<section class="pack" id="{anchor}">
<h3>{e(label)} <span class="count">{len(plugin_rules)} rules · built-in analysis</span></h3>
<p class="intro">{e(intro)}</p>
{cards}
</section>""")

    n_total = len(rules) + sum(len(p[2]) for p in PLUGIN_PACKS)
    nav_html = "\n".join(nav_packs)
    packs_html = "\n".join(body_packs)

    return TEMPLATE.format(
        version=e(__version__), n_total=n_total, n_yaml=len(rules),
        n_plugin=n_total - len(rules), nav_packs=nav_html, packs=packs_html,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>physcheck — the physical-plausibility linter, explained</title>
<style>
  :root {{
    --bg:#ffffff; --fg:#1c2733; --muted:#5b6b7b; --accent:#0b6e4f;
    --accent-soft:#e7f4ef; --card:#f5f7f9; --border:#dde4ea;
    --bad:#b3261e; --warnc:#8a6d00; --infoc:#28546e;
    --code-bg:#10141a; --code-fg:#d7e0ea; --sidebar-w:250px;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg:#10141a; --fg:#e4ebf2; --muted:#9aa8b6; --accent:#4cc79a;
      --accent-soft:#12291f; --card:#171d26; --border:#2a3441;
      --bad:#ff8a80; --warnc:#ffd54f; --infoc:#81c8f0;
      --code-bg:#0a0d12; --code-fg:#cdd8e3;
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;
         background:var(--bg); color:var(--fg); }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  nav.side {{
    position:fixed; top:0; left:0; bottom:0; width:var(--sidebar-w);
    overflow-y:auto; background:var(--card); border-right:1px solid var(--border);
    padding:1.2rem 1rem 2rem; font-size:.88rem;
  }}
  nav.side .brand {{ font-weight:800; font-size:1.15rem; margin-bottom:.2rem; }}
  nav.side .brand span {{ color:var(--accent); }}
  nav.side .ver {{ color:var(--muted); margin-bottom:1rem; }}
  nav.side h5 {{ margin:1.1rem 0 .3rem; color:var(--muted);
               text-transform:uppercase; font-size:.72rem; letter-spacing:.06em; }}
  nav.side a {{ display:block; padding:.18rem .4rem; border-radius:6px; color:var(--fg); }}
  nav.side a:hover {{ background:var(--accent-soft); text-decoration:none; }}
  nav.side a em {{ float:right; font-style:normal; color:var(--muted); }}
  main {{ margin-left:var(--sidebar-w); max-width:900px; padding:2.5rem 2.2rem 5rem; }}
  @media (max-width: 900px) {{
    nav.side {{ position:static; width:auto; border-right:none;
               border-bottom:1px solid var(--border); }}
    main {{ margin-left:0; padding:1.5rem 1.2rem 4rem; }}
  }}
  h1 {{ font-size:2rem; margin:.2rem 0 .5rem; letter-spacing:-.02em; }}
  h2 {{ font-size:1.4rem; margin:2.6rem 0 .7rem; padding-top:.5rem; }}
  h3 {{ font-size:1.15rem; margin:2.2rem 0 .4rem; }}
  h3 .count {{ font-weight:400; font-size:.8rem; color:var(--muted); margin-left:.5rem; }}
  .muted {{ color:var(--muted); }}
  .pipeline {{ display:flex; flex-wrap:wrap; gap:.45rem; align-items:center; margin:1.2rem 0; }}
  .pipeline .box {{ background:var(--accent-soft); color:var(--accent);
    border:1px solid var(--accent); border-radius:8px; padding:.4rem .8rem;
    font-weight:600; font-size:.85rem; text-align:center; }}
  .pipeline .a {{ color:var(--muted); }}
  pre {{ background:var(--code-bg); color:var(--code-fg); border-radius:10px;
        padding:1rem 1.2rem; overflow-x:auto; font-size:.85rem; line-height:1.55; }}
  code {{ font-family:ui-monospace,"SF Mono",Consolas,monospace; }}
  p code, li code, td code, .cond code {{ background:var(--card);
    border:1px solid var(--border); border-radius:5px; padding:.05rem .35rem; font-size:.86em; }}
  table {{ border-collapse:collapse; width:100%; margin:1rem 0; font-size:.92rem; }}
  th, td {{ text-align:left; padding:.5rem .65rem; border-bottom:1px solid var(--border);
           vertical-align:top; }}
  th {{ color:var(--muted); }}
  .rule {{ background:var(--card); border:1px solid var(--border); border-radius:10px;
          padding: .9rem 1.1rem; margin:.8rem 0; }}
  .rule-head {{ display:flex; gap:.55rem; align-items:center; flex-wrap:wrap; }}
  .rid {{ font-family:ui-monospace,Consolas,monospace; font-weight:700; }}
  .sev {{ border-radius:6px; padding:.02rem .5rem; font-size:.75rem; font-weight:700;
         text-transform:uppercase; color:var(--bg); }}
  .sev.err {{ background:var(--bad); }}
  .sev.warn {{ background:var(--warnc); }}
  .sev.info {{ background:var(--infoc); }}
  .scope {{ color:var(--muted); font-size:.8rem; }}
  .rule h4 {{ margin:.45rem 0 .35rem; font-size:1rem; }}
  .cond {{ margin:.25rem 0; font-size:.88rem; }}
  .cond span, .src span {{ color:var(--muted); font-size:.78rem;
    text-transform:uppercase; letter-spacing:.05em; margin-right:.5rem; }}
  .basis {{ margin:.45rem 0 .25rem; font-size:.92rem; }}
  .src {{ margin:.35rem 0 0; font-size:.85rem; color:var(--muted); }}
  .pack {{ border-top:1px solid var(--border); }}
  .intro {{ color:var(--muted); }}
  .toprow {{ display:flex; gap:1rem; flex-wrap:wrap; margin:1.2rem 0; }}
  .stat {{ flex:1 1 140px; background:var(--card); border:1px solid var(--border);
    border-radius:10px; padding: .8rem 1rem; text-align:center; }}
  .stat b {{ display:block; font-size:1.6rem; color:var(--accent); }}
  .stat small {{ color:var(--muted); }}
</style>
</head>
<body>
<nav class="side">
  <div class="brand">odd-<span>pilot</span> docs</div>
  <div class="ver">physcheck {version}</div>
  <h5>Site</h5>
  <a href="index.html">← Overview</a>
  <a href="install.html">Download &amp; install</a>
  <a href="findings.html">Violations in public suites</a>
  <a href="related.html">Related work &amp; comparison</a>
  <a href="oddpilot.html">odd-pilot: campaign copilot</a>
  <h5>physcheck</h5>
  <a href="#what">What it is</a>
  <a href="#how">How it is implemented</a>
  <a href="#using">Using it</a>
  <a href="#extending">Writing your own rules</a>
  <a href="#trust">Validation</a>
  <h5>Rule reference ({n_total})</h5>
  {nav_packs}
</nav>
<main>

<h1>physcheck<span class="muted"> — every rule, explained</span></h1>
<p>The physical-plausibility linter inside odd-pilot. It reads ASAM
OpenSCENARIO files and reports everything that is physically impossible,
internally contradictory, or outside your declared operating domain —
each finding backed by a citation. This page documents how it works and
every one of its {n_total} rules.</p>

<div class="toprow">
  <div class="stat"><b>{n_total}</b><small>rules, all cited</small></div>
  <div class="stat"><b>7</b><small>independent layers (L0–L6)</small></div>
  <div class="stat"><b>1</b><small>runtime dependency (PyYAML)</small></div>
  <div class="stat"><b>0</b><small>false alarms on 1,109 real files</small></div>
</div>

<h2 id="what">What it is</h2>
<p>physcheck is a <b>linter</b>: it never runs a simulation. It parses each
scenario file, reconstructs what the file actually declares — weather, road
surface, actors, motion, story logic — and evaluates rules against that
declaration. A finding always carries: the rule id, a severity
(<b>error</b> = impossible as written, <b>warning</b> = suspicious or rare,
<b>info</b> = worth knowing), a one-sentence message with the offending
values, and the literature source the rule is based on.</p>
<p>The severity philosophy is deliberate: <b>errors are reserved for the
certainly-impossible</b>. Where physics gives a range, rules use the generous
end of the published range, so an error means "no real-world configuration
could produce this file" — not "unusual".</p>

<h2 id="how">How it is implemented</h2>
<div class="pipeline">
  <span class="box">.xosc file</span><span class="a">→</span>
  <span class="box">Parser<br><small>parameters, expressions, catalogs</small></span><span class="a">→</span>
  <span class="box">Typed Scenario IR</span><span class="a">→</span>
  <span class="box">Attribute view<br><small>flat, canonical names</small></span><span class="a">→</span>
  <span class="box">Rule engine<br><small>YAML predicates + built-in analyses</small></span><span class="a">→</span>
  <span class="box">Findings<br><small>table · JSON · SARIF · HTML</small></span>
</div>
<table>
<tr><th>Component</th><th>What it does, in practice</th></tr>
<tr><td>Parser</td><td>Reads OpenSCENARIO 1.0–1.3, resolves <code>$parameters</code>,
  <code>${{expressions}}</code> and catalog references. It <b>never throws</b>: anything it
  cannot interpret becomes an L0 finding, so one broken element never hides the
  rest of the file.</td></tr>
<tr><td>Scenario IR</td><td>A typed, engine-agnostic model of the file: environments,
  entities with performance and boxes, speed commands, lane changes, followed
  trajectories (memory-efficient for replay files with 100,000+ vertices), and the
  storyboard control structure.</td></tr>
<tr><td>Attribute view</td><td>The IR flattened into canonically named values
  (<code>env.precip.type</code>, <code>entity.max_decel_mps2</code>, …). YAML rules only ever see
  this view — never raw XML. An absent value is an absent key, never a default:
  a rule that needs a missing attribute silently does not apply.</td></tr>
<tr><td>YAML rules ({n_yaml})</td><td>Each is a guarded predicate in a <b>safe expression
  subset</b> (comparisons, arithmetic, a fixed set of math functions — no arbitrary
  code). Shown below per rule as "Applies when" / "Requires".</td></tr>
<tr><td>Built-in analyses ({n_plugin})</td><td>Checks that need real computation: the
  OpenDRIVE map frontend (geometry sampling, lane resolution, connectivity), the
  NOAA/Meeus solar ephemeris, trajectory kinematics with noise-robust windowed
  estimators, storyboard reachability, ODD evaluation, and the statistical scorer.
  Each is documented with its rules below.</td></tr>
<tr><td>Layer gating</td><td>Layers are independent and opt-in: L0–L1 always work
  from the file alone; L2–L3 activate when a map is available (via <code>--map</code> or the
  scenario's own RoadNetwork reference); L5 needs an ODD definition; L6 an
  operational model. Missing inputs skip a layer with a note — never an error.</td></tr>
<tr><td>Determinism</td><td>Same inputs, same findings: no randomness, no network, no
  simulator. Suitable as a CI gate (<code>--fail-on error</code> sets the exit code).</td></tr>
</table>
<p>Every interpretation decision made while implementing the rules (what a
missing attribute means, which frame a coordinate is in, how tolerances were
chosen) is recorded in
<a href="https://github.com/BorhaneddineHamadou/oddpilot/blob/main/docs/decisions.md">docs/decisions.md</a>
(D1–D36) — the reviewers' trail behind every threshold on this page.</p>

<h2 id="using">Using it</h2>
<pre><code># check a folder — layers L0+L1 need nothing but the files
physcheck lint scenarios/

# add map-based checks (L2+L3): give a map, or let each file's
# RoadNetwork reference resolve automatically
physcheck lint scenarios/ --map town04.xodr

# storyboard logic, ODD conformance, statistical realism
physcheck lint scenarios/ --layers L0,L1,L4
physcheck lint scenarios/ --odd my_odd.yaml
odd-pilot lint scenarios/ --layers L0,L1,L6 --model world.bn

# outputs and CI
physcheck lint scenarios/ --format sarif -o lint.sarif   # GitHub code scanning
physcheck lint scenarios/ --format html  -o report.html  # shareable page
physcheck lint scenarios/ --fail-on error                # exit 1 on any error

# understand a finding
physcheck rules show FRI-013
physcheck lint s.xosc --explain FRI-013</code></pre>
<p>Exit codes: <code>0</code> clean, <code>1</code> findings at/above <code>--fail-on</code>,
<code>3</code> usage error. <code>2</code> is reserved by odd-pilot's <code>assess
--fail-if-inadequate</code>.</p>

<h2 id="extending">Writing your own rules</h2>
<p>Teams add domain rules without touching code — a YAML pack with the same
schema as the built-in catalog, validated by <code>physcheck rules lint</code>:</p>
<pre><code>pack: my_team
version: "1.0"
rules:
  - id: TEAM-001
    layer: L1
    severity: error
    title: Our simulator cannot render fog below 50 m
    scope: scenario
    when: "env.fog.present"
    assert: "env.fog.visual_range_m >= 50"
    message: "visualRange={{env.fog.visual_range_m}} m is below the renderer's floor."
    units: {{env.fog.visual_range_m: m}}
    citation: {{source: "Internal renderer spec RD-42", year: 2026}}

# validate, then use it
physcheck rules lint my_rules.yaml
physcheck lint scenarios/ --rules my_rules.yaml</code></pre>

<h2 id="trust">Validation</h2>
<p>physcheck is benchmarked on every release against scenario files derived
from <b>real recorded driving</b> (drone recordings of intersections and
motorways, camera recordings, roadside-sensor replays): real driving is
physically plausible by construction, so every error finding there is a
potential false alarm — and there were <b>0 tool false alarms across 1,109
files</b>, while all <b>1,819 deliberately injected impossibilities</b> were
detected. The full protocol, corpora provenance and per-finding triage
evidence live in the
<a href="https://github.com/BorhaneddineHamadou/physcheck-benchmark">benchmark repository</a>.</p>

<h2 id="rules">Rule reference</h2>
<p class="muted">Generated from the shipped catalog (physcheck {version}) —
{n_yaml} YAML rules and {n_plugin} built-in analyses. "Applies when" is the guard;
"Requires" must hold or the rule fires. Attribute names are the canonical
attribute view (<code>env.*</code>, <code>entity.*</code>).</p>
{packs}

<footer style="border-top:1px solid var(--border); margin-top:3rem; padding-top:1.2rem;"
        class="muted">
<p>This page is generated from the rule catalog by
<code>docs/generate_physcheck_docs.py</code> — it cannot drift from the code.
<a href="https://github.com/BorhaneddineHamadou/oddpilot">Source on GitHub</a> ·
Apache-2.0.</p>
</footer>
</main>
</body>
</html>
"""


if __name__ == "__main__":
    out = ROOT / "docs" / "physcheck.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
