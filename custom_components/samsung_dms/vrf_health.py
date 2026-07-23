"""VRF cycle diagnostics for Samsung DVM outdoor units.

Turns the raw cycle-monitoring values (pressures, temperatures, compressor
data) into refrigerant-side metrics and a plain-language health verdict, the
way a service engineer reads a gauge manifold. R410A only (DVM S/DVM Plus).

All thresholds are advisory and deliberately conservative — this flags "worth
looking at", it is not a substitute for a technician with gauges.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any

# R410A saturated pressure (bar, absolute) -> temperature (°C).
_R410A_PT: list[tuple[float, float]] = [
    (3.99, -20.0), (5.79, -10.0), (8.14, 0.0), (9.55, 5.0), (11.13, 10.0),
    (12.91, 15.0), (14.89, 20.0), (17.09, 25.0), (19.52, 30.0), (22.21, 35.0),
    (25.16, 40.0), (28.39, 45.0), (31.92, 50.0), (35.78, 55.0), (39.97, 60.0),
    (44.50, 65.0),
]
_PRESSURES = [p for p, _ in _R410A_PT]
_TEMPS = [t for _, t in _R410A_PT]

# 1 kgf/cm² = 0.980665 bar; DMS pressures are gauge, atmospheric ≈ 1.01325 bar.
_KGFCM2_TO_BAR = 0.980665
_ATM_BAR = 1.01325

_INVALID = -999.0  # DMS uses -1000 for "not available"

# Thresholds (cooling-mode, R410A).
_DISCHARGE_WARN, _DISCHARGE_ALERT = 95.0, 110.0
_IPM_WARN, _IPM_ALERT = 80.0, 90.0
_APPROACH_WARN, _APPROACH_ALERT = 16.0, 24.0  # condenser fouling
# Combined-suction superheat is NOT a reliable charge gauge on VRF (it mixes the
# return gas of every running indoor EEV over pipe runs up to ~220 m); only very
# low (floodback) or very high (extreme) values are actionable.
_SUPERHEAT_LOW, _SUPERHEAT_HIGH = 1.0, 30.0
# Below this compressor frequency the unit is starting / oil-returning / at very
# low part-load: cycle-quality readings are transient. Compute the metrics for
# display, but do not let them escalate the verdict.
_MIN_STEADY_HZ = 25.0

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ALERT = "alert"
_RANK = {STATUS_OK: 0, STATUS_WARNING: 1, STATUS_ALERT: 2}


@dataclass(frozen=True)
class OutdoorHealth:
    """Computed diagnostics for one outdoor unit."""

    status: str = STATUS_OK
    issues: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)


def saturation_temp(kgfcm2_gauge: float) -> float:
    """R410A saturation temperature (°C) for a gauge pressure in kgf/cm²."""
    p_abs = kgfcm2_gauge * _KGFCM2_TO_BAR + _ATM_BAR
    i = bisect.bisect_left(_PRESSURES, p_abs)
    if i <= 0:
        return _TEMPS[0]
    if i >= len(_PRESSURES):
        return _TEMPS[-1]
    span = _PRESSURES[i] - _PRESSURES[i - 1]
    frac = (p_abs - _PRESSURES[i - 1]) / span if span else 0.0
    return round(_TEMPS[i - 1] + frac * (_TEMPS[i] - _TEMPS[i - 1]), 1)


def _f(unit: dict[str, Any], key: str) -> float | None:
    try:
        value = float(unit[key])
    except (KeyError, TypeError, ValueError):
        return None
    return None if value <= _INVALID else value


def _escalate(current: str, new: str) -> str:
    return new if _RANK[new] > _RANK[current] else current


def assess_outdoor(unit: dict[str, Any]) -> OutdoorHealth:
    """Return a health verdict + refrigerant metrics for an outdoor unit."""
    status = STATUS_OK
    issues: list[str] = []
    metrics: dict[str, float] = {}

    if unit.get("commError"):
        return OutdoorHealth(
            STATUS_ALERT, ("Communication error with the outdoor unit",), {}
        )

    cooling = str(unit.get("opMode", "cool")).lower() != "heat"
    running = str(unit.get("comp1", "false")).lower() == "true"
    # Steady state = compressor above the ramp/oil-return band. Only then are the
    # cycle-quality checks (approach, superheat) meaningful on a modulating VRF.
    frequency = _f(unit, "compCurrentFrequency1")
    steady = running and (frequency is None or frequency >= _MIN_STEADY_HZ)

    high = _f(unit, "highPressure")
    low = _f(unit, "lowPressure")
    ambient = _f(unit, "outsideTemp")
    discharge = _f(unit, "dischargeTemp1")
    ipm = _f(unit, "ipm1")
    suction = _f(unit, "suctionTemp")

    cond_temp = saturation_temp(high) if high is not None else None
    evap_temp = saturation_temp(low) if low is not None else None
    if cond_temp is not None:
        metrics["condensing_temperature"] = cond_temp
    if evap_temp is not None:
        metrics["evaporating_temperature"] = evap_temp

    # Compressor thermal limits apply whenever it is running.
    if running and discharge is not None:
        metrics["discharge_temperature"] = discharge
        if discharge >= _DISCHARGE_ALERT:
            issues.append(
                f"Very high discharge temperature ({discharge:.0f}°C) — "
                "check refrigerant charge / restriction"
            )
            status = _escalate(status, STATUS_ALERT)
        elif discharge >= _DISCHARGE_WARN:
            issues.append(f"Elevated discharge temperature ({discharge:.0f}°C)")
            status = _escalate(status, STATUS_WARNING)

    if ipm is not None:
        metrics["ipm_temperature"] = ipm
        if ipm >= _IPM_ALERT:
            issues.append(f"Inverter module overheating ({ipm:.0f}°C)")
            status = _escalate(status, STATUS_ALERT)
        elif ipm >= _IPM_WARN:
            issues.append(f"Inverter module running hot ({ipm:.0f}°C)")
            status = _escalate(status, STATUS_WARNING)

    # Cooling-only cycle checks (roles swap in heating; skip to avoid false
    # positives on a reversed circuit).
    # Metrics are computed whenever the compressor runs (for display); they only
    # ESCALATE the verdict at steady state, so ramp/oil-return transients on a
    # modulating VRF unit don't raise spurious maintenance flags.
    if cooling and running and cond_temp is not None and ambient is not None:
        approach = round(cond_temp - ambient, 1)
        metrics["condenser_approach"] = approach
        if steady and approach >= _APPROACH_ALERT:
            issues.append(
                f"Condenser approach {approach:.0f} K — coil likely dirty or "
                "airflow blocked; cleaning recommended"
            )
            status = _escalate(status, STATUS_ALERT)
        elif steady and approach >= _APPROACH_WARN:
            issues.append(
                f"Condenser approach {approach:.0f} K — check/clean the "
                "outdoor coil"
            )
            status = _escalate(status, STATUS_WARNING)

    if cooling and running and evap_temp is not None and suction is not None:
        superheat = round(suction - evap_temp, 1)
        metrics["suction_superheat"] = superheat
        if steady and superheat < _SUPERHEAT_LOW:
            issues.append(
                f"Low suction superheat ({superheat:.0f} K) — liquid floodback risk"
            )
            status = _escalate(status, STATUS_WARNING)
        elif steady and superheat > _SUPERHEAT_HIGH:
            issues.append(
                f"Very high suction superheat ({superheat:.0f} K) — verify charge "
                "/ EEV operation"
            )
            status = _escalate(status, STATUS_WARNING)

    return OutdoorHealth(status, tuple(issues), metrics)
