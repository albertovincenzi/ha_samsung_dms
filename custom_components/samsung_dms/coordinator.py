"""DataUpdateCoordinator for the Samsung DMS integration."""

from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SamsungDMSAuthError, SamsungDMSClient, SamsungDMSError
from .const import (
    CONFIRM_REFRESH_DELAYS,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_TYPE_INDOOR,
    DOMAIN,
    OPTIMISTIC_TTL_SECONDS,
)

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
        # Pending optimistic overrides (monitoring-key space) applied on top of
        # each poll until the DMS confirms them or they age out. Keyed by addr.
        self._optimistic: dict[str, dict[str, Any]] = {}
        self._optimistic_until: dict[str, float] = {}

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

        return {
            unit["addr"]: self._apply_optimistic(unit["addr"], unit)
            for unit in units
            if unit.get("addr")
        }

    def _apply_optimistic(
        self, addr: str, unit: dict[str, Any]
    ) -> dict[str, Any]:
        """Overlay pending optimistic values, expiring confirmed/stale ones.

        The DMS lags a few seconds behind a control command, so a poll fired
        right after a write reports the *old* state. We keep the commanded
        value on top of each poll until the DMS reports the same value (the
        command took effect) or the guard times out (accept the DMS's truth).
        """
        overrides = self._optimistic.get(addr)
        if not overrides:
            return unit
        pending = {k: v for k, v in overrides.items() if str(unit.get(k)) != str(v)}
        if not pending or monotonic() >= self._optimistic_until.get(addr, 0.0):
            # Fully confirmed, or we've waited long enough — trust the DMS.
            self._optimistic.pop(addr, None)
            self._optimistic_until.pop(addr, None)
            return unit
        self._optimistic[addr] = pending
        return {**unit, **pending}

    async def async_send_control(
        self,
        addr: str,
        control_values: dict[str, str],
        optimistic: dict[str, Any] | None = None,
    ) -> None:
        """Send a control command and refresh state.

        ``optimistic`` (monitoring-key space) is shown immediately and held
        across polls until the DMS confirms it, so the UI reflects the change
        without waiting for the device to catch up.
        """
        if optimistic and self.data and addr in self.data:
            self._optimistic[addr] = {**self._optimistic.get(addr, {}), **optimistic}
            self._optimistic_until[addr] = monotonic() + OPTIMISTIC_TTL_SECONDS
            patched = dict(self.data)
            patched[addr] = {**self.data[addr], **self._optimistic[addr]}
            self.async_set_updated_data(patched)

        await self.client.async_control([addr], control_values)
        await self.async_request_refresh()

        # The DMS reflects a command a few seconds after it is issued. Poll
        # again shortly after so the confirmed value replaces the optimistic
        # guess quickly (and a silently-rejected command surfaces sooner),
        # rather than waiting for the next 30s scan.
        for delay in CONFIRM_REFRESH_DELAYS:
            async_call_later(self.hass, delay, self._async_confirm_refresh)

    async def _async_confirm_refresh(self, _now: Any) -> None:
        """Trigger a post-command confirmation poll (debouncer-coalesced)."""
        await self.async_request_refresh()
