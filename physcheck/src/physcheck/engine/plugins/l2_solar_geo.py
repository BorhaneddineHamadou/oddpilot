"""L2 solar_geo pack: declared sun vs geography and ephemeris.

The deferred checks from docs/catalog_report.md §Solar, enabled by the
OpenDRIVE ``geoReference`` (latitude/longitude of the map origin):

- GEO-001/002 - date-free declination bound: from (lat, elevation, azimuth) the
  implied solar declination sin(delta) = sin(phi) sin(h) + cos(phi) cos(h) cos(A)
  must satisfy |delta| <= 23.44 deg for the sun to be there on ANY date/time.
- GEO-003/004 - azimuth-free maximum elevation h <= 90 - max(0, |phi| - 23.44).
- GEO-005/006 - full ephemeris consistency of (elevation, azimuth) with the
  declared TimeOfDay, taking the minimum discrepancy over the timezone
  interpretations {UTC, local standard, local DST} since OSC 1.x leaves the
  timezone undefined (decisions.md D5); 0.7 deg warning / 5 deg error
  tolerances (refraction-dominated; docs/decisions.md D25).

Positions inside a map are treated as at the geoReference origin: town-scale
maps span a few km, which moves the sun by well under 0.1 deg.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from physcheck.ephemeris import solar_position_deg
from physcheck.ir.model import Scenario
from physcheck.xodr.model import XodrMap

if TYPE_CHECKING:  # imported late at runtime to avoid a cycle with engine.py
    from physcheck.engine.engine import Finding

__all__ = ["PLUGIN_RULES", "solar_geo_findings"]

_MEEUS = (
    "Meeus, J., Astronomical Algorithms, 2nd ed., Willmann-Bell, Ch. 22/25 "
    "(obliquity 23.44 deg; solar coordinates); NOAA ESRL solar position calculator"
)
_EPHEMERIS_CITE = (
    "Meeus, J., Astronomical Algorithms, 2nd ed., Ch. 25 (solar position); NOAA "
    "ESRL solar calculator (implementation standard); Saemundsson (1986) refraction"
)

#: id -> (layer, severity, title, citation)
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    "GEO-001": (
        "L2", "error",
        "Sun direction impossible at the map's latitude on any date",
        _MEEUS,
    ),
    "GEO-002": (
        "L2", "warning",
        "Sun direction implausible at the map's latitude",
        _MEEUS,
    ),
    "GEO-003": (
        "L2", "error",
        "Sun elevation exceeds the maximum possible at the map's latitude",
        _MEEUS,
    ),
    "GEO-004": (
        "L2", "warning",
        "Sun elevation close to impossible at the map's latitude",
        _MEEUS,
    ),
    "GEO-005": (
        "L2", "error",
        "Declared sun position contradicts the ephemeris for the declared time",
        _EPHEMERIS_CITE,
    ),
    "GEO-006": (
        "L2", "warning",
        "Declared sun position deviates from the ephemeris for the declared time",
        _EPHEMERIS_CITE,
    ),
}

_OBLIQUITY_DEG = 23.44
_WARN_TOL_DEG = 0.7
_ERROR_TOL_DEG = 5.0


def solar_geo_findings(scenario: Scenario, xmap: XodrMap) -> list[Finding]:
    lat = xmap.geo.lat0_deg
    lon = xmap.geo.lon0_deg
    if lat is None:
        return []  # no geodetic anchor: the whole pack is inapplicable
    findings: list[Finding] = []
    n_envs = len(scenario.environments)
    for i, env in enumerate(scenario.environments):
        label = env.label if n_envs == 1 else f"{env.label} (#{i + 1})"
        sun = env.weather.sun if env.weather is not None else None
        if sun is None or sun.elevation_rad is None:
            continue
        elev = math.degrees(sun.elevation_rad)
        azim = math.degrees(sun.azimuth_rad) if sun.azimuth_rad is not None else None
        findings.extend(_direction_findings(scenario, label, lat, elev, azim))
        when = env.time_of_day.when if env.time_of_day is not None else None
        if when is not None and lon is not None:
            findings.extend(
                _ephemeris_findings(scenario, label, lat, lon, when, elev, azim)
            )
    return findings


def _mk(rule_id: str, message: str, scenario: Scenario, context: str,
        values: dict[str, object]) -> Finding:
    from physcheck.engine.engine import Finding

    layer, severity, title, citation = PLUGIN_RULES[rule_id]
    return Finding(
        rule_id=rule_id, severity=severity, layer=layer, title=title,
        message=message, file=scenario.source_path, context=context,
        values=values, citation=citation,
    )


def _direction_findings(
    scenario: Scenario, context: str, lat: float, elev: float, azim: float | None
) -> list[Finding]:
    lat_rad, elev_rad = math.radians(lat), math.radians(elev)
    if azim is not None:
        sin_decl = (
            math.sin(lat_rad) * math.sin(elev_rad)
            + math.cos(lat_rad) * math.cos(elev_rad) * math.cos(math.radians(azim))
        )
        decl = math.degrees(math.asin(min(1.0, max(-1.0, sin_decl))))
        excess = abs(decl) - _OBLIQUITY_DEG
        if excess <= _WARN_TOL_DEG:
            return []
        rule_id = "GEO-001" if excess > _ERROR_TOL_DEG else "GEO-002"
        return [
            _mk(
                rule_id,
                f"Sun at elevation {elev:.1f} deg / azimuth {azim:.1f} deg seen from "
                f"latitude {lat:.2f} deg implies solar declination {decl:.1f} deg — "
                f"the sun never leaves the +-{_OBLIQUITY_DEG} deg declination band, "
                "so this direction is impossible on any date or time.",
                scenario, context,
                {"sun.elevation_deg": round(elev, 2), "sun.azimuth_deg": round(azim, 2),
                 "implied.declination_deg": round(decl, 2), "map.lat_deg": lat},
            )
        ]
    max_elev = 90.0 - max(0.0, abs(lat) - _OBLIQUITY_DEG)
    excess = elev - max_elev
    if excess <= _WARN_TOL_DEG:
        return []
    rule_id = "GEO-003" if excess > _ERROR_TOL_DEG else "GEO-004"
    return [
        _mk(
            rule_id,
            f"Sun elevation {elev:.1f} deg exceeds the highest sun possible at "
            f"latitude {lat:.2f} deg ({max_elev:.1f} deg, reached at the solstice).",
            scenario, context,
            {"sun.elevation_deg": round(elev, 2), "max.elevation_deg": round(max_elev, 2),
             "map.lat_deg": lat},
        )
    ]


def _time_interpretations(when: datetime, lon: float) -> list[tuple[str, datetime]]:
    """UTC datetimes for each plausible reading of an OSC dateTime (D5/D25)."""
    if when.tzinfo is not None:
        return [("declared timezone", when.astimezone(timezone.utc))]
    utc = when.replace(tzinfo=timezone.utc)
    std_offset = round(lon / 15.0)
    return [
        ("UTC", utc),
        (f"local standard (UTC{std_offset:+d})", utc - timedelta(hours=std_offset)),
        (f"local DST (UTC{std_offset + 1:+d})", utc - timedelta(hours=std_offset + 1)),
    ]


def _ephemeris_findings(
    scenario: Scenario, context: str, lat: float, lon: float,
    when: datetime, elev: float, azim: float | None,
) -> list[Finding]:
    best: tuple[float, str, float, float] | None = None  # (discrepancy, name, el, az)
    for name, utc in _time_interpretations(when, lon):
        cal_elev, cal_azim = solar_position_deg(utc, lat, lon)
        if azim is not None:
            cos_sep = (
                math.sin(math.radians(elev)) * math.sin(math.radians(cal_elev))
                + math.cos(math.radians(elev)) * math.cos(math.radians(cal_elev))
                * math.cos(math.radians(azim - cal_azim))
            )
            sep = math.degrees(math.acos(min(1.0, max(-1.0, cos_sep))))
        else:
            sep = abs(elev - cal_elev)
        if elev < 0 and cal_elev < 0:
            sep = 0.0  # both below the horizon: exact night-sun position is irrelevant
        if best is None or sep < best[0]:
            best = (sep, name, cal_elev, cal_azim)
    if best is None or best[0] <= _WARN_TOL_DEG:
        return []
    sep, name, cal_elev, cal_azim = best
    rule_id = "GEO-005" if sep > _ERROR_TOL_DEG else "GEO-006"
    declared = (
        f"elevation {elev:.1f} deg"
        + (f" / azimuth {azim:.1f} deg" if azim is not None else "")
    )
    return [
        _mk(
            rule_id,
            f"Declared sun ({declared}) is {sep:.1f} deg away from the ephemeris sun "
            f"(elevation {cal_elev:.1f} deg / azimuth {cal_azim:.1f} deg) computed for "
            f"{when.isoformat()} at the map origin ({lat:.2f}, {lon:.2f}) — closest "
            f"timezone interpretation: {name}.",
            scenario, context,
            {"sun.discrepancy_deg": round(sep, 2),
             "ephemeris.elevation_deg": round(cal_elev, 2),
             "ephemeris.azimuth_deg": round(cal_azim, 2),
             "interpretation": name},
        )
    ]
