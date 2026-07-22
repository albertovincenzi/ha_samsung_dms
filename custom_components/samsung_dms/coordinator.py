"""DataUpdateCoordinator for the Samsung DMS integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SamsungDMSAuthError, SamsungDMSClient, SamsungDMSError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

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
