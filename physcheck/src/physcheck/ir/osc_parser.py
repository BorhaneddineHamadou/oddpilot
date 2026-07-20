"""OpenSCENARIO 1.x XML frontend for the Scenario IR.

Supports revisions 1.0 through 1.3 with ParameterDeclaration / ``$param`` /
``${expr}`` resolution. Anything the parser cannot interpret is recorded as a
:class:`~physcheck.ir.model.ParseIssue` (surfaced as L0 findings), never an
exception: parsing must always yield a Scenario.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from physcheck.engine.predicate import Predicate
from physcheck.ir.model import (
    BoundingBox,
    Entity,
    Environment,
    FileHeader,
    Fog,
    LaneChange,
    ParseIssue,
    Performance,
    Precipitation,
    RoadCondition,
    Scenario,
    SpeedCommand,
    Sun,
    TimeOfDay,
    Weather,
    Wind,
)

__all__ = ["parse_file", "parse_string"]

#: OSC 1.2 FractionalCloudCover enum -> oktas.
_OKTAS = {f"{name}Oktas": i for i, name in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
)}

_VEHICLE_LIKE = {"Vehicle": "vehicle", "Pedestrian": "pedestrian", "MiscObject": "misc_object"}


class _Ctx:
    """Mutable parse context: parameters and the issue sink."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.params: dict[str, str] = scenario.parameters
        self._depth = 0

    def issue(self, code: str, message: str, context: str = "") -> None:
        self.scenario.parse_issues.append(ParseIssue(code, message, context))

    def resolve(self, raw: str | None, where: str) -> str | None:
        """Resolve $parameter references and ${...} expressions to a literal string."""
        if raw is None:
            return None
        value = raw.strip()
        for _ in range(10):  # parameters may reference parameters
            if value.startswith("${") and value.endswith("}"):
                value = self._eval_expr(value[2:-1], where)
                continue
            if value.startswith("$") and not value.startswith("${"):
                name = value[1:]
                if name in self.params:
                    value = self.params[name].strip()
                    continue
                self.issue("unresolved-parameter", f"parameter ${name} is not declared", where)
                return None
            return value
        self.issue("unresolved-parameter", f"parameter resolution loop for {raw!r}", where)
        return None

    def _eval_expr(self, expr: str, where: str) -> str:
        if self._depth > 8:
            self.issue(
                "unresolved-expression", f"expression nesting too deep in ${{{expr}}}", where
            )
            return ""
        text = expr
        # OSC expressions reference parameters as $name; substitute each with its
        # *resolved* value (parameter values may themselves be expressions).
        self._depth += 1
        try:
            for name, val in sorted(self.params.items(), key=lambda kv: -len(kv[0])):
                if f"${name}" in text:
                    resolved = self.resolve(val, where)
                    text = text.replace(f"${name}", (resolved if resolved else val).strip())
        finally:
            self._depth -= 1
        try:
            result = Predicate(text).evaluate({})
        except Exception:  # any failure is a parse issue, never an exception
            self.issue("unresolved-expression", f"cannot evaluate expression ${{{expr}}}", where)
            return ""
        return repr(result) if isinstance(result, bool) else str(result)

    def get_float(self, elem: ET.Element, attr: str, where: str) -> float | None:
        raw = self.resolve(elem.get(attr), where=f"{where}@{attr}")
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except ValueError:
            self.issue("bad-number", f"value {raw!r} is not a number", f"{where}@{attr}")
            return None

    def get_str(self, elem: ET.Element, attr: str, where: str) -> str | None:
        return self.resolve(elem.get(attr), where=f"{where}@{attr}")


def parse_file(path: str | Path) -> Scenario:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        sc = Scenario(source_path=str(p))
        sc.parse_issues.append(ParseIssue("io-error", f"cannot read file: {exc}"))
        return sc
    return parse_string(text, source_path=str(p))


def parse_string(text: str, source_path: str = "<string>") -> Scenario:
    sc = Scenario(source_path=source_path)
    ctx = _Ctx(sc)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        ctx.issue("xml-error", f"not well-formed XML: {exc}")
        return sc
    if root.tag != "OpenSCENARIO":
        ctx.issue("xml-error", f"root element is <{root.tag}>, expected <OpenSCENARIO>")
        return sc

    header = root.find("FileHeader")
    if header is None:
        ctx.issue("missing-header", "FileHeader element is missing")
    else:
        sc.header = _parse_header(header, ctx)

    if root.find("ParameterValueDistribution") is not None:
        sc.document_kind = "parameter_value_distribution"
        return sc
    if root.find("Catalog") is not None:
        sc.document_kind = "catalog"
        return sc

    # Collect ParameterDeclarations from every level (scenario, Story,
    # ManeuverGroup, Maneuver). Scoping is flattened: physcheck only needs
    # values for plausibility checks, not OSC's lexical scoping (decisions D10).
    for decls in root.iter("ParameterDeclaration"):
        name = decls.get("name")
        value = decls.get("value", "")
        if name and name.lstrip("$") not in sc.parameters:
            sc.parameters[name.lstrip("$")] = value

    logic = root.find("RoadNetwork/LogicFile")
    if logic is not None:
        sc.road_network_logic_file = logic.get("filepath")

    for obj in root.findall("Entities/ScenarioObject"):
        entity = _parse_scenario_object(obj, ctx)
        if entity is not None:
            sc.entities.append(entity)

    storyboard = root.find("Storyboard")
    if storyboard is not None:
        _parse_storyboard(storyboard, ctx)

    # Collect every entityRef anywhere for the dangling-reference check.
    for elem in root.iter():
        ref = elem.get("entityRef")
        if ref is not None:
            resolved = ctx.resolve(ref, where=f"<{elem.tag}>@entityRef")
            if resolved:
                sc.entity_refs.append(resolved)
    return sc


