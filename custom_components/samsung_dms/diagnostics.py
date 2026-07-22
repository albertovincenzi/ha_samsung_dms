"""Diagnostics support for the Samsung DMS integration.

Powers the "Download diagnostics" button on the config entry / device pages.
Credentials are redacted so the dump is safe to attach to a bug report.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, CONF_USERNAME
from .coordinator import SamsungDMSCoordinator

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SamsungDMSCoordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": dict(entry.options),
        },
        "metadata": coordinator.metadata,
        "outdoor_addresses": coordinator.outdoor_addrs,
        "units": coordinator.data,
        "outdoor": coordinator.outdoor,
    }
