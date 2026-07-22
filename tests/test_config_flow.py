"""Tests for the Samsung DMS config, reauth and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samsung_dms.api import (
    SamsungDMSAuthError,
    SamsungDMSConnectionError,
)
from custom_components.samsung_dms.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)

_USER_INPUT = {
    CONF_HOST: "192.168.1.9",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_VERIFY_SSL: False,
}

_VALIDATE = "custom_components.samsung_dms.config_flow._validate"
_SETUP = "custom_components.samsung_dms.async_setup_entry"


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A valid login creates the config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch(_VALIDATE, AsyncMock(return_value=None)), patch(
        _SETUP, return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "192.168.1.9"
    assert result["result"].unique_id == "192.168.1.9"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SamsungDMSAuthError(), "invalid_auth"),
        (SamsungDMSConnectionError(), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_recover(
    hass: HomeAssistant, error: Exception, expected: str
) -> None:
    """Login failures surface as a form error and allow a retry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with patch(_VALIDATE, AsyncMock(side_effect=error)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    # The flow stays open: a subsequent valid attempt still succeeds.
    with patch(_VALIDATE, AsyncMock(return_value=None)), patch(
        _SETUP, return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A host that is already set up aborts the flow."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(_VALIDATE, AsyncMock(return_value=None)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**_USER_INPUT, CONF_HOST: "192.168.1.5"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_updates_credentials(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Reauth validates and stores the new credentials, then reloads."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(_VALIDATE, AsyncMock(return_value=None)), patch(
        _SETUP, return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "admin", CONF_PASSWORD: "newsecret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "newsecret"


async def test_reauth_flow_rejects_bad_credentials(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A failed reauth login re-shows the form with an error."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    with patch(_VALIDATE, AsyncMock(side_effect=SamsungDMSAuthError())):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "admin", CONF_PASSWORD: "wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_PASSWORD] == "secret"


async def test_options_flow_sets_scan_interval(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The options flow stores a validated polling interval."""
    mock_config_entry.add_to_hass(hass)

    with patch(_SETUP, return_value=True), patch(
        "custom_components.samsung_dms.async_unload_entry", return_value=True
    ):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 120}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_SCAN_INTERVAL] == 120


async def test_options_flow_rejects_out_of_range(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A polling interval outside the allowed bounds is refused."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 1}
        )
