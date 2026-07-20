"""Flat attribute view over the Scenario IR.

Rules see only these canonically named attributes (documented with provenance,
type, units and range in docs/attribute_space.md). Absent information is an
absent key — never a sentinel value.
"""

from __future__ import annotations

from physcheck.ir.model import Entity, Environment, Scenario

__all__ = ["entity_contexts", "scenario_contexts"]

Attrs = dict[str, object]


def _put(attrs: Attrs, key: str, value: object) -> None:
    if value is not None:
        attrs[key] = value


def _environment_attrs(env: Environment) -> Attrs:
    attrs: Attrs = {"env.present": True}
    if env.time_of_day is not None:
        _put(attrs, "env.time.iso", env.time_of_day.raw)
        if env.time_of_day.when is not None:
            when = env.time_of_day.when
            attrs["env.time.hour"] = when.hour + when.minute / 60.0
            attrs["env.time.month"] = when.month
    weather = env.weather
    if weather is not None:
        _put(attrs, "env.cloud.state", weather.cloud_state)
        _put(attrs, "env.cloud.oktas", weather.cloud_cover_oktas)
        _put(attrs, "env.temperature_k", weather.temperature_k)
        if weather.temperature_k is not None:
            attrs["env.temperature_c"] = round(weather.temperature_k - 273.15, 4)
        _put(attrs, "env.pressure_pa", weather.atmospheric_pressure_pa)
        if weather.sun is not None:
            _put(attrs, "env.sun.azimuth_rad", weather.sun.azimuth_rad)
            _put(attrs, "env.sun.elevation_rad", weather.sun.elevation_rad)
            _put(attrs, "env.sun.illuminance_lux", weather.sun.illuminance_lux)
        if weather.fog is not None:
            attrs["env.fog.present"] = True
            _put(attrs, "env.fog.visual_range_m", weather.fog.visual_range_m)
        else:
            attrs["env.fog.present"] = False
        if weather.precipitation is not None:
            _put(attrs, "env.precip.type", weather.precipitation.ptype)
            _put(attrs, "env.precip.intensity01", weather.precipitation.intensity01)
            _put(attrs, "env.precip.intensity_mmh", weather.precipitation.intensity_mmh)
        if weather.wind is not None:
            _put(attrs, "env.wind.direction_rad", weather.wind.direction_rad)
            _put(attrs, "env.wind.speed_mps", weather.wind.speed_mps)
    if env.road_condition is not None:
        _put(attrs, "env.road.friction_scale", env.road_condition.friction_scale_factor)
        _put(attrs, "env.road.wetness", env.road_condition.wetness)
    return attrs


def _scenario_wide_attrs(scenario: Scenario) -> Attrs:
    attrs: Attrs = {"file.name": scenario.source_path}
    _put(attrs, "osc.version", scenario.osc_version)
    speeds = [s for s in (_max_target_speed(scenario, e) for e in scenario.entities)
              if s is not None]
    if speeds:
        attrs["scenario.max_speed_mps"] = max(speeds)
    return attrs


def _max_target_speed(scenario: Scenario, entity: Entity) -> float | None:
    speeds = [
        cmd.target_speed_mps
        for cmd in scenario.speed_commands
        if cmd.entity == entity.name and cmd.target_speed_mps is not None
    ]
    if entity.initial_speed_mps is not None:
        speeds.append(entity.initial_speed_mps)
    return max(speeds) if speeds else None


def scenario_contexts(scenario: Scenario) -> list[tuple[str, Attrs]]:
    """One (label, attrs) context per declared environment state.

    A scenario without any Environment yields a single context so that
    environment-independent scenario rules can still run.
    """
    base = _scenario_wide_attrs(scenario)
    if not scenario.environments:
        return [("no-environment", dict(base))]
    contexts: list[tuple[str, Attrs]] = []
    for i, env in enumerate(scenario.environments):
        attrs = dict(base)
        attrs.update(_environment_attrs(env))
        label = env.label if len(scenario.environments) == 1 else f"{env.label} (#{i + 1})"
        contexts.append((label, attrs))
    return contexts


def entity_contexts(scenario: Scenario) -> list[tuple[str, Attrs]]:
    """One (label, attrs) context per concrete entity.

    Entity contexts include the environment attributes of the *initial*
    environment state (docs/decisions.md D9) so friction-coupled rules can
    reference env.* alongside entity.*.
    """
    base = _scenario_wide_attrs(scenario)
    if scenario.environments:
        base.update(_environment_attrs(scenario.environments[0]))
    contexts: list[tuple[str, Attrs]] = []
    for entity in scenario.entities:
        if entity.from_catalog:
            continue  # nothing checkable without resolving the catalog
        attrs = dict(base)
        attrs["entity.name"] = entity.name
        attrs["entity.kind"] = entity.kind
        _put(attrs, "entity.category", entity.category)
        if entity.bounding_box is not None:
            _put(attrs, "entity.length_m", entity.bounding_box.length_m)
            _put(attrs, "entity.width_m", entity.bounding_box.width_m)
            _put(attrs, "entity.height_m", entity.bounding_box.height_m)
        if entity.performance is not None:
            _put(attrs, "entity.max_speed_mps", entity.performance.max_speed_mps)
            _put(attrs, "entity.max_accel_mps2", entity.performance.max_acceleration_mps2)
            _put(attrs, "entity.max_decel_mps2", entity.performance.max_deceleration_mps2)
        _put(attrs, "entity.mass_kg", entity.mass_kg)
        _put(attrs, "entity.initial_speed_mps", entity.initial_speed_mps)
        _put(attrs, "entity.max_target_speed_mps", _max_target_speed(scenario, entity))
        rates = [
            cmd.rate_mps2
            for cmd in scenario.speed_commands
            if cmd.entity == entity.name and cmd.rate_mps2 is not None
        ]
        if rates:
            attrs["entity.max_speed_change_rate_mps2"] = max(rates)
        durations = [
            lc.duration_s
            for lc in scenario.lane_changes
            if lc.entity == entity.name and lc.duration_s is not None
        ]
        if durations:
            attrs["entity.min_lane_change_time_s"] = min(durations)
        contexts.append((f"entity '{entity.name}'", attrs))
    return contexts
