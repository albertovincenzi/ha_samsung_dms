"""Outdoor-unit (VRF condensing unit) entities and helpers.

Builds the "external machine" device: raw cycle telemetry sensors, engineer's
derived metrics (condensing/evaporating temperature, approach, superheat) and a
health-status verdict, plus running / comm-error / maintenance binary sensors.
Values come from the coordinator's ``outdoor`` snapshot.
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
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfFrequency,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SamsungDMSCoordinator
from .diagnostics import STATUS_OK

_INVALID = -999.0
_KGFCM2_TO_BAR = 0.980665
_DELTA_KELVIN = "K"


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result <= _INVALID else result


def outdoor_device_info(
    coordinator: SamsungDMSCoordinator, addr: str
) -> DeviceInfo:
    """Build the device entry for an outdoor unit."""
    unit = coordinator.outdoor.get(addr, {})
    model = unit.get("modelName") or "DVM outdoor unit"
    capacity = unit.get("outdoorCapacity")
    model_full = f"{model} {capacity}HP" if capacity else model
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_outdoor_{addr}")},
        name=f"Outdoor unit {addr}",
        manufacturer="Samsung",
        model=model_full,
    )


# --- sensor descriptions ----------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OutdoorSensorDescription(SensorEntityDescription):
    """An outdoor telemetry or derived-metric sensor."""

    source: str
    metric: bool = False  # read from health_metrics instead of a raw field
    value_fn: Callable[[float], float | int] = lambda v: round(v, 1)


OUTDOOR_SENSORS: tuple[OutdoorSensorDescription, ...] = (
    OutdoorSensorDescription(
        key="outside_temperature",
        source="outsideTemp",
        translation_key="outside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OutdoorSensorDescription(
        key="discharge_temperature",
        source="dischargeTemp1",
        translation_key="discharge_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    OutdoorSensorDescription(
        key="ipm_temperature",
        source="ipm1",
        translation_key="ipm_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    OutdoorSensorDescription(
        key="compressor_current",
        source="ct1",
        translation_key="compressor_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    OutdoorSensorDescription(
        key="compressor_frequency",
        source="compCurrentFrequency1",
        translation_key="compressor_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    OutdoorSensorDescription(
        key="high_pressure",
        source="highPressure",
        translation_key="high_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: round(v * _KGFCM2_TO_BAR, 2),
    ),
    OutdoorSensorDescription(
        key="low_pressure",
        source="lowPressure",
        translation_key="low_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: round(v * _KGFCM2_TO_BAR, 2),
    ),
    OutdoorSensorDescription(
        key="compressor_hours",
        source="accumComp1OnTime",
        translation_key="compressor_hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=round,
    ),
    # Engineer's derived metrics (from diagnostics.assess_outdoor).
    OutdoorSensorDescription(
        key="condensing_temperature",
        source="condensing_temperature",
        metric=True,
        translation_key="condensing_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    OutdoorSensorDescription(
        key="evaporating_temperature",
        source="evaporating_temperature",
        metric=True,
        translation_key="evaporating_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    OutdoorSensorDescription(
        key="condenser_approach",
        source="condenser_approach",
        metric=True,
        translation_key="condenser_approach",
        native_unit_of_measurement=_DELTA_KELVIN,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    OutdoorSensorDescription(
        key="suction_superheat",
        source="suction_superheat",
        metric=True,
        translation_key="suction_superheat",
        native_unit_of_measurement=_DELTA_KELVIN,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


# --- binary sensor descriptions ---------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OutdoorBinaryDescription(BinarySensorEntityDescription):
    """An outdoor boolean/state indicator."""

    is_on_fn: Callable[[dict[str, Any]], bool]


OUTDOOR_BINARY_SENSORS: tuple[OutdoorBinaryDescription, ...] = (
    OutdoorBinaryDescription(
        key="compressor",
        translation_key="compressor",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=lambda u: str(u.get("comp1", "")).lower() == "true",
    ),
    OutdoorBinaryDescription(
        key="communication_error",
        translation_key="communication_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda u: bool(u.get("commError")),
    ),
    OutdoorBinaryDescription(
        key="maintenance",
        translation_key="maintenance",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda u: u.get("health_status", STATUS_OK) != STATUS_OK,
    ),
)


# --- entities ---------------------------------------------------------------


class _OutdoorBase(CoordinatorEntity[SamsungDMSCoordinator]):
    """Shared plumbing for outdoor entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SamsungDMSCoordinator, addr: str) -> None:
        super().__init__(coordinator)
        self._addr = addr
        self._attr_device_info = outdoor_device_info(coordinator, addr)

    @property
    def _unit(self) -> dict[str, Any]:
        return self.coordinator.outdoor.get(self._addr, {})

    @property
    def available(self) -> bool:
        return super().available and self._addr in self.coordinator.outdoor

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class SamsungDMSOutdoorSensor(_OutdoorBase, SensorEntity):
    """A telemetry or derived-metric reading from an outdoor unit."""

    entity_description: OutdoorSensorDescription

    def __init__(
        self,
        coordinator: SamsungDMSCoordinator,
        addr: str,
        description: OutdoorSensorDescription,
    ) -> None:
        super().__init__(coordinator, addr)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_outdoor_{addr}_{description.key}"
        )

    def _raw(self) -> Any:
        desc = self.entity_description
        if desc.metric:
            return self._unit.get("health_metrics", {}).get(desc.source)
        return self._unit.get(desc.source)

    @property
    def native_value(self) -> float | int | None:
        value = _to_float(self._raw())
        if value is None:
            return None
        return self.entity_description.value_fn(value)


