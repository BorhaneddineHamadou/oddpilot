"""Solar position, pure Python (NOAA solar calculator / Meeus chapter 25).

Accuracy ~0.01 deg for years 1900-2100 — far tighter than the 0.7 deg
refraction-dominated tolerance the solar_geo rules use (docs/catalog_report.md
§Solar). The full NREL SPA is unnecessary at lint tolerances; NOAA's
implementation is the cross-validation standard used in the research notes.

Azimuth convention matches OpenSCENARIO's Sun: 0 = north, pi/2 = east
(clockwise from above); elevation is refraction-corrected (Saemundsson 1986
as used by NOAA).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

__all__ = ["solar_declination_deg", "solar_position_deg"]


def _julian_day(dt: datetime) -> float:
    """Julian day from a UTC datetime (Meeus eq. 7.1)."""
    year, month = dt.year, dt.month
    day = (
        dt.day
        + dt.hour / 24.0
        + dt.minute / 1440.0
        + (dt.second + dt.microsecond / 1e6) / 86400.0
    )
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5


def _solar_coordinates(jd: float) -> tuple[float, float, float]:
    """(declination deg, equation of time minutes, apparent longitude deg)."""
    t = (jd - 2451545.0) / 36525.0
    mean_long = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360.0
    mean_anom = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    ecc = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    m_rad = math.radians(mean_anom)
    center = (
        math.sin(m_rad) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * m_rad) * (0.019993 - 0.000101 * t)
        + math.sin(3 * m_rad) * 0.000289
    )
    true_long = mean_long + center
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    obliq_sec = 21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))
    mean_obliq = 23.0 + (26.0 + obliq_sec / 60.0) / 60.0
    obliq = mean_obliq + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(
        math.asin(math.sin(math.radians(obliq)) * math.sin(math.radians(app_long)))
    )
    y = math.tan(math.radians(obliq / 2.0)) ** 2
    l0_rad = math.radians(mean_long)
    eqtime = 4.0 * math.degrees(
        y * math.sin(2 * l0_rad)
        - 2.0 * ecc * math.sin(m_rad)
        + 4.0 * ecc * y * math.sin(m_rad) * math.cos(2 * l0_rad)
        - 0.5 * y * y * math.sin(4 * l0_rad)
        - 1.25 * ecc * ecc * math.sin(2 * m_rad)
    )
    return decl, eqtime, app_long


def solar_declination_deg(dt_utc: datetime) -> float:
    """Solar declination in degrees for a UTC datetime."""
    return _solar_coordinates(_julian_day(_as_utc(dt_utc)))[0]


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def solar_position_deg(dt_utc: datetime, lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """(elevation deg, azimuth deg) of the sun; azimuth clockwise from north.

    ``dt_utc`` is taken as UTC (naive datetimes are assumed UTC); longitude is
    positive east. Elevation includes NOAA's atmospheric refraction correction.
    """
    dt = _as_utc(dt_utc)
    jd = _julian_day(dt)
    decl, eqtime, _ = _solar_coordinates(jd)
    minutes = dt.hour * 60.0 + dt.minute + (dt.second + dt.microsecond / 1e6) / 60.0
    true_solar_min = (minutes + eqtime + 4.0 * lon_deg) % 1440.0
    hour_angle = true_solar_min / 4.0 - 180.0
    if hour_angle < -180.0:
        hour_angle += 360.0
    lat = math.radians(lat_deg)
    decl_rad = math.radians(decl)
    ha_rad = math.radians(hour_angle)
    cos_zenith = math.sin(lat) * math.sin(decl_rad) + math.cos(lat) * math.cos(decl_rad) * math.cos(
        ha_rad
    )
    cos_zenith = min(1.0, max(-1.0, cos_zenith))
    zenith = math.degrees(math.acos(cos_zenith))
    elevation = 90.0 - zenith

    denom = math.cos(lat) * math.sin(math.radians(zenith))
    if abs(denom) > 1e-12:
        cos_az = (math.sin(lat) * cos_zenith - math.sin(decl_rad)) / denom
        cos_az = min(1.0, max(-1.0, cos_az))
        azimuth = math.degrees(math.acos(cos_az))
        if hour_angle > 0:
            azimuth = (azimuth + 180.0) % 360.0
        else:
            azimuth = (540.0 - azimuth) % 360.0
    else:  # sun at zenith/nadir or observer at a pole: azimuth undefined; pick south
        azimuth = 180.0

    return elevation + _refraction_deg(elevation), azimuth


def _refraction_deg(elevation_deg: float) -> float:
    """NOAA's piecewise atmospheric refraction correction (degrees)."""
    if elevation_deg > 85.0:
        return 0.0
    tan_e = math.tan(math.radians(elevation_deg))
    if elevation_deg > 5.0:
        arcsec = 58.1 / tan_e - 0.07 / tan_e**3 + 0.000086 / tan_e**5
    elif elevation_deg > -0.575:
        arcsec = 1735.0 + elevation_deg * (
            -518.2 + elevation_deg * (103.4 + elevation_deg * (-12.79 + elevation_deg * 0.711))
        )
    else:
        arcsec = -20.774 / tan_e
    return arcsec / 3600.0
