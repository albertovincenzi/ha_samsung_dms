"""Climate platform for Samsung DMS indoor units."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEVICE_TYPE_INDOOR,
    DOMAIN,
    FAN_SPEED_TO_HA,
    HA_TO_FAN_SPEED,
)
from .coordinator import SamsungDMSCoordinator

# Samsung operationMode <-> HA HVACMode (used only while the unit is powered on).
DMS_TO_HVAC = {
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "dry": HVACMode.DRY,
    "fan": HVACMode.FAN_ONLY,
    "auto": HVACMode.AUTO,
}
HVAC_TO_DMS = {v: k for k, v in DMS_TO_HVAC.items()}

# Per-mode temperature-limit field names reported in the monitoring payload.
_MIN_FIELD = {
    HVACMode.COOL: "minTempCool",
    HVACMode.HEAT: "minTempHeat",
    HVACMode.DRY: "minTempDry",
    HVACMode.AUTO: "minTempAuto",
}
_MAX_FIELD = {
    HVACMode.COOL: "maxTempCool",
    HVACMode.HEAT: "maxTempHeat",
    HVACMode.DRY: "maxTempDry",
    HVACMode.AUTO: "maxTempAuto",
}

# Sentinel the DMS uses for "not applicable" temperatures.
_INVALID_TEMP = -1000.0

# Friendly model label from the DMS ``subIndoorType`` code.
_MODEL_LABELS = {
    "rac": "RAC indoor unit",
    "duct": "Duct indoor unit",
    "ehs": "EHS / hydro unit",
    "": "DVM indoor unit",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities from a config entry."""
    coordinator: SamsungDMSCoordinator = entry.runtime_data
    async_add_entities(
        SamsungDMSClimate(coordinator, addr)
        for addr in coordinator.data
        if coordinator.device_type(addr) == DEVICE_TYPE_INDOOR
    )


class SamsungDMSClimate(CoordinatorEntity[SamsungDMSCoordinator], ClimateEntity):
    """A single Samsung indoor AC unit."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: SamsungDMSCoordinator, addr: str) -> None:
        """Initialise the entity for a given unit address."""
        super().__init__(coordinator)
        self._addr = addr
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{addr}"

        meta = coordinator.metadata.get(addr, {})
        # unique_id stays address-based so renaming a unit on the DMS never
        # orphans the entity; only the display name follows the label.
        name = meta.get("name") or f"Samsung AC {addr}"
        model = _MODEL_LABELS.get(meta.get("sub_type"), meta.get("sub_type") or "DVM indoor unit")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=name,
            manufacturer="Samsung",
            model=model,
            sw_version=meta.get("version") or None,
        )

    # -- helpers -------------------------------------------------------------

    @property
    def _unit(self) -> dict[str, Any]:
        """Return this unit's latest monitoring dict (empty if gone)."""
        return self.coordinator.data.get(self._addr, {})

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return None if result <= _INVALID_TEMP else result

    def _supported_hvac_modes(self) -> list[HVACMode]:
        unit = self._unit
        modes: list[HVACMode] = [HVACMode.OFF]
        if unit.get("useCoolMode") == "true":
            modes.append(HVACMode.COOL)
        if unit.get("useHeatMode") == "true":
            modes.append(HVACMode.HEAT)
        # Dry/fan/auto are broadly available; include when the unit advertises
        # a matching min-temp field or is already using the mode.
        for mode in (HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.AUTO):
            modes.append(mode)
        return modes

    # -- entity availability -------------------------------------------------

    @property
    def available(self) -> bool:
        """Return True when the coordinator still reports this unit."""
        return super().available and self._addr in self.coordinator.data

    # -- state ---------------------------------------------------------------

    @property
    def current_temperature(self) -> float | None:
        """Return the room temperature."""
        return self._to_float(self._unit.get("roomTemp"))

    @property
    def target_temperature(self) -> float | None:
        """Return the setpoint."""
        return self._to_float(self._unit.get("setTemp"))

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the active HVAC mode (OFF when powered down)."""
        unit = self._unit
        if unit.get("power") != "on":
            return HVACMode.OFF
        return DMS_TO_HVAC.get(unit.get("opMode"), HVACMode.AUTO)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of supported HVAC modes."""
        return self._supported_hvac_modes()

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode label."""
        return FAN_SPEED_TO_HA.get(self._unit.get("fanSpeed"))

    @property
    def fan_modes(self) -> list[str]:
        """Return the supported fan mode labels."""
        return ["auto", "low", "medium", "high"]

    @property
    def min_temp(self) -> float:
        """Return the minimum settable temperature for the active mode."""
        field = _MIN_FIELD.get(self.hvac_mode)
        value = self._to_float(self._unit.get(field)) if field else None
        return value if value is not None else DEFAULT_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the maximum settable temperature for the active mode."""
        field = _MAX_FIELD.get(self.hvac_mode)
        value = self._to_float(self._unit.get(field)) if field else None
        return value if value is not None else DEFAULT_MAX_TEMP

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose useful raw fields for diagnostics/automations."""
        unit = self._unit
        return {
            "address": self._addr,
            "error": unit.get("error"),
            "filter_warning": unit.get("filterWarning"),
            "remote_control_enabled": unit.get("remoconEnable"),
            "scheduled": unit.get("isScheduled"),
        }

    # -- commands ------------------------------------------------------------

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        await self.coordinator.async_send_control(
            self._addr, {"setTemp": f"{float(temp):.1f}"}
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set a new fan mode."""
        speed = HA_TO_FAN_SPEED.get(fan_mode)
        if speed is None:
            return
        await self.coordinator.async_send_control(self._addr, {"fanSpeed": speed})

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new HVAC mode (handles power on/off)."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_send_control(self._addr, {"power": "off"})
            return

        dms_mode = HVAC_TO_DMS.get(hvac_mode)
        control: dict[str, str] = {"power": "on"}
        if dms_mode is not None:
            control["operationMode"] = dms_mode
        await self.coordinator.async_send_control(self._addr, control)

    async def async_turn_on(self) -> None:
        """Turn the unit on."""
        await self.coordinator.async_send_control(self._addr, {"power": "on"})

    async def async_turn_off(self) -> None:
        """Turn the unit off."""
        await self.coordinator.async_send_control(self._addr, {"power": "off"})

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
