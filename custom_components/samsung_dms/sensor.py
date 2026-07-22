"""Sensor platform for Samsung energy-recovery ventilators (pluserv units).

An ERV reports richer telemetry than the fan entity can express — CO2 and a
handful of air temperatures. Each sensor is created only when its source field
is actually present and valid on the unit, so a model that omits a probe simply
won't get that sensor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_TYPE_PLUSERV, DOMAIN
from .coordinator import SamsungDMSCoordinator
from .outdoor import build_outdoor_sensors

_INVALID_TEMP = -1000.0


@dataclass(frozen=True, kw_only=True)
class DMSSensorDescription(SensorEntityDescription):
    """Describes a DMS sensor and how to read its value."""

    source: str  # monitoring field name
    text: bool = False  # True for string readings (e.g. operating mode)
    value_fn: Callable[[float], float | int] = lambda v: round(v, 1)


# Values the DMS uses to mean "no reading" for string fields.
_TEXT_ABSENT = (None, "", "null", "none", "false")


def _present(value: Any, *, text: bool) -> bool:
    """Return True when a field carries a usable reading."""
    if text:
        return value not in _TEXT_ABSENT
    return _to_float(value) is not None


SENSOR_TYPES: tuple[DMSSensorDescription, ...] = (
    DMSSensorDescription(
        key="co2",
        source="co2Sensor",
        translation_key="co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: round(v),
    ),
    DMSSensorDescription(
        key="outdoor_temperature",
        source="ervPlusOutdoorTemp",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DMSSensorDescription(
        key="air_temperature",
        source="roomTemp",
        translation_key="air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DMSSensorDescription(
        key="intake_temperature",
        source="evaInhaleTemp",
        translation_key="intake_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # The ERV Plus tempers incoming air but its mode/setpoint are driven by the
    # connected system and are NOT controllable via the DMS — exposed read-only.
    DMSSensorDescription(
        key="setpoint",
        source="setTemp",
        translation_key="setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DMSSensorDescription(
        key="operating_mode",
        source="opMode",
        translation_key="operating_mode",
        text=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result <= _INVALID_TEMP else result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ERV sensors for pluserv units that report the source field."""
    coordinator: SamsungDMSCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for addr, unit in coordinator.data.items():
        if coordinator.device_type(addr) != DEVICE_TYPE_PLUSERV:
            continue
        for description in SENSOR_TYPES:
            if _present(unit.get(description.source), text=description.text):
                entities.append(SamsungDMSSensor(coordinator, addr, description))
    entities.extend(build_outdoor_sensors(coordinator))
    async_add_entities(entities)


class SamsungDMSSensor(CoordinatorEntity[SamsungDMSCoordinator], SensorEntity):
    """A single telemetry reading from an ERV."""

    _attr_has_entity_name = True
    entity_description: DMSSensorDescription

    def __init__(
        self,
        coordinator: SamsungDMSCoordinator,
        addr: str,
        description: DMSSensorDescription,
    ) -> None:
        """Initialise the sensor for a given address and metric."""
        super().__init__(coordinator)
        self._addr = addr
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{addr}_{description.key}"

        meta = coordinator.metadata.get(addr, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{addr}")},
            name=meta.get("name") or f"Samsung ERV {addr}",
            manufacturer="Samsung",
            model="Energy recovery ventilator",
            sw_version=meta.get("version") or None,
        )

    @property
    def available(self) -> bool:
        """Return True when the unit and this metric are present."""
        if not (super().available and self._addr in self.coordinator.data):
            return False
        unit = self.coordinator.data[self._addr]
        return _present(
            unit.get(self.entity_description.source),
            text=self.entity_description.text,
        )

    @property
    def native_value(self) -> float | int | str | None:
        """Return the current reading."""
        raw = self.coordinator.data.get(self._addr, {}).get(
            self.entity_description.source
        )
        if self.entity_description.text:
            return raw if raw not in _TEXT_ABSENT else None
        value = _to_float(raw)
        if value is None:
            return None
        return self.entity_description.value_fn(value)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
