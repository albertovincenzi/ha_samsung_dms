"""Binary sensor platform for Samsung DMS.

Per indoor/EHS/ERV unit: schedule-active, fault, and filter-cleaning
indicators. Plus the outdoor-unit running / comm-error / maintenance sensors.
The fault and filter sensors use the ``problem`` device class so they can drive
Home Assistant warnings directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SamsungDMSCoordinator
from .outdoor import build_outdoor_binary_sensors


@dataclass(frozen=True, kw_only=True)
class DMSBinaryDescription(BinarySensorEntityDescription):
    """Describes a per-unit binary sensor."""

    is_on_fn: Callable[[dict[str, Any]], bool]


UNIT_BINARY_SENSORS: tuple[DMSBinaryDescription, ...] = (
    DMSBinaryDescription(
        key="scheduled",
        translation_key="scheduled",
        icon="mdi:calendar-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda u: u.get("isScheduled") == "true",
    ),
    DMSBinaryDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda u: u.get("error") == "true",
    ),
    DMSBinaryDescription(
        key="filter",
        translation_key="filter",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:air-filter",
        is_on_fn=lambda u: u.get("filterWarning") == "true",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up per-unit and outdoor binary sensors."""
    coordinator: SamsungDMSCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        SamsungDMSUnitBinary(coordinator, addr, description)
        for addr in coordinator.data
        for description in UNIT_BINARY_SENSORS
    ]
    entities.extend(build_outdoor_binary_sensors(coordinator))
    async_add_entities(entities)


class SamsungDMSUnitBinary(
    CoordinatorEntity[SamsungDMSCoordinator], BinarySensorEntity
):
    """A per-unit boolean indicator (schedule / fault / filter)."""

    _attr_has_entity_name = True
    entity_description: DMSBinaryDescription

    def __init__(
        self,
        coordinator: SamsungDMSCoordinator,
        addr: str,
        description: DMSBinaryDescription,
    ) -> None:
        """Initialise the sensor for a given address and metric."""
        super().__init__(coordinator)
        self._addr = addr
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{addr}_{description.key}"

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
        """Return the indicator state."""
        return self.entity_description.is_on_fn(self._unit)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
