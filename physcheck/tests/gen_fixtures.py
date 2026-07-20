#!/usr/bin/env python3
"""Generate the .xosc test fixtures (one violating fixture per catalog rule).

Run from the repo:  python3 physcheck/tests/gen_fixtures.py
Writes tests/fixtures/{valid,violating}/ and ../examples/{valid,violating}/.

Fixtures are deliberately minimal OpenSCENARIO documents: they carry only the
elements physcheck reads (they are not full-schema-valid; XSD validation is an
external L0 concern, see docs/decisions.md D11).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
EXAMPLES = HERE.parents[1] / "examples" if (HERE.parents[1] / "examples").exists() else None


def env_xml(
    *,
    tod: str | None = None,
    cloud_state: str | None = None,
    oktas: str | None = None,
    temperature: float | None = None,
    pressure: float | None = None,
    sun: dict[str, Any] | None = None,
    fog_range: Any = None,
    precip: dict[str, Any] | None = None,
    wind: dict[str, Any] | None = None,
    friction: Any = None,
    wetness: str | None = None,
) -> str:
    weather_attrs = ""
    if cloud_state is not None:
        weather_attrs += f' cloudState="{cloud_state}"'
    if oktas is not None:
        weather_attrs += f' fractionalCloudCover="{oktas}"'
    if temperature is not None:
        weather_attrs += f' temperature="{temperature}"'
    if pressure is not None:
        weather_attrs += f' atmosphericPressure="{pressure}"'
    parts = [f"        <Weather{weather_attrs}>"]
    if sun is not None:
        attrs = "".join(f' {k}="{v}"' for k, v in sun.items())
        parts.append(f"          <Sun{attrs}/>")
    if fog_range is not None:
        parts.append(f'          <Fog visualRange="{fog_range}"/>')
    if precip is not None:
        attrs = "".join(f' {k}="{v}"' for k, v in precip.items())
        parts.append(f"          <Precipitation{attrs}/>")
    if wind is not None:
        attrs = "".join(f' {k}="{v}"' for k, v in wind.items())
        parts.append(f"          <Wind{attrs}/>")
    parts.append("        </Weather>")
    weather = "\n".join(parts)
    tod_xml = (
        f'        <TimeOfDay animation="false" dateTime="{tod}"/>\n' if tod is not None else ""
    )
    road = ""
    if friction is not None or wetness is not None:
        attrs = ""
        if friction is not None:
            attrs += f' frictionScaleFactor="{friction}"'
        if wetness is not None:
            attrs += f' wetness="{wetness}"'
        road = f"        <RoadCondition{attrs}/>\n"
    return (
        '      <EnvironmentAction>\n        <Environment name="Env">\n'
        + tod_xml
        + weather
        + "\n"
        + road
        + "        </Environment>\n      </EnvironmentAction>\n"
    )


def entity_xml(spec: dict[str, Any]) -> str:
    name = spec["name"]
    kind = spec.get("kind", "vehicle")
    category = spec.get("category", "car")
    inner_attrs = f' name="{name}_model"'
    if kind == "vehicle":
        tag, cat_attr = "Vehicle", "vehicleCategory"
    elif kind == "pedestrian":
        tag, cat_attr = "Pedestrian", "pedestrianCategory"
        inner_attrs += ' model="human"'
    else:
        tag, cat_attr = "MiscObject", "miscObjectCategory"
    inner_attrs += f' {cat_attr}="{category}"'
    if "mass" in spec:
        inner_attrs += f' mass="{spec["mass"]}"'
    body = ""
    if "bbox" in spec:
        length, width, height = spec["bbox"]
        body += (
            "        <BoundingBox>\n"
            '          <Center x="0" y="0" z="0"/>\n'
            f'          <Dimensions length="{length}" width="{width}" height="{height}"/>\n'
            "        </BoundingBox>\n"
        )
    if "perf" in spec:
        max_speed, max_acc, max_dec = spec["perf"]
        body += (
            f'        <Performance maxSpeed="{max_speed}" maxAcceleration="{max_acc}"'
            f' maxDeceleration="{max_dec}"/>\n'
        )
    return (
        f'    <ScenarioObject name="{name}">\n'
        f"      <{tag}{inner_attrs}>\n{body}      </{tag}>\n"
        "    </ScenarioObject>\n"
    )


def speed_action_xml(target: Any = None, rate: Any = None) -> str:
    dyn_dim = "rate" if rate is not None else "time"
    dyn_val = rate if rate is not None else 1
    tgt = target if target is not None else 10
    return (
        "<SpeedAction>"
        f'<SpeedActionDynamics dynamicsShape="linear" value="{dyn_val}"'
        f' dynamicsDimension="{dyn_dim}"/>'
        f'<SpeedActionTarget><AbsoluteTargetSpeed value="{tgt}"/></SpeedActionTarget>'
        "</SpeedAction>"
    )


def lane_change_xml(duration: float) -> str:
    return (
        "<LaneChangeAction>"
        f'<LaneChangeActionDynamics dynamicsShape="sinusoidal" value="{duration}"'
        ' dynamicsDimension="time"/>'
        '<LaneChangeTarget><RelativeTargetLane entityRef="ego" value="1"/></LaneChangeTarget>'
        "</LaneChangeAction>"
    )


def build_xosc(
    *,
    rev: tuple[int, int] = (1, 2),
    description: str = "physcheck fixture",
    entities: list[dict[str, Any]] | None = None,
    env: str = "",
    story_env: str = "",
    extra_init: str = "",
    story_actions: dict[str, list[str]] | None = None,
) -> str:
    entities = entities if entities is not None else [{"name": "ego"}]
    entities_xml = "".join(entity_xml(e) for e in entities)
    init_privates = ""
    for spec in entities:
        acts = []
        if "init_speed" in spec:
            acts.append(speed_action_xml(target=spec["init_speed"]))
        if acts:
            actions = "".join(
                f"        <PrivateAction>{a}</PrivateAction>\n" for a in acts
            )
            init_privates += (
                f'      <Private entityRef="{spec["name"]}">\n{actions}      </Private>\n'
            )
    init_env = f"      <GlobalAction>\n{env}      </GlobalAction>\n" if env else ""

    stories = ""
    story_actions = story_actions or {}
    for spec in entities:
        acts = []
        if "speed_target" in spec or "speed_rate" in spec:
            acts.append(
                speed_action_xml(target=spec.get("speed_target"), rate=spec.get("speed_rate"))
            )
        if "lane_change_time" in spec:
            acts.append(lane_change_xml(spec["lane_change_time"]))
        acts.extend(story_actions.get(spec["name"], []))
        if acts:
            events = "".join(
                "            <Event name=\"ev\" priority=\"overwrite\">"
                f"<Action name=\"a\"><PrivateAction>{a}</PrivateAction></Action>"
                "</Event>\n"
                for a in acts
            )
            stories += (
                '      <ManeuverGroup maximumExecutionCount="1" name="mg">\n'
                f'        <Actors selectTriggeringEntities="false">'
                f'<EntityRef entityRef="{spec["name"]}"/></Actors>\n'
                f'        <Maneuver name="m">\n{events}        </Maneuver>\n'
                "      </ManeuverGroup>\n"
            )
    if story_env:
        stories += (
            '      <ManeuverGroup maximumExecutionCount="1" name="mg_env">\n'
            '        <Actors selectTriggeringEntities="false"/>\n'
            '        <Maneuver name="m_env"><Event name="ev_env" priority="overwrite">'
            f"<Action name=\"a_env\"><GlobalAction>{story_env}</GlobalAction></Action>"
            "</Event></Maneuver>\n"
            "      </ManeuverGroup>\n"
        )
    story = (
        f'    <Story name="story">\n      <Act name="act">\n{stories}      </Act>\n'
        "    </Story>\n"
        if stories
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenSCENARIO>
  <FileHeader revMajor="{rev[0]}" revMinor="{rev[1]}" date="2026-07-20T12:00:00"
              description="{description}" author="physcheck"/>
  <RoadNetwork><LogicFile filepath="road.xodr"/></RoadNetwork>
  <Entities>
{entities_xml}  </Entities>
  <Storyboard>
    <Init>
      <Actions>
{init_env}{extra_init}{init_privates}      </Actions>
    </Init>
{story}  </Storyboard>
</OpenSCENARIO>
"""


