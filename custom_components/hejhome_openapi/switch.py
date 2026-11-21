"""스위치: 조명이 아닌 onOff(플러그·스위치 채널), toggle(설정)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HejhomeConfigEntry
from .api import Capability
from .capability import async_setup_device_entities, switch_caps
from .const import OUTLET_NAME_HINTS
from .coordinator import HejhomeCoordinator
from .entity import HejhomeEntity, unique_id_for

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HejhomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    def build(device_id: str) -> list[HejhomeSwitch]:
        device = coordinator.devices[device_id]
        caps = coordinator.capabilities.get(device_id, [])
        chosen = switch_caps(caps, device.connection)
        channels = sum(1 for c in chosen if c.type == "onOff")
        return [HejhomeSwitch(coordinator, device_id, cap, channels) for cap in chosen]

    async_setup_device_entities(coordinator, async_add_entities, build)


class HejhomeSwitch(HejhomeEntity, SwitchEntity):
    def __init__(
        self,
        coordinator: HejhomeCoordinator,
        device_id: str,
        cap: Capability,
        channels: int,
    ) -> None:
        super().__init__(coordinator, device_id, cap.type, cap.instance)
        self._attr_unique_id = unique_id_for(device_id, cap.type, cap.instance)
        name = coordinator.devices[device_id].name.lower()
        if cap.type == "toggle":
            # child_lock 같은 설정 스위치. instance 이름을 그대로 보여 준다
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_translation_key = "toggle"
            self._attr_translation_placeholders = {"instance": cap.instance or "toggle"}
        else:
            if any(h in name for h in OUTLET_NAME_HINTS):
                self._attr_device_class = SwitchDeviceClass.OUTLET
            if channels > 1 or cap.instance is not None:
                self._attr_translation_key = "channel"
                self._attr_translation_placeholders = {"instance": cap.instance or "1"}
            else:
                self._attr_name = None  # 기기의 주 기능: 기기 이름 그대로

    @property
    def is_on(self) -> bool | None:
        value = self.field("on")
        return value if isinstance(value, bool) else None

    async def _set(self, on: bool) -> None:
        item: dict[str, Any] = {self.cap_type: {"on": on}}
        if self.instance is not None:
            item["instance"] = self.instance
        await self.coordinator.async_control(self.device_id, [item])

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
