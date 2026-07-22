"""Config flow for the Samsung DMS integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import config_validation as cv

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
    DEFAULT_USERNAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
    }
)


async def _validate(data: dict[str, Any]) -> None:
    """Attempt a login with the supplied credentials."""
    connector = aiohttp.TCPConnector(ssl=data[CONF_VERIFY_SSL])
    session = aiohttp.ClientSession(
        connector=connector,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )
    try:
        client = SamsungDMSClient(
            host=data[CONF_HOST],
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            session=session,
        )
        await client.async_login()
    finally:
        await session.close()


class SamsungDMSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Samsung DMS."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            user_input[CONF_HOST] = host
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            try:
                await _validate(user_input)
            except SamsungDMSAuthError:
                errors["base"] = "invalid_auth"
            except SamsungDMSConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - surface as generic error
                _LOGGER.exception("Unexpected error validating DMS connection")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Samsung DMS ({host})", data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
