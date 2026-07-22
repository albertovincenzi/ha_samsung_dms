"""DataUpdateCoordinator for the Samsung DMS integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SamsungDMSAuthError, SamsungDMSClient, SamsungDMSError
from .const import DEFAULT_SCAN_INTERVAL, DEVICE_TYPE_INDOOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SamsungDMSCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Polls the DMS and exposes state keyed by indoor-unit address."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SamsungDMSClient,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.entry = entry
        # addr -> {name, sub_type, indoor_type, model_code, version}
        self.metadata: dict[str, dict[str, Any]] = {}

    def device_type(self, addr: str) -> str:
        """Return the device class for an address.

        One of ``indoor`` / ``ehs`` / ``pluserv``. Falls back to ``indoor``
        when metadata is unavailable, so units always get at least a climate
        entity.
        """
        return self.metadata.get(addr, {}).get("indoor_type", DEVICE_TYPE_INDOOR)

    async def async_load_metadata(self) -> None:
        """Load per-unit labels/models once at setup (best-effort)."""
        try:
            self.metadata = await self.client.async_get_indoor_metadata()
        except SamsungDMSError as err:
            _LOGGER.warning("Could not load Samsung DMS device names: %s", err)
            self.metadata = {}

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch the latest monitoring snapshot, keyed by address."""
        try:
            units = await self.client.async_get_monitoring()
        except SamsungDMSAuthError as err:
            # Surface as UpdateFailed; the client already retried a re-login.
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except SamsungDMSError as err:
            raise UpdateFailed(f"Error communicating with DMS: {err}") from err

        return {unit["addr"]: unit for unit in units if unit.get("addr")}

    async def async_send_control(
        self, addr: str, control_values: dict[str, str]
    ) -> None:
        """Send a control command and refresh state."""
        await self.client.async_control([addr], control_values)
        await self.async_request_refresh()