class SamsungDMSOutdoorHealth(_OutdoorBase, SensorEntity):
    """Overall health verdict for an outdoor unit (ok / warning / alert)."""

    _attr_translation_key = "health_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ok", "warning", "alert"]

    def __init__(self, coordinator: SamsungDMSCoordinator, addr: str) -> None:
        super().__init__(coordinator, addr)
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_outdoor_{addr}_health_status"
        )

    @property
    def native_value(self) -> str | None:
        return self._unit.get("health_status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        unit = self._unit
        attrs: dict[str, Any] = {"issues": unit.get("health_issues", [])}
        attrs.update(unit.get("health_metrics", {}))
        return attrs


class SamsungDMSOutdoorBinary(_OutdoorBase, BinarySensorEntity):
    """A boolean indicator for an outdoor unit."""

    entity_description: OutdoorBinaryDescription

    def __init__(
        self,
        coordinator: SamsungDMSCoordinator,
        addr: str,
        description: OutdoorBinaryDescription,
    ) -> None:
        super().__init__(coordinator, addr)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_outdoor_{addr}_{description.key}"
        )

    @property
    def is_on(self) -> bool:
        return self.entity_description.is_on_fn(self._unit)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "maintenance":
            return {"issues": self._unit.get("health_issues", [])}
        return None


def build_outdoor_sensors(
    coordinator: SamsungDMSCoordinator,
) -> list[SensorEntity]:
    """Create all outdoor sensor entities present in the current snapshot."""
    entities: list[SensorEntity] = []
    for addr, unit in coordinator.outdoor.items():
        metrics = unit.get("health_metrics", {})
        for desc in OUTDOOR_SENSORS:
            present = (
                desc.source in metrics
                if desc.metric
                else _to_float(unit.get(desc.source)) is not None
            )
            if present:
                entities.append(SamsungDMSOutdoorSensor(coordinator, addr, desc))
        if unit.get("health_status") is not None:
            entities.append(SamsungDMSOutdoorHealth(coordinator, addr))
    return entities


def build_outdoor_binary_sensors(
    coordinator: SamsungDMSCoordinator,
) -> list[BinarySensorEntity]:
    """Create all outdoor binary-sensor entities."""
    entities: list[BinarySensorEntity] = []
    for addr in coordinator.outdoor:
        for desc in OUTDOOR_BINARY_SENSORS:
            entities.append(SamsungDMSOutdoorBinary(coordinator, addr, desc))
    return entities