def _parse_header(elem: ET.Element, ctx: _Ctx) -> FileHeader:
    def _int(attr: str) -> int | None:
        raw = elem.get(attr)
        if raw is None:
            ctx.issue("missing-header", f"FileHeader@{attr} is missing")
            return None
        try:
            return int(raw)
        except ValueError:
            ctx.issue("bad-number", f"FileHeader@{attr}={raw!r} is not an integer")
            return None

    return FileHeader(
        rev_major=_int("revMajor"),
        rev_minor=_int("revMinor"),
        date=elem.get("date"),
        description=elem.get("description"),
        author=elem.get("author"),
    )


def _parse_scenario_object(obj: ET.Element, ctx: _Ctx) -> Entity | None:
    name = obj.get("name") or "<unnamed>"
    for tag, kind in _VEHICLE_LIKE.items():
        found = obj.find(tag)
        if found is not None:
            return _parse_entity_body(found, name, kind, ctx)
    if obj.find("CatalogReference") is not None:
        catref = obj.find("CatalogReference")
        assert catref is not None
        ctx.issue(
            "unresolved-catalog",
            f"entity '{name}' comes from catalog "
            f"'{catref.get('catalogName')}/{catref.get('entryName')}' (not resolved in v0.1)",
            f"ScenarioObject[{name}]",
        )
        return Entity(name=name, kind="external", from_catalog=True)
    ctx.issue("unknown-entity", f"entity '{name}' has an unrecognized object type")
    return Entity(name=name, kind="external")


def _parse_entity_body(elem: ET.Element, name: str, kind: str, ctx: _Ctx) -> Entity:
    where = f"{elem.tag}[{name}]"
    category = (
        ctx.get_str(elem, "vehicleCategory", where)
        or ctx.get_str(elem, "pedestrianCategory", where)
        or ctx.get_str(elem, "miscObjectCategory", where)
    )
    bbox = None
    dims = elem.find("BoundingBox/Dimensions")
    if dims is not None:
        bbox = BoundingBox(
            length_m=ctx.get_float(dims, "length", where),
            width_m=ctx.get_float(dims, "width", where),
            height_m=ctx.get_float(dims, "height", where),
        )
    perf = None
    perf_elem = elem.find("Performance")
    if perf_elem is not None:
        perf = Performance(
            max_speed_mps=ctx.get_float(perf_elem, "maxSpeed", where),
            max_acceleration_mps2=ctx.get_float(perf_elem, "maxAcceleration", where),
            max_deceleration_mps2=ctx.get_float(perf_elem, "maxDeceleration", where),
        )
    return Entity(
        name=name,
        kind=kind,
        category=category,
        bounding_box=bbox,
        performance=perf,
        mass_kg=ctx.get_float(elem, "mass", where),
        model=elem.get("model"),
    )


def _parse_storyboard(storyboard: ET.Element, ctx: _Ctx) -> None:
    sc = ctx.scenario
    init = storyboard.find("Init")
    if init is not None:
        for global_action in init.findall("Actions/GlobalAction"):
            env_action = global_action.find("EnvironmentAction")
            if env_action is not None:
                env = _parse_environment_action(env_action, ctx, label="Init")
                if env is not None:
                    sc.environments.append(env)
        for private in init.findall("Actions/Private"):
            ref = ctx.resolve(private.get("entityRef"), "Init/Private@entityRef") or ""
            for speed_action in private.iter("SpeedAction"):
                cmd = _parse_speed_action(speed_action, ref, "Init", ctx)
                if cmd is not None:
                    sc.speed_commands.append(cmd)
                    entity = _find_entity(sc, ref)
                    if entity is not None and cmd.target_speed_mps is not None:
                        entity.initial_speed_mps = cmd.target_speed_mps

    for story in storyboard.findall("Story"):
        story_name = story.get("name", "")
        for group in story.iter("ManeuverGroup"):
            actors = [
                ctx.resolve(e.get("entityRef"), "Actors/EntityRef") or ""
                for e in group.findall("Actors/EntityRef")
            ]
            label = f"Story[{story_name}]/{group.get('name', '')}"
            for speed_action in group.iter("SpeedAction"):
                for actor in actors or [""]:
                    cmd = _parse_speed_action(speed_action, actor, label, ctx)
                    if cmd is not None:
                        sc.speed_commands.append(cmd)
            for lane_change in group.iter("LaneChangeAction"):
                for actor in actors or [""]:
                    lc = _parse_lane_change(lane_change, actor, label, ctx)
                    if lc is not None:
                        sc.lane_changes.append(lc)
            for env_action in group.iter("EnvironmentAction"):
                env = _parse_environment_action(env_action, ctx, label=label)
                if env is not None:
                    sc.environments.append(env)