CAR = {"name": "ego"}


def _fix(**kwargs: Any) -> str:
    return build_xosc(**kwargs)


# rule id -> xosc content
VIOLATING: dict[str, str] = {
    # --- structural (raw documents) ---
    "SCH-001": "<OpenSCENARIO><FileHeader revMajor='1'",
    "SCH-002": "<OpenSCENARIO><Entities/><Storyboard><Init><Actions/></Init></Storyboard></OpenSCENARIO>",
    "SCH-003": _fix(rev=(2, 0)),
    "SCH-004": "",  # filled in after the dict (needs a post-build replace)
    "SCH-005": _fix(entities=[{"name": "ego", "init_speed": "$undeclaredSpeed"}]),
    "SCH-006": _fix(env=env_xml(fog_range="abc")),
    "SCH-007": """<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="2026-07-20T12:00:00" description="f" author="p"/>
  <Entities>
    <ScenarioObject name="ego">
      <CatalogReference catalogName="VehicleCatalog" entryName="car_white"/>
    </ScenarioObject>
  </Entities>
  <Storyboard><Init><Actions/></Init></Storyboard>
</OpenSCENARIO>
""",
    "SCH-008": _fix(env=env_xml(tod="yesterday-noon")),
    # --- schema ranges (YAML L0) ---
    "SCH-101": _fix(rev=(1, 0), env=env_xml(precip={"precipitationType": "rain", "intensity": 1.5})),
    "SCH-102": _fix(env=env_xml(precip={"precipitationType": "rain", "precipitationIntensity": -5})),
    "SCH-103": _fix(env=env_xml(precip={"precipitationType": "hail", "precipitationIntensity": 5})),
    "SCH-104": _fix(rev=(1, 0), env=env_xml(cloud_state="stormy")),
    "SCH-105": _fix(env=env_xml(wetness="soaked")),
    "SCH-106": _fix(env=env_xml(fog_range=0)),
    "SCH-107": _fix(env=env_xml(friction=0)),
    "SCH-108": _fix(env=env_xml(temperature=100)),
    "SCH-109": _fix(env=env_xml(pressure=50000)),
    "SCH-110": _fix(env=env_xml(sun={"azimuth": 1.0, "elevation": 4.0, "illuminance": 1000})),
    "SCH-111": _fix(entities=[{"name": "ego", "init_speed": -5}]),
    "SCH-112": _fix(entities=[{"name": "ego", "bbox": (0, 1.8, 1.5)}]),
    "SCH-113": _fix(entities=[{"name": "ego", "perf": (-1, 5, 8)}]),
    "SCH-114": _fix(entities=[{"name": "ego", "mass": 0}]),
    # --- version gating ---
    "VER-001": _fix(rev=(1, 0), env=env_xml(precip={"precipitationType": "rain", "precipitationIntensity": 5})),
    "VER-002": _fix(rev=(1, 0), env=env_xml(wind={"direction": 0, "speed": 5})),
    "VER-003": _fix(rev=(1, 0), env=env_xml(temperature=288.15)),
    "VER-004": _fix(rev=(1, 1), env=env_xml(oktas="twoOktas")),
    "VER-005": _fix(rev=(1, 1), env=env_xml(wetness="dry")),
    "VER-006": _fix(rev=(1, 1), env=env_xml(sun={"azimuth": 1.0, "elevation": 0.5, "illuminance": 5000})),
    "VER-007": _fix(rev=(1, 2), env=env_xml(precip={"precipitationType": "rain", "intensity": 0.5})),
    "VER-008": _fix(rev=(1, 2), env=env_xml(cloud_state="free")),
    "VER-009": _fix(rev=(1, 2), env=env_xml(sun={"azimuth": 1.0, "elevation": 0.5, "intensity": 5000})),
    "VER-010": _fix(rev=(1, 0), entities=[{"name": "ego", "mass": 1500}]),
    # --- cross-environment ---
    "FRI-024": _fix(
        env=env_xml(wetness="dry", friction=0.8),
        story_env=env_xml(wetness="wetWithPuddles", friction=0.85).strip(),
    ),
    # --- atmosphere ---
    "ATM-001": _fix(env=env_xml(fog_range=5000)),
    "ATM-002": _fix(env=env_xml(fog_range=400000)),
    "ATM-003": _fix(env=env_xml(fog_range=20000,
                                precip={"precipitationType": "rain", "precipitationIntensity": 50})),
    "ATM-004": _fix(env=env_xml(fog_range=9000,
                                precip={"precipitationType": "snow", "precipitationIntensity": 5})),
    "ATM-005": _fix(env=env_xml(fog_range=100, temperature=228.15)),
    "ATM-006": _fix(env=env_xml(oktas="eightOktas",
                                sun={"azimuth": 3.14, "elevation": 0.5, "illuminance": 100000})),
    "ATM-007": _fix(env=env_xml(fog_range=150,
                                sun={"azimuth": 3.14, "elevation": 0.5, "illuminance": 90000})),
    # --- solar ---
    "SOL-001": _fix(env=env_xml(sun={"azimuth": 1.0, "elevation": 2.0, "illuminance": 1000})),
    "SOL-002": _fix(env=env_xml(sun={"azimuth": 6.5, "elevation": 0.5, "illuminance": 1000})),
    "SOL-003": _fix(env=env_xml(sun={"azimuth": 3.1, "elevation": 1.0, "illuminance": 150000})),
    "SOL-004": _fix(env=env_xml(sun={"azimuth": 3.1, "elevation": 1.0, "illuminance": 125000})),
    "SOL-005": _fix(env=env_xml(sun={"azimuth": 3.1, "elevation": -0.1, "illuminance": 5000})),
    "SOL-006": _fix(env=env_xml(sun={"azimuth": 3.1, "elevation": 0.05, "illuminance": 100000})),
    "SOL-007": _fix(env=env_xml(tod="2026-06-21T02:00:00",
                                sun={"azimuth": 3.1, "elevation": 1.0, "illuminance": 90000})),
    "SOL-008": _fix(env=env_xml(tod="2026-06-21T23:00:00", sun={"illuminance": 50000})),
    # --- precipitation & thermodynamics ---
    "PRE-001": _fix(env=env_xml(precip={"precipitationType": "dry", "precipitationIntensity": 5})),
    "PRE-002": _fix(env=env_xml(precip={"precipitationType": "rain", "precipitationIntensity": 0})),
    "PRE-003": _fix(env=env_xml(precip={"precipitationType": "rain", "precipitationIntensity": 80})),
    "PRE-004": _fix(env=env_xml(precip={"precipitationType": "rain", "precipitationIntensity": 500})),
    "PRE-005": _fix(env=env_xml(precip={"precipitationType": "snow", "precipitationIntensity": 2000})),
    "PRE-006": _fix(env=env_xml(precip={"precipitationType": "snow", "precipitationIntensity": 20})),
    "PRE-007": _fix(env=env_xml(precip={"precipitationType": "snow", "precipitationIntensity": 60})),
    "PRE-008": _fix(env=env_xml(temperature=268.15,
                                precip={"precipitationType": "rain", "precipitationIntensity": 5})),
    "PRE-009": _fix(env=env_xml(temperature=258.15,
                                precip={"precipitationType": "rain", "precipitationIntensity": 5})),
    "PRE-010": _fix(env=env_xml(temperature=276.65,
                                precip={"precipitationType": "snow", "precipitationIntensity": 2})),
    "PRE-011": _fix(env=env_xml(temperature=281.15,
                                precip={"precipitationType": "snow", "precipitationIntensity": 2})),
    "PRE-012": _fix(env=env_xml(oktas="zeroOktas",
                                precip={"precipitationType": "rain", "precipitationIntensity": 5})),
    "PRE-013": _fix(env=env_xml(oktas="twoOktas",
                                precip={"precipitationType": "rain", "precipitationIntensity": 20})),
    "PRE-014": _fix(env=env_xml(temperature=333.15)),
    "PRE-015": _fix(env=env_xml(wind={"direction": 0, "speed": 20})),
    "PRE-016": _fix(env=env_xml(wind={"direction": 0, "speed": 40})),
    "PRE-017": _fix(env=env_xml(wind={"direction": 0, "speed": 150})),
    # --- friction & road ---
    "FRI-001": _fix(env=env_xml(wetness="moist", friction=1.1)),
    "FRI-002": _fix(env=env_xml(wetness="dry", friction=0.5,
                                precip={"precipitationType": "dry", "precipitationIntensity": 0})),
    "FRI-003": _fix(env=env_xml(wetness="wetWithPuddles", friction=0.95)),
    "FRI-004": _fix(env=env_xml(wetness="lowFlooded", friction=0.9)),
    "FRI-005": _fix(env=env_xml(wetness="highFlooded", friction=0.7)),
    "FRI-006": _fix(env=env_xml(friction=1.5)),
    "FRI-007": _fix(env=env_xml(friction=0.02)),
    "FRI-008": _fix(env=env_xml(wetness="dry",
                                precip={"precipitationType": "rain", "precipitationIntensity": 5})),
    "FRI-009": _fix(rev=(1, 0), env=env_xml(wetness="dry",
                                            precip={"precipitationType": "rain", "intensity": 0.5})),
    "FRI-010": _fix(env=env_xml(wetness="moist",
                                precip={"precipitationType": "rain", "precipitationIntensity": 20})),
    "FRI-011": _fix(entities=[{"name": "ego", "init_speed": 30}],
                    env=env_xml(wetness="lowFlooded", friction=0.6)),
    "FRI-012": _fix(entities=[{"name": "ego", "init_speed": 30}],
                    env=env_xml(wetness="wetWithPuddles", friction=0.85)),
    "FRI-013": _fix(entities=[{"name": "ego", "perf": (60, 3, 9)}],
                    env=env_xml(friction=0.3)),
    "FRI-014": _fix(entities=[{"name": "ego", "perf": (60, 3, 5)}],
                    env=env_xml(wetness="dry")),
    "FRI-015": _fix(entities=[{"name": "ego", "perf": (60, 3, 9)}],
                    env=env_xml(wetness="wetWithPuddles")),
    "FRI-016": _fix(entities=[{"name": "ego", "perf": (60, 3, 6)}],
                    env=env_xml(temperature=268.15,
                                precip={"precipitationType": "snow", "precipitationIntensity": 2})),
    "FRI-017": _fix(env=env_xml(temperature=268.15, friction=0.8,
                                precip={"precipitationType": "snow", "precipitationIntensity": 2})),
    "FRI-018": _fix(env=env_xml(temperature=268.15, wetness="moist", friction=0.6)),
    "FRI-019": _fix(env=env_xml(temperature=258.15, wetness="moist")),
    "FRI-020": _fix(env=env_xml(temperature=248.15, wetness="moist")),
    "FRI-021": _fix(env=env_xml(temperature=268.15, friction=0.8,
                                precip={"precipitationType": "rain", "precipitationIntensity": 5})),
    "FRI-022": _fix(env=env_xml(temperature=288.15, wetness="dry", friction=0.4,
                                precip={"precipitationType": "dry", "precipitationIntensity": 0})),
    "FRI-023": _fix(entities=[{"name": "ego", "perf": (60, 8, 3)}],
                    env=env_xml(friction=0.3)),
    # --- kinematics ---
    "KIN-001": _fix(entities=[{"name": "p1", "kind": "pedestrian", "category": "pedestrian",
                               "init_speed": 15}]),
    "KIN-002": _fix(entities=[{"name": "p1", "kind": "pedestrian", "category": "pedestrian",
                               "init_speed": 9}]),
    "KIN-003": _fix(entities=[{"name": "p1", "kind": "pedestrian", "category": "pedestrian",
                               "init_speed": 4}]),
    "KIN-004": _fix(entities=[{"name": "p1", "kind": "pedestrian", "category": "pedestrian",
                               "speed_target": 2, "speed_rate": 12}]),
    "KIN-005": _fix(entities=[{"name": "p1", "kind": "pedestrian", "category": "pedestrian",
                               "speed_target": 2, "speed_rate": 6}]),
    "KIN-006": _fix(entities=[{"name": "b1", "category": "bicycle", "init_speed": 45}]),
    "KIN-007": _fix(entities=[{"name": "b1", "category": "bicycle", "init_speed": 15}]),
    "KIN-008": _fix(entities=[{"name": "b1", "category": "bicycle",
                               "speed_target": 8, "speed_rate": 3}]),
    "KIN-009": _fix(entities=[{"name": "a1", "kind": "pedestrian", "category": "animal",
                               "init_speed": 25}]),
    "KIN-010": _fix(entities=[{"name": "a1", "kind": "pedestrian", "category": "animal",
                               "init_speed": 40}]),
    "KIN-011": _fix(entities=[{"name": "ego", "perf": (150, 5, 8)}]),
    "KIN-012": _fix(entities=[{"name": "ego", "perf": (110, 5, 8)}]),
    "KIN-013": _fix(entities=[{"name": "t1", "category": "truck", "perf": (50, 2, 6)}]),
    "KIN-014": _fix(entities=[{"name": "ego", "perf": (60, 5, 12.5)}]),
    "KIN-015": _fix(entities=[{"name": "t1", "category": "truck", "perf": (25, 2, 9)}]),
    "KIN-016": _fix(entities=[{"name": "t1", "category": "truck", "perf": (25, 2, 4)}]),
    "KIN-017": _fix(entities=[{"name": "b1", "category": "bicycle", "perf": (10, 1, 8)}]),
    "KIN-018": _fix(entities=[{"name": "ego", "perf": (60, 20, 8)}]),
    "KIN-019": _fix(entities=[{"name": "ego", "perf": (60, 10, 8)}]),
    "KIN-020": _fix(entities=[{"name": "t1", "category": "truck", "perf": (25, 4, 6)}]),
    "KIN-021": _fix(entities=[{"name": "ego", "lane_change_time": 0.5}]),
    "KIN-022": _fix(entities=[{"name": "ego", "lane_change_time": 1.5}]),
    "KIN-023": _fix(entities=[{"name": "ego", "perf": (20, 5, 8), "speed_target": 30}]),
    "KIN-024": _fix(entities=[{"name": "ego", "speed_target": 40, "speed_rate": 15}]),
    # --- entities ---
    "ENT-001": _fix(entities=[{"name": "t1", "category": "truck", "bbox": (10, 2.8, 3.5)}]),
    "ENT-002": _fix(entities=[{"name": "ego", "bbox": (4.5, 2.3, 1.5)}]),
    "ENT-003": _fix(entities=[{"name": "ego", "bbox": (7, 1.8, 1.5)}]),
    "ENT-004": _fix(entities=[{"name": "t1", "category": "truck", "bbox": (20, 2.5, 3.5)}]),
    "ENT-005": _fix(entities=[{"name": "bus1", "category": "bus", "bbox": (16, 2.5, 3.2)}]),
    "ENT-006": _fix(entities=[{"name": "t1", "category": "truck", "bbox": (10, 2.5, 5.5)}]),
    "ENT-007": _fix(entities=[{"name": "t1", "category": "truck", "bbox": (10, 2.5, 4.3)}]),
    "ENT-008": _fix(entities=[{"name": "ego", "bbox": (4.5, 1.8, 2.5)}]),
    "ENT-009": _fix(entities=[{"name": "p1", "kind": "pedestrian", "category": "pedestrian",
                               "bbox": (0.5, 0.5, 3.0)}]),
    "ENT-010": _fix(entities=[{"name": "p1", "kind": "pedestrian", "category": "pedestrian",
                               "bbox": (0.5, 0.5, 2.3)}]),
    "ENT-011": _fix(entities=[{"name": "b1", "category": "bicycle", "bbox": (2.5, 0.7, 1.2)}]),
    "ENT-012": _fix(entities=[{"name": "ego", "mass": 5000}]),
    "ENT-013": _fix(entities=[{"name": "t1", "category": "truck", "mass": 60000}]),
}

