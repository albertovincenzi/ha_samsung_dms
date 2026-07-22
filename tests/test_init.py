"""Tests for setup/unload and the diagnostics dump."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.diagnostics.const import REDACTED
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samsung_dms.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from custom_components.samsung_dms.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
) -> None:
    """The entry loads with a mocked client and unloads cleanly."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_redacts_credentials(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
) -> None:
    """Credentials are redacted; the host (a LAN address) is kept."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    data = diag["entry"]["data"]

    assert data[CONF_PASSWORD] == REDACTED
    assert data[CONF_USERNAME] == REDACTED
    assert data[CONF_HOST] == "192.168.1.5"
