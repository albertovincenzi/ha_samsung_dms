"""Switch platform: per-unit remote-controller lock."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
    """Set up a remote-lock switch for every unit."""
    coordinator: SamsungDMSCoordinator = entry.runtime_data
    async_add_entities(
        SamsungDMSRemoteLock(coordinator, addr) for addr in coordinator.data
    )


class SamsungDMSRemoteLock(CoordinatorEntity[SamsungDMSCoordinator], SwitchEntity):
    """Locks/unlocks a unit's wall remote controller.

    On = locked (the physical remote is disabled). The DMS also has a
    conditional ``level1`` state; it is reported (not locked) and surfaced in
    the ``remocon_state`` attribute.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "remote_lock"
    _attr_icon = "mdi:remote"

    def __init__(self, coordinator: SamsungDMSCoordinator, addr: str) -> None:
        """Initialise the switch for a given address."""
        super().__init__(coordinator)
        self._addr = addr
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{addr}_remote_lock"

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
        """Return True when the remote is locked (disabled)."""
        return self._unit.get("remoconEnable") == "false"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw remote-control state (true/false/level1)."""
        return {"remocon_state": self._unit.get("remoconEnable")}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Lock the remote (disable it)."""
        await self.coordinator.async_send_control(self._addr, {"remocon": "false"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unlock the remote (enable it)."""
        await self.coordinator.async_send_control(self._addr, {"remocon": "true"})

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