# SCH-004 needs a dangling entityRef inside the story.
VIOLATING["SCH-004"] = _fix(entities=[{"name": "ego", "speed_target": 10}]).replace(
    '<EntityRef entityRef="ego"/>', '<EntityRef entityRef="ghost"/>'
)

VALID: dict[str, str] = {
    "valid_clear_noon": _fix(
        description="clear dry noon, all attributes consistent",
        entities=[{"name": "ego", "bbox": (4.6, 1.86, 1.5), "perf": (62, 5, 9),
                   "mass": 1600, "init_speed": 25, "speed_target": 30},
                  {"name": "ped", "kind": "pedestrian", "category": "pedestrian",
                   "bbox": (0.5, 0.6, 1.8), "init_speed": 1.4}],
        env=env_xml(tod="2026-06-21T12:00:00", oktas="oneOktas", temperature=295.15,
                    pressure=101300,
                    sun={"azimuth": 3.14, "elevation": 1.05, "illuminance": 95000},
                    precip={"precipitationType": "dry", "precipitationIntensity": 0},
                    friction=1.0, wetness="dry"),
    ),
    "valid_rain_wet": _fix(
        description="moderate rain on a wet road, consistent couplings",
        entities=[{"name": "ego", "bbox": (4.6, 1.86, 1.5), "perf": (62, 3, 7),
                   "mass": 1600, "init_speed": 20, "lane_change_time": 4.0}],
        env=env_xml(tod="2026-10-05T09:30:00", oktas="sevenOktas", temperature=283.15,
                    sun={"azimuth": 2.4, "elevation": 0.3, "illuminance": 12000},
                    precip={"precipitationType": "rain", "precipitationIntensity": 6},
                    wind={"direction": 1.2, "speed": 6},
                    friction=0.7, wetness="wetWithPuddles"),
    ),
    "valid_night": _fix(
        description="clear night, sun below horizon, no illuminance",
        entities=[{"name": "ego", "bbox": (4.6, 1.86, 1.5), "perf": (62, 5, 9),
                   "init_speed": 15}],
        env=env_xml(tod="2026-03-10T23:30:00", oktas="zeroOktas", temperature=278.15,
                    sun={"azimuth": 0.2, "elevation": -0.6, "illuminance": 0},
                    precip={"precipitationType": "dry", "precipitationIntensity": 0},
                    friction=1.0, wetness="dry"),
    ),
}

