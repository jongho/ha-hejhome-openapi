"""진단 다운로드. API 키·계정 이름은 가린다."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import HejhomeConfigEntry
from .capability import unhandled_types
from .const import CONF_LINKED_ACCOUNT_ID

TO_REDACT = {CONF_API_KEY, CONF_LINKED_ACCOUNT_ID, "linkedAccountId", "username"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HejhomeConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.diagnostics()
    for device_id, info in data["devices"].items():
        info["unhandled_capabilities"] = sorted(
            unhandled_types(coordinator.capabilities.get(device_id, []))
        )
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": async_redact_data(data, TO_REDACT),
    }