def _find_entity(sc: Scenario, name: str) -> Entity | None:
    for entity in sc.entities:
        if entity.name == name:
            return entity
    return None


def _parse_speed_action(
    action: ET.Element, entity: str, label: str, ctx: _Ctx
) -> SpeedCommand | None:
    where = f"{label}/SpeedAction"
    target = action.find("SpeedActionTarget/AbsoluteTargetSpeed")
    speed = ctx.get_float(target, "value", where) if target is not None else None
    rate = None
    dynamics = action.find("SpeedActionDynamics")
    if dynamics is not None and ctx.get_str(dynamics, "dynamicsDimension", where) == "rate":
        value = ctx.get_float(dynamics, "value", where)
        if value is not None:
            rate = abs(value)
    if speed is None and rate is None:
        return None
    return SpeedCommand(entity=entity, target_speed_mps=speed, rate_mps2=rate, label=label)


def _parse_lane_change(
    action: ET.Element, entity: str, label: str, ctx: _Ctx
) -> LaneChange | None:
    where = f"{label}/LaneChangeAction"
    dynamics = action.find("LaneChangeActionDynamics")
    if dynamics is None:
        return None
    dim = ctx.get_str(dynamics, "dynamicsDimension", where)
    value = ctx.get_float(dynamics, "value", where)
    if value is None:
        return None
    if dim == "time":
        return LaneChange(entity=entity, duration_s=value, label=label)
    if dim == "distance":
        return LaneChange(entity=entity, distance_m=value, label=label)
    return None


def _parse_environment_action(action: ET.Element, ctx: _Ctx, label: str) -> Environment | None:
    env_elem = action.find("Environment")
    if env_elem is None:
        if action.find("CatalogReference") is not None:
            ctx.issue(
                "unresolved-catalog",
                "EnvironmentAction uses a CatalogReference (not resolved in v0.1)",
                label,
            )
        return None
    return _parse_environment(env_elem, ctx, label)


def _parse_environment(env_elem: ET.Element, ctx: _Ctx, label: str) -> Environment:
    where = f"{label}/Environment"
    env = Environment(name=env_elem.get("name", ""), label=label)

    tod = env_elem.find("TimeOfDay")
    if tod is not None:
        raw = ctx.get_str(tod, "dateTime", where)
        parsed: datetime | None = None
        if raw:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                ctx.issue("bad-datetime", f"TimeOfDay@dateTime={raw!r} is not ISO 8601", where)
        animation_raw = ctx.get_str(tod, "animation", where)
        env.time_of_day = TimeOfDay(
            when=parsed,
            animation=None if animation_raw is None else animation_raw == "true",
            raw=raw,
        )

    weather_elem = env_elem.find("Weather")
    if weather_elem is not None:
        weather = Weather(
            cloud_state=ctx.get_str(weather_elem, "cloudState", where),
            temperature_k=ctx.get_float(weather_elem, "temperature", where),
            atmospheric_pressure_pa=ctx.get_float(weather_elem, "atmosphericPressure", where),
        )
        cover = ctx.get_str(weather_elem, "fractionalCloudCover", where)
        if cover is not None:
            if cover in _OKTAS:
                weather.cloud_cover_oktas = float(_OKTAS[cover])
            else:
                ctx.issue(
                    "bad-enum", f"fractionalCloudCover={cover!r} is not an oktas value", where
                )
        sun = weather_elem.find("Sun")
        if sun is not None:
            illuminance = ctx.get_float(sun, "illuminance", where)
            if illuminance is None:
                illuminance = ctx.get_float(sun, "intensity", where)
            weather.sun = Sun(
                azimuth_rad=ctx.get_float(sun, "azimuth", where),
                elevation_rad=ctx.get_float(sun, "elevation", where),
                illuminance_lux=illuminance,
            )
        fog = weather_elem.find("Fog")
        if fog is not None:
            weather.fog = Fog(visual_range_m=ctx.get_float(fog, "visualRange", where))
        precipitation = weather_elem.find("Precipitation")
        if precipitation is not None:
            ptype = ctx.get_str(precipitation, "precipitationType", where)
            weather.precipitation = Precipitation(
                ptype=ptype,
                intensity01=ctx.get_float(precipitation, "intensity", where),
                intensity_mmh=ctx.get_float(precipitation, "precipitationIntensity", where),
            )
        wind = weather_elem.find("Wind")
        if wind is not None:
            weather.wind = Wind(
                direction_rad=ctx.get_float(wind, "direction", where),
                speed_mps=ctx.get_float(wind, "speed", where),
            )
        env.weather = weather

    road = env_elem.find("RoadCondition")
    if road is not None:
        env.road_condition = RoadCondition(
            friction_scale_factor=ctx.get_float(road, "frictionScaleFactor", where),
            wetness=ctx.get_str(road, "wetness", where),
        )
    return env