EXAMPLE_VIOLATING: dict[str, str] = {
    "foggy_contradiction": _fix(
        description="dense fog declared with huge visual range, rain on a dry high-grip road",
        entities=[{"name": "ego", "bbox": (4.5, 1.8, 1.5), "perf": (69.4, 200, 10),
                   "init_speed": 30}],
        env=env_xml(tod="2026-01-15T10:00:00", oktas="twoOktas", temperature=288.15,
                    fog_range=30000,
                    sun={"azimuth": 2.8, "elevation": 0.4, "illuminance": 80000},
                    precip={"precipitationType": "rain", "precipitationIntensity": 60},
                    friction=1.4, wetness="dry"),
    ),
    "impossible_kinematics": _fix(
        description="sprinting pedestrian at 20 m/s, 0.5 s lane change, 540 km/h car",
        entities=[{"name": "ego", "bbox": (4.5, 1.8, 1.5), "perf": (150, 5, 9),
                   "init_speed": 40, "lane_change_time": 0.5},
                  {"name": "runner", "kind": "pedestrian", "category": "pedestrian",
                   "bbox": (0.5, 0.6, 1.8), "init_speed": 20}],
    ),
    "midnight_sun_snow": _fix(
        description="high summer sun at 2 am plus snow at +30 degC",
        env=env_xml(tod="2026-06-21T02:00:00", oktas="zeroOktas", temperature=303.15,
                    sun={"azimuth": 0.5, "elevation": 1.2, "illuminance": 140000},
                    precip={"precipitationType": "snow", "precipitationIntensity": 8}),
        entities=[{"name": "ego", "bbox": (4.5, 1.8, 1.5), "perf": (62, 5, 9),
                   "init_speed": 20}],
    ),
}


def main() -> None:
    (FIXTURES / "violating").mkdir(parents=True, exist_ok=True)
    (FIXTURES / "valid").mkdir(parents=True, exist_ok=True)
    for rule_id, content in sorted(VIOLATING.items()):
        (FIXTURES / "violating" / f"{rule_id}.xosc").write_text(content, encoding="utf-8")
    for name, content in sorted(VALID.items()):
        (FIXTURES / "valid" / f"{name}.xosc").write_text(content, encoding="utf-8")
    print(f"wrote {len(VIOLATING)} violating + {len(VALID)} valid fixtures under {FIXTURES}")
    if EXAMPLES is not None:
        (EXAMPLES / "valid").mkdir(parents=True, exist_ok=True)
        (EXAMPLES / "violating").mkdir(parents=True, exist_ok=True)
        for name, content in sorted(VALID.items()):
            (EXAMPLES / "valid" / f"{name.removeprefix('valid_')}.xosc").write_text(
                content, encoding="utf-8"
            )
        for name, content in sorted(EXAMPLE_VIOLATING.items()):
            (EXAMPLES / "violating" / f"{name}.xosc").write_text(content, encoding="utf-8")
        print(f"wrote examples under {EXAMPLES}")


if __name__ == "__main__":
    main()
