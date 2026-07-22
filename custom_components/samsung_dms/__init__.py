"""The Samsung DMS integration."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import (
    SamsungDMSAuthError,
    SamsungDMSClient,
    SamsungDMSConnectionError,
)
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_VERIFY_SSL,
)
from .coordinator import SamsungDMSCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.WATER_HEATER,
    Platform.FAN,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Samsung DMS from a config entry."""
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

    # A bare-IP host requires an unsafe cookie jar to retain JSESSIONID, and the
    # DMS ships a self-signed cert so TLS verification is normally disabled.
    connector = aiohttp.TCPConnector(ssl=verify_ssl)
    session = aiohttp.ClientSession(
        connector=connector,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )

    client = SamsungDMSClient(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=session,
    )

    try:
        await client.async_login()
    except SamsungDMSAuthError as err:
        await session.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except SamsungDMSConnectionError as err:
        await session.close()
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = SamsungDMSCoordinator(hass, entry, client)
    # Friendly names/models come from a separate tree-view call; load once.
    await coordinator.async_load_metadata()
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await session.close()
        raise

    entry.runtime_data = coordinator
    # ``session.close`` is a coroutine function; HA awaits it during unload.
    entry.async_on_unload(session.close)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change (e.g. polling interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
