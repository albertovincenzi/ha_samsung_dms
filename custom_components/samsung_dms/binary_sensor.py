"""Binary sensor platform: per-unit schedule-active indicator."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SamsungDMSCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a schedule-active binary sensor for every unit."""
    coordinator: SamsungDMSCoordinator = entry.runtime_data
    async_add_entities(
        SamsungDMSScheduleSensor(coordinator, addr) for addr in coordinator.data
    )


class SamsungDMSScheduleSensor(
    CoordinatorEntity[SamsungDMSCoordinator], BinarySensorEntity
):
    """Indicates whether a DMS schedule is currently active for the unit."""

    _attr_has_entity_name = True
    _attr_translation_key = "scheduled"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: SamsungDMSCoordinator, addr: str) -> None:
        """Initialise the sensor for a given address."""
        super().__init__(coordinator)
        self._addr = addr
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{addr}_scheduled"

        meta = coordinator.metadata.get(addr, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{addr}")},
            name=meta.get("name") or f"Samsung {addr}",
            manufacturer="Samsung",
        )

    @property
    def _unit(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._addr, {})

    @property
    def available(self) -> bool:
        """Return True when the coordinator still reports this unit."""
        return super().available and self._addr in self.coordinator.data

    @property
    def is_on(self) -> bool:
        """Return True when a schedule is active for this unit."""
        return self._unit.get("isScheduled") == "true"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
