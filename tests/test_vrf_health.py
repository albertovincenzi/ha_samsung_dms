"""Unit tests for the pure VRF-health computations.

These are deliberately dependency-free: ``vrf_health`` is a self-contained
refrigerant-side calculator, so the tests document the thresholds precisely.
"""

from __future__ import annotations

import pytest

from custom_components.samsung_dms.vrf_health import (
    STATUS_ALERT,
    STATUS_OK,
    STATUS_WARNING,
    assess_outdoor,
    saturation_temp,
)


def test_saturation_temp_is_monotonic() -> None:
    """Higher pressure must map to a higher saturation temperature."""
    temps = [saturation_temp(p) for p in (5.0, 15.0, 25.0, 35.0)]
    assert temps == sorted(temps)


def test_saturation_temp_clamps_out_of_range() -> None:
    """Pressures beyond the P-T table clamp to the table's endpoints."""
    assert saturation_temp(-5.0) == pytest.approx(-20.0)
    assert saturation_temp(999.0) == pytest.approx(65.0)


def test_healthy_unit_reports_ok() -> None:
    """A running unit within all limits is OK with no issues."""
    health = assess_outdoor(
        {
            "opMode": "cool",
            "comp1": "true",
            "highPressure": 30.0,   # ~condensing 48 C
            "lowPressure": 9.0,
            "outsideTemp": 38.0,    # approach ~10 K -> within limits
            "dischargeTemp1": 70.0,
            "ipm1": 55.0,
            "suctionTemp": 12.0,
        }
    )
    assert health.status == STATUS_OK
    assert health.issues == ()
    assert "condensing_temperature" in health.metrics


def test_comm_error_short_circuits_to_alert() -> None:
    """A communication error is an immediate alert, no metrics computed."""
    health = assess_outdoor({"commError": True, "highPressure": 30.0})
    assert health.status == STATUS_ALERT
    assert health.metrics == {}
    assert any("ommunication" in issue for issue in health.issues)


def test_high_discharge_temperature_alerts() -> None:
    """Discharge temperature over the alert threshold escalates to alert."""
    health = assess_outdoor(
        {"comp1": "true", "dischargeTemp1": 115.0}
    )
    assert health.status == STATUS_ALERT
    assert any("discharge" in issue.lower() for issue in health.issues)


def test_discharge_ignored_when_compressor_off() -> None:
    """Thermal limits only apply while the compressor runs."""
    health = assess_outdoor({"comp1": "false", "dischargeTemp1": 115.0})
    assert "discharge_temperature" not in health.metrics
    assert health.status == STATUS_OK


def test_dirty_condenser_warns_via_approach() -> None:
    """A large condenser approach flags a fouled coil."""
    health = assess_outdoor(
        {
            "opMode": "cool",
            "comp1": "true",
            "highPressure": 29.5,  # ~condensing 47 C
            "outsideTemp": 30.0,   # approach ~17 K -> warning band
        }
    )
    assert health.status == STATUS_WARNING
    assert "condenser_approach" in health.metrics
    assert any("approach" in issue.lower() for issue in health.issues)


def test_invalid_sentinels_are_skipped() -> None:
    """DMS -1000 sentinels must not be treated as real readings."""
    health = assess_outdoor(
        {"comp1": "true", "dischargeTemp1": -1000.0, "ipm1": -1000.0}
    )
    assert health.metrics == {} or "discharge_temperature" not in health.metrics
    assert health.status == STATUS_OK
