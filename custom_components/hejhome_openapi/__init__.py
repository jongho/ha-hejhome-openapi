"""헤이홈 공식 Open API v3 통합."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HejhomeClient
from .capability import unhandled_types
from .const import DOMAIN
from .coordinator import HejhomeCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type HejhomeConfigEntry = ConfigEntry[HejhomeCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HejhomeConfigEntry) -> bool:
    client = HejhomeClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = HejhomeCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    for device_id, device in coordinator.devices.items():
        if skipped := unhandled_types(coordinator.capabilities.get(device_id, [])):
            _LOGGER.info(
                "%s: 아직 엔터티로 만들지 않는 능력 %s (진단 파일에 원본이 남습니다)",
                device.name,
                ", ".join(sorted(skipped)),
            )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HejhomeConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: HejhomeConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """API 기기 목록에 더는 없는 기기만 사용자가 지울 수 있다."""
    coordinator = entry.runtime_data
    return not any(
        ident[0] == DOMAIN and ident[1] in coordinator.devices
        for ident in device_entry.identifiers
    )
