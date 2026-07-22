"""Shared fixtures for the Samsung DMS test suite."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samsung_dms.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None, None, None]:
    """Enable loading of the samsung_dms custom component in every test."""
    yield


ENTRY_DATA = {
    CONF_HOST: "192.168.1.5",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_VERIFY_SSL: False,
}


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for the DMS at a fixed host."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Samsung DMS (192.168.1.5)",
        data=ENTRY_DATA,
        unique_id="192.168.1.5",
    )


@pytest.fixture
def mock_client() -> Generator[MagicMock, None, None]:
    """Patch the DMS client and aiohttp so no real network/threads are used."""
    with (
        patch(
            "custom_components.samsung_dms.SamsungDMSClient", autospec=True
        ) as client_cls,
        patch("custom_components.samsung_dms.aiohttp.ClientSession") as session_cls,
        patch("custom_components.samsung_dms.aiohttp.TCPConnector"),
        patch("custom_components.samsung_dms.aiohttp.CookieJar"),
    ):
        session_cls.return_value.close = AsyncMock()
        client = client_cls.return_value
        client.async_login.return_value = None
        client.async_get_indoor_metadata.return_value = {}
        client.async_get_outdoor_addresses.return_value = []
        client.async_get_monitoring.return_value = []
        client.async_get_cycle_monitoring.return_value = {}
        yield client
