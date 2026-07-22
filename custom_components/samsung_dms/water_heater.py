"""Water heater platform for Samsung EHS (domestic-hot-water) units."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    STATE_OFF,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEFAULT_TANK_MAX_TEMP,
    DEFAULT_TANK_MIN_TEMP,
    DEVICE_TYPE_EHS,
    DHW_MODES,
    DOMAIN,
)
from .coordinator import SamsungDMSCoordinator

_INVALID_TEMP = -1000.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up water-heater entities for EHS units."""
    coordinator: SamsungDMSCoordinator = entry.runtime_data
    async_add_entities(
        SamsungDMSWaterHeater(coordinator, addr)
        for addr in coordinator.data
        if coordinator.device_type(addr) == DEVICE_TYPE_EHS
    )


class SamsungDMSWaterHeater(
    CoordinatorEntity[SamsungDMSCoordinator], WaterHeaterEntity
):
    """The domestic-hot-water side of a Samsung EHS/hydro unit."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_operation_list = [STATE_OFF, *DHW_MODES]
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.AWAY_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(self, coordinator: SamsungDMSCoordinator, addr: str) -> None:
        """Initialise the entity for a given EHS address."""
        super().__init__(coordinator)
        self._addr = addr
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{addr}_dhw"

        meta = coordinator.metadata.get(addr, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{addr}")},
            name=meta.get("name") or f"Samsung EHS {addr}",
            manufacturer="Samsung",
            model="EHS / hydro unit",
            sw_version=meta.get("version") or None,
        )

    @property
    def _unit(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._addr, {})

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return None if result <= _INVALID_TEMP else result

    @property
    def available(self) -> bool:
        """Return True when the coordinator still reports this unit."""
        return super().available and self._addr in self.coordinator.data

    @property
    def current_temperature(self) -> float | None:
        """Return the current tank temperature."""
        return self._to_float(self._unit.get("currentHotWaterSupplyTemp"))

    @property
    def target_temperature(self) -> float | None:
        """Return the DHW setpoint."""
        return self._to_float(self._unit.get("setHotWaterSupplyTemp"))

    @property
    def min_temp(self) -> float:
        """Return the minimum tank temperature."""
        value = self._to_float(self._unit.get("minTempTank"))
        return value if value is not None else DEFAULT_TANK_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the maximum tank temperature."""
        value = self._to_float(self._unit.get("maxTempTank"))
        return value if value is not None else DEFAULT_TANK_MAX_TEMP

    @property
    def current_operation(self) -> str:
        """Return the active DHW operation mode (or off)."""
        unit = self._unit
        if unit.get("hotWaterSupplyPower") != "on":
            return STATE_OFF
        mode = unit.get("hotWaterSupplyMode")
        return mode if mode in DHW_MODES else STATE_OFF

    @property
    def is_away_mode_on(self) -> bool:
        """Return True when the unit's 'go out' (away) flag is set."""
        return self._unit.get("goOut") == "on"

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new tank setpoint."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        value = f"{float(temp):.1f}"
        await self.coordinator.async_send_control(
            self._addr,
            {"setHotWaterSupplyTemp": value},
            optimistic={"setHotWaterSupplyTemp": value},
        )

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set a new DHW operation mode (or turn off)."""
        if operation_mode == STATE_OFF:
            await self.coordinator.async_send_control(
                self._addr,
                {"hotWaterSupplyPower": "off"},
                optimistic={"hotWaterSupplyPower": "off"},
            )
            return
        if operation_mode not in DHW_MODES:
            return
        control = {"hotWaterSupplyPower": "on", "hotWaterSupplyMode": operation_mode}
        await self.coordinator.async_send_control(
            self._addr, control, optimistic=control
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn DHW on."""
        await self.coordinator.async_send_control(
            self._addr,
            {"hotWaterSupplyPower": "on"},
            optimistic={"hotWaterSupplyPower": "on"},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn DHW off."""
        await self.coordinator.async_send_control(
            self._addr,
            {"hotWaterSupplyPower": "off"},
            optimistic={"hotWaterSupplyPower": "off"},
        )

    async def async_turn_away_mode_on(self) -> None:
        """Enable away ('go out') mode."""
        await self.coordinator.async_send_control(
            self._addr, {"goOut": "on"}, optimistic={"goOut": "on"}
        )

    async def async_turn_away_mode_off(self) -> None:
        """Disable away ('go out') mode."""
        await self.coordinator.async_send_control(
            self._addr, {"goOut": "off"}, optimistic={"goOut": "off"}
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
