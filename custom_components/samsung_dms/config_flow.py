"""Config flow for the Samsung DMS integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .api import (
    SamsungDMSAuthError,
    SamsungDMSClient,
    SamsungDMSConnectionError,
)
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DEFAULT_USERNAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
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


async def _login_error(data: dict[str, Any]) -> str | None:
    """Attempt a login and return an error key, or ``None`` on success."""
    try:
        await _validate(data)
    except SamsungDMSAuthError:
        return "invalid_auth"
    except SamsungDMSConnectionError:
        return "cannot_connect"
    except Exception:  # noqa: BLE001 - surface as generic error
        _LOGGER.exception("Unexpected error validating DMS connection")
        return "unknown"
    return None


class SamsungDMSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Samsung DMS."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return SamsungDMSOptionsFlow()

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

            error = await _login_error(user_input)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Samsung DMS ({host})", data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for new credentials and validate them against the DMS."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, **user_input}
            error = await _login_error(data)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=entry.data.get(CONF_USERNAME)
                ): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={CONF_HOST: entry.data[CONF_HOST]},
        )


class SamsungDMSOptionsFlow(OptionsFlow):
    """Handle Samsung DMS options (polling interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_SCAN_INTERVAL_SECONDS,
                        max=MAX_SCAN_INTERVAL_SECONDS,
                    ),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
