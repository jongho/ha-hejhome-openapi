"""센서: 온도·습도·배터리·조도·전력 등."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HejhomeConfigEntry
from .capability import SENSORS, SensorSpec, async_setup_device_entities
from .coordinator import HejhomeCoordinator
from .entity import HejhomeEntity, unique_id_for

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HejhomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    def build(device_id: str) -> list[HejhomeSensor]:
        return [
            HejhomeSensor(coordinator, device_id, cap.type, cap.instance, spec)
            for cap in coordinator.capabilities.get(device_id, [])
            if cap.readable
            for spec in SENSORS.get(cap.type, ())
        ]

    async_setup_device_entities(coordinator, async_add_entities, build)


class HejhomeSensor(HejhomeEntity, SensorEntity):
    def __init__(
        self,
        coordinator: HejhomeCoordinator,
        device_id: str,
        cap_type: str,
        instance: str | None,
        spec: SensorSpec,
    ) -> None:
        super().__init__(coordinator, device_id, cap_type, instance)
        self.spec = spec
        self._attr_unique_id = unique_id_for(device_id, cap_type, instance, spec.suffix)
        self._attr_device_class = spec.device_class
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_state_class = spec.state_class
        self._attr_entity_category = spec.entity_category
        self._attr_entity_registry_enabled_default = spec.enabled_default
        if spec.options:
            self._attr_options = list(spec.options)
        if spec.translation_key:
            self._attr_translation_key = spec.translation_key
        if instance is not None:
            # 같은 능력이 여러 개면 이름에 instance를 붙인다
            self._attr_translation_key = spec.translation_key or "instance"
            self._attr_translation_placeholders = {"instance": instance}

    @property
    def native_value(self) -> Any:
        value = self.field(self.spec.field)
        if value is None:
            return None
        if self.spec.device_class is SensorDeviceClass.ENUM:
            value = str(value).lower()
            return value if value in (self.spec.options or ()) else None
        return value
