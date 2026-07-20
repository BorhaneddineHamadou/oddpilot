"""Typed Scenario IR.

Engine-agnostic intermediate representation of a driving scenario. Frontends
(currently OpenSCENARIO 1.x XML) map concrete formats into these dataclasses;
rules read only the flat attribute view derived from them
(:mod:`physcheck.ir.attributes`), never the raw input.

Unit conventions (SI, following OpenSCENARIO): metres, seconds, m/s, m/s^2,
radians, kelvin, pascal, lux, mm/h for precipitation intensity (OSC >= 1.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ParseIssue:
    """A problem found while mapping the input into the IR (surfaces as L0 finding)."""

    code: str  # e.g. "xml-error", "bad-number", "unresolved-parameter"
    message: str
    context: str = ""


@dataclass
class FileHeader:
    rev_major: int | None = None
    rev_minor: int | None = None
    date: str | None = None
    description: str | None = None
    author: str | None = None


@dataclass
class Sun:
    azimuth_rad: float | None = None
    elevation_rad: float | None = None
    #: ``intensity`` (lux) in OSC 1.0/1.1; renamed ``illuminance`` (lux) in 1.2.
    illuminance_lux: float | None = None
    #: Which XML attribute carried the value: "illuminance" | "intensity" | None.
    illuminance_attr: str | None = None


@dataclass
class Fog:
    visual_range_m: float | None = None


@dataclass
class Precipitation:
    #: OSC PrecipitationType: dry | rain | snow
    ptype: str | None = None
    #: OSC 1.0 unitless intensity in [0, 1] (deprecated in 1.1).
    intensity01: float | None = None
    #: OSC >= 1.1 precipitationIntensity in mm/h.
    intensity_mmh: float | None = None


@dataclass
class Wind:
    direction_rad: float | None = None
    speed_mps: float | None = None


@dataclass
class RoadCondition:
    friction_scale_factor: float | None = None
    #: OSC >= 1.2 Wetness enum: dry | moist | wetWithPuddles | lowFlooded | highFlooded
    wetness: str | None = None


@dataclass
class Weather:
    #: OSC <= 1.1 CloudState enum (skyOff | free | cloudy | overcast | rainy).
    cloud_state: str | None = None
    #: OSC >= 1.2 FractionalCloudCover enum, normalised here to oktas [0..8].
    cloud_cover_oktas: float | None = None
    temperature_k: float | None = None
    atmospheric_pressure_pa: float | None = None
    sun: Sun | None = None
    fog: Fog | None = None
    precipitation: Precipitation | None = None
    wind: Wind | None = None


@dataclass
class TimeOfDay:
    #: Wall-clock date-time as written in the scenario (timezone semantics are
    #: underspecified in OSC 1.x; see docs/decisions.md D5).
    when: datetime | None = None
    animation: bool | None = None
    raw: str | None = None


@dataclass
class Environment:
    """One declared environment state (Init or a storyboard EnvironmentAction)."""

    name: str = ""
    label: str = "Init"  # human-readable provenance within the scenario
    time_of_day: TimeOfDay | None = None
    weather: Weather | None = None
    road_condition: RoadCondition | None = None


@dataclass
class BoundingBox:
    length_m: float | None = None
    width_m: float | None = None
    height_m: float | None = None


@dataclass
class Performance:
    max_speed_mps: float | None = None
    max_acceleration_mps2: float | None = None
    max_deceleration_mps2: float | None = None


@dataclass
class Entity:
    name: str
    #: vehicle | pedestrian | misc_object | external (catalog ref not resolved)
    kind: str
    #: OSC category enum (car, truck, bicycle, pedestrian, animal, ...).
    category: str | None = None
    bounding_box: BoundingBox | None = None
    performance: Performance | None = None
    mass_kg: float | None = None
    model: str | None = None
    initial_speed_mps: float | None = None
    #: Init teleport position, when declared.
    initial_position: Position | None = None
    #: True when the entity comes from an unresolved CatalogReference.
    from_catalog: bool = False


@dataclass
class Position:
    """One OpenSCENARIO Position element, normalised.

    ``kind`` is one of: world | relative_world | relative_object | road |
    relative_road | lane | relative_lane | route | trajectory | geo | other.
    Only the fields meaningful for the kind are set; everything else is None.
    """

    kind: str
    #: WorldPosition (map/inertial frame), metres / radians.
    x: float | None = None
    y: float | None = None
    z: float | None = None
    h: float | None = None
    #: RoadPosition / LanePosition target (OpenDRIVE road & lane ids).
    road_id: str | None = None
    lane_id: str | None = None
    s: float | None = None
    #: RoadPosition ``t`` or LanePosition ``offset`` (lateral, metres).
    t_or_offset: float | None = None
    #: Relative* positions: the reference entity and the offsets.
    entity_ref: str | None = None
    dx: float | None = None
    dy: float | None = None


@dataclass
class PositionUse:
    """A Position occurrence with its provenance inside the scenario."""

    position: Position
    #: Entity the position applies to ("" when not entity-bound).
    entity: str = ""
    label: str = ""
    #: True when this is an Init teleport (defines the entity's start pose).
    is_init: bool = False


@dataclass
class RouteAssignment:
    """An AssignRouteAction / AcquirePositionAction for one entity."""

    entity: str
    waypoints: list[Position] = field(default_factory=list)
    label: str = ""


@dataclass
class SpeedCommand:
    """A SpeedAction target relevant to plausibility (absolute targets only)."""

    entity: str
    target_speed_mps: float | None = None
    #: TransitionDynamics with dynamicsDimension == rate: |dv/dt| bound in m/s^2.
    rate_mps2: float | None = None
    label: str = ""


@dataclass
class LaneChange:
    entity: str
    #: TransitionDynamics with dynamicsDimension == time (s) or distance (m).
    duration_s: float | None = None
    distance_m: float | None = None
    label: str = ""


@dataclass
class Scenario:
    source_path: str = "<string>"
    #: Root element kind: "scenario" | "catalog" | "parameter_value_distribution".
    document_kind: str = "scenario"
    header: FileHeader = field(default_factory=FileHeader)
    parameters: dict[str, str] = field(default_factory=dict)
    entities: list[Entity] = field(default_factory=list)
    #: All environment states in declaration order; index 0 is Init when present.
    environments: list[Environment] = field(default_factory=list)
    speed_commands: list[SpeedCommand] = field(default_factory=list)
    lane_changes: list[LaneChange] = field(default_factory=list)
    #: Every Position occurrence with provenance (teleports, route waypoints, ...).
    position_uses: list[PositionUse] = field(default_factory=list)
    routes: list[RouteAssignment] = field(default_factory=list)
    #: All entityRef values seen anywhere in the storyboard/init.
    entity_refs: list[str] = field(default_factory=list)
    road_network_logic_file: str | None = None
    parse_issues: list[ParseIssue] = field(default_factory=list)

    @property
    def osc_version(self) -> str | None:
        if self.header.rev_major is None:
            return None
        return f"{self.header.rev_major}.{self.header.rev_minor or 0}"
