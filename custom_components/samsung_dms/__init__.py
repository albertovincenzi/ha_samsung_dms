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
    DOMAIN,
)
from .coordinator import SamsungDMSCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE]


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
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await session.close()
        raise

    entry.runtime_data = coordinator
    entry.async_on_unload(lambda: hass.async_create_task(session.close()))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
