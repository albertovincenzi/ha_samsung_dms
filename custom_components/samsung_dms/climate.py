"""Climate platform for Samsung DMS indoor units."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_VERTICAL,
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
    DEVICE_TYPE_EHS,
    DEVICE_TYPE_INDOOR,
    DOMAIN,
    FAN_SPEED_TO_HA,
    HA_TO_FAN_SPEED,
)
from .coordinator import SamsungDMSCoordinator

# Water-out (EHS space heating) target/limit fields, keyed by mode.
_WATEROUT_SET_FIELD = "waterOutSetTemp"
_WATEROUT_MIN_FIELD = {
    HVACMode.HEAT: "waterOutHeatLowerBound",
    HVACMode.COOL: "waterOutCoolLowerBound",
}
_WATEROUT_MAX_FIELD = {
    HVACMode.HEAT: "waterOutHeatUpperBound",
    HVACMode.COOL: "waterOutCoolUpperBound",
}
_DEFAULT_WATEROUT_MIN = 15.0
_DEFAULT_WATEROUT_MAX = 65.0

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
    entities: list[ClimateEntity] = []
    for addr in coordinator.data:
        device_type = coordinator.device_type(addr)
        if device_type == DEVICE_TYPE_INDOOR:
            entities.append(SamsungDMSClimate(coordinator, addr))
        elif device_type == DEVICE_TYPE_EHS:
            # The EHS also exposes a domestic-hot-water side via water_heater.
            entities.append(SamsungDMSWaterOutClimate(coordinator, addr))
    async_add_entities(entities)


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

        # Swing capability is static per unit: a vertical vane exists when the
        # DMS reports an actual airSwing_UD value ("null" means no vane); the
        # left/right vane is advertised via useLRSwing.
        unit = coordinator.data.get(addr, {})
        self._ud_capable = unit.get("airSwing_UD") not in (None, "null")
        self._lr_capable = unit.get("useLRSwing") == "true"
        self._swing_supported = self._ud_capable or self._lr_capable

        swing_modes = [SWING_OFF]
        if self._ud_capable:
            swing_modes.append(SWING_VERTICAL)
        if self._lr_capable:
            swing_modes.append(SWING_HORIZONTAL)
        if self._ud_capable and self._lr_capable:
            swing_modes.append(SWING_BOTH)
        self._attr_swing_modes = swing_modes

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
    def swing_mode(self) -> str | None:
        """Return the current swing mode from the UD/LR vane flags."""
        if not self._swing_supported:
            return None
        unit = self._unit
        ud = unit.get("airSwing_UD") == "true"
        lr = unit.get("airSwing_LR") == "true"
        if ud and lr:
            return SWING_BOTH
        if ud:
            return SWING_VERTICAL
        if lr:
            return SWING_HORIZONTAL
        return SWING_OFF

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported features."""
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self._swing_supported:
            features |= ClimateEntityFeature.SWING_MODE
        return features

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
        value = f"{float(temp):.1f}"
        await self.coordinator.async_send_control(
            self._addr, {"setTemp": value}, optimistic={"setTemp": value}
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set a new fan mode."""
        speed = HA_TO_FAN_SPEED.get(fan_mode)
        if speed is None:
            return
        await self.coordinator.async_send_control(
            self._addr, {"fanSpeed": speed}, optimistic={"fanSpeed": speed}
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new HVAC mode (handles power on/off)."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_send_control(
                self._addr, {"power": "off"}, optimistic={"power": "off"}
            )
            return

        dms_mode = HVAC_TO_DMS.get(hvac_mode)
        control: dict[str, str] = {"power": "on"}
        # Monitoring reports the mode as ``opMode``; the control tag is
        # ``operationMode``.
        optimistic: dict[str, str] = {"power": "on"}
        if dms_mode is not None:
            control["operationMode"] = dms_mode
            optimistic["opMode"] = dms_mode
        await self.coordinator.async_send_control(
            self._addr, control, optimistic=optimistic
        )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set the vane swing (mirrors the DMS UD/LR command)."""
        if not self._swing_supported:
            return
        ud = "true" if swing_mode in (SWING_VERTICAL, SWING_BOTH) else "false"
        lr = "true" if swing_mode in (SWING_HORIZONTAL, SWING_BOTH) else "false"
        # The DMS wind-direction command always carries both vane flags.
        vanes = {"airSwing_UD": ud, "airSwing_LR": lr}
        await self.coordinator.async_send_control(
            self._addr, vanes, optimistic=vanes
        )

    async def async_turn_on(self) -> None:
        """Turn the unit on."""
        await self.coordinator.async_send_control(
            self._addr, {"power": "on"}, optimistic={"power": "on"}
        )

    async def async_turn_off(self) -> None:
        """Turn the unit off."""
        await self.coordinator.async_send_control(
            self._addr, {"power": "off"}, optimistic={"power": "off"}
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class SamsungDMSWaterOutClimate(
    CoordinatorEntity[SamsungDMSCoordinator], ClimateEntity
):
    """The space-heating (water-out) side of a Samsung EHS/hydro unit.

    Shares the EHS device with the domestic-hot-water ``water_heater`` entity;
    it controls the leaving-water setpoint used for underfloor / radiator loops.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "space_heating"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: SamsungDMSCoordinator, addr: str) -> None:
        """Initialise the water-out climate entity for an EHS address."""
        super().__init__(coordinator)
        self._addr = addr
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{addr}_waterout"

        meta = coordinator.metadata.get(addr, {})
        # Same identifiers as the water_heater entity -> one grouped device.
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
    def hvac_modes(self) -> list[HVACMode]:
        """Return supported modes (off + whichever of heat/cool are enabled)."""
        unit = self._unit
        modes: list[HVACMode] = [HVACMode.OFF]
        if unit.get("useHeatMode") == "true":
            modes.append(HVACMode.HEAT)
        if unit.get("useCoolMode") == "true":
            modes.append(HVACMode.COOL)
        return modes

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the active mode (OFF when the space-heating side is off)."""
        unit = self._unit
        if unit.get("power") != "on":
            return HVACMode.OFF
        return HVACMode.COOL if unit.get("opMode") == "cool" else HVACMode.HEAT

    @property
    def current_temperature(self) -> float | None:
        """Return the current leaving-water temperature."""
        return self._to_float(self._unit.get("waterOutCurrentTemp"))

    @property
    def target_temperature(self) -> float | None:
        """Return the leaving-water setpoint."""
        return self._to_float(self._unit.get(_WATEROUT_SET_FIELD))

    def _active_mode(self) -> HVACMode:
        mode = self.hvac_mode
        return HVACMode.COOL if mode == HVACMode.COOL else HVACMode.HEAT

    @property
    def min_temp(self) -> float:
        """Return the minimum leaving-water setpoint for the active mode."""
        field = _WATEROUT_MIN_FIELD.get(self._active_mode())
        value = self._to_float(self._unit.get(field)) if field else None
        return value if value is not None else _DEFAULT_WATEROUT_MIN

    @property
    def max_temp(self) -> float:
        """Return the maximum leaving-water setpoint for the active mode."""
        field = _WATEROUT_MAX_FIELD.get(self._active_mode())
        value = self._to_float(self._unit.get(field)) if field else None
        return value if value is not None else _DEFAULT_WATEROUT_MAX

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new leaving-water setpoint."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        # Control tag is ``setWaterOutTemp``; monitoring reports the setpoint
        # under ``waterOutSetTemp``.
        value = f"{float(temp):.1f}"
        await self.coordinator.async_send_control(
            self._addr,
            {"setWaterOutTemp": value},
            optimistic={_WATEROUT_SET_FIELD: value},
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new mode (handles power on/off)."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_send_control(
                self._addr, {"power": "off"}, optimistic={"power": "off"}
            )
            return
        dms_mode = "cool" if hvac_mode == HVACMode.COOL else "heat"
        await self.coordinator.async_send_control(
            self._addr,
            {"power": "on", "operationMode": dms_mode},
            optimistic={"power": "on", "opMode": dms_mode},
        )

    async def async_turn_on(self) -> None:
        """Turn the space-heating side on."""
        await self.coordinator.async_send_control(
            self._addr, {"power": "on"}, optimistic={"power": "on"}
        )

    async def async_turn_off(self) -> None:
        """Turn the space-heating side off."""
        await self.coordinator.async_send_control(
            self._addr, {"power": "off"}, optimistic={"power": "off"}
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
