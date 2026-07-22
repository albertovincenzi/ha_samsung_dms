"""Fan platform for Samsung energy-recovery ventilators (pluserv units)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import (
    DEVICE_TYPE_PLUSERV,
    DOMAIN,
    VENT_MODES,
    VENT_SPEEDS,
)
from .coordinator import SamsungDMSCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up fan entities for energy-recovery ventilators."""
    coordinator: SamsungDMSCoordinator = entry.runtime_data
    async_add_entities(
        SamsungDMSVentilator(coordinator, addr)
        for addr in coordinator.data
        if coordinator.device_type(addr) == DEVICE_TYPE_PLUSERV
    )


class SamsungDMSVentilator(CoordinatorEntity[SamsungDMSCoordinator], FanEntity):
    """A Samsung energy-recovery ventilator (ERV / pluserv)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_preset_modes = VENT_MODES
    _attr_speed_count = len(VENT_SPEEDS)
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: SamsungDMSCoordinator, addr: str) -> None:
        """Initialise the entity for a given pluserv address."""
        super().__init__(coordinator)
        self._addr = addr
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{addr}_erv"

        meta = coordinator.metadata.get(addr, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{addr}")},
            name=meta.get("name") or f"Samsung ERV {addr}",
            manufacturer="Samsung",
            model="Energy recovery ventilator",
            sw_version=meta.get("version") or None,
        )

    @property
    def _unit(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._addr, {})

    @property
    def available(self) -> bool:
        """Return True when the coordinator still reports this unit."""
        return super().available and self._addr in self.coordinator.data

    @property
    def is_on(self) -> bool | None:
        """Return whether the ventilator is running."""
        return self._unit.get("power") == "on"

    @property
    def percentage(self) -> int | None:
        """Return the current speed as a percentage."""
        if self._unit.get("power") != "on":
            return 0
        speed = self._unit.get("ventilationFanSpeed")
        if speed not in VENT_SPEEDS:
            return None
        return ordered_list_item_to_percentage(VENT_SPEEDS, speed)

    @property
    def preset_mode(self) -> str | None:
        """Return the current ventilation mode."""
        mode = self._unit.get("ventilationMode")
        return mode if mode in VENT_MODES else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose ERV diagnostics for dashboards and automations.

        Only fields the unit actually reports are included, so a model that
        omits e.g. a filter indicator simply won't surface that attribute.
        """
        unit = self._unit
        raw = {
            "address": self._addr,
            "error": unit.get("error"),
            "filter_warning": unit.get("filterWarning"),
            "remote_control_enabled": unit.get("remoconEnable"),
            "scheduled": unit.get("isScheduled"),
            "ventilation_mode": unit.get("ventilationMode"),
            "fan_speed": unit.get("ventilationFanSpeed"),
        }
        return {key: value for key, value in raw.items() if value is not None}

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the ventilation fan speed."""
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = percentage_to_ordered_list_item(VENT_SPEEDS, percentage)
        control = {"power": "on", "ventilationFanSpeed": speed}
        await self.coordinator.async_send_control(
            self._addr, control, optimistic=control
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the ventilation mode."""
        if preset_mode not in VENT_MODES:
            return
        control = {"power": "on", "ventilationMode": preset_mode}
        await self.coordinator.async_send_control(
            self._addr, control, optimistic=control
        )

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the ventilator on, optionally with a speed or mode."""
        control: dict[str, str] = {"power": "on"}
        if preset_mode in VENT_MODES:
            control["ventilationMode"] = preset_mode
        if percentage:
            control["ventilationFanSpeed"] = percentage_to_ordered_list_item(
                VENT_SPEEDS, percentage
            )
        await self.coordinator.async_send_control(
            self._addr, control, optimistic=control
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the ventilator off."""
        await self.coordinator.async_send_control(
            self._addr, {"power": "off"}, optimistic={"power": "off"}
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
