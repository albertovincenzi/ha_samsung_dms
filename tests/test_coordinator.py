"""Tests for the coordinator's optimistic overlay and device grouping."""

from __future__ import annotations

from time import monotonic
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samsung_dms.const import DOMAIN
from custom_components.samsung_dms.coordinator import SamsungDMSCoordinator


@pytest.fixture
def coordinator(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> SamsungDMSCoordinator:
    """Return a coordinator wired to a dummy client (no polling started)."""
    mock_config_entry.add_to_hass(hass)
    return SamsungDMSCoordinator(hass, mock_config_entry, MagicMock())


def test_optimistic_overlay_holds_until_confirmed(
    coordinator: SamsungDMSCoordinator,
) -> None:
    """A commanded value is overlaid on stale polls, then cleared on confirm."""
    coordinator._optimistic = {"a": {"power": "on"}}
    coordinator._optimistic_until = {"a": monotonic() + 60}

    # DMS still reports the old value -> optimistic value wins.
    stale = coordinator._apply_optimistic("a", {"addr": "a", "power": "off"})
    assert stale["power"] == "on"
    assert "a" in coordinator._optimistic

    # DMS now agrees -> the override is dropped.
    fresh = coordinator._apply_optimistic("a", {"addr": "a", "power": "on"})
    assert fresh["power"] == "on"
    assert "a" not in coordinator._optimistic


def test_optimistic_overlay_expires_after_ttl(
    coordinator: SamsungDMSCoordinator,
) -> None:
    """Once the TTL passes we trust the DMS even if it disagrees."""
    coordinator._optimistic = {"a": {"power": "on"}}
    coordinator._optimistic_until = {"a": monotonic() - 1}  # already expired

    result = coordinator._apply_optimistic("a", {"addr": "a", "power": "off"})
    assert result["power"] == "off"
    assert "a" not in coordinator._optimistic


def test_apply_optimistic_no_overrides_is_passthrough(
    coordinator: SamsungDMSCoordinator,
) -> None:
    """Units without a pending override are returned unchanged."""
    unit = {"addr": "b", "power": "off"}
    assert coordinator._apply_optimistic("b", unit) is unit


@pytest.mark.parametrize(
    ("addr", "expected"),
    [
        ("12.01.09", "12.01.00"),  # child of a known outdoor unit
        ("12.01.00", None),        # the outdoor unit itself -> no self-link
        ("99.99.09", None),        # parent not among known outdoor units
        ("not-an-addr", None),     # malformed address
    ],
)
def test_outdoor_parent(
    coordinator: SamsungDMSCoordinator, addr: str, expected: str | None
) -> None:
    """The parent outdoor unit is derived from the address prefix."""
    coordinator.outdoor_addrs = ["12.01.00"]
    assert coordinator.outdoor_parent(addr) == expected


def test_with_via_device_links_to_parent(
    coordinator: SamsungDMSCoordinator,
) -> None:
    """A child unit gets a via_device pointing at its outdoor unit."""
    coordinator.outdoor_addrs = ["12.01.00"]
    info = DeviceInfo(identifiers={(DOMAIN, "child")})
    coordinator.with_via_device(info, "12.01.09")

    entry_id = coordinator.entry.entry_id
    assert info["via_device"] == (DOMAIN, f"{entry_id}_outdoor_12.01.00")


def test_with_via_device_noop_without_parent(
    coordinator: SamsungDMSCoordinator,
) -> None:
    """No via_device key is added when there is no distinct parent."""
    coordinator.outdoor_addrs = ["12.01.00"]
    info = DeviceInfo(identifiers={(DOMAIN, "outdoor")})
    coordinator.with_via_device(info, "12.01.00")
    assert "via_device" not in info
