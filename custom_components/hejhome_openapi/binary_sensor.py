"""이진 센서: 문 열림·움직임·재실·누수·연기·일산화탄소·잠금 상태·연결."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HejhomeConfigEntry
from .capability import BINARY_SENSORS, BinarySpec, async_setup_device_entities
from .coordinator import HejhomeCoordinator
from .entity import HejhomeEntity, unique_id_for

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HejhomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    def build(device_id: str) -> list[BinarySensorEntity]:
        entities: list[BinarySensorEntity] = []
        for cap in coordinator.capabilities.get(device_id, []):
            if not cap.readable:
                continue
            for spec in BINARY_SENSORS.get(cap.type, ()):
                cls = HejhomeConnectivity if cap.type == "onlineStatus" else HejhomeBinarySensor
                entities.append(cls(coordinator, device_id, cap.type, cap.instance, spec))
        return entities

    async_setup_device_entities(coordinator, async_add_entities, build)


class HejhomeBinarySensor(HejhomeEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: HejhomeCoordinator,
        device_id: str,
        cap_type: str,
        instance: str | None,
        spec: BinarySpec,
    ) -> None:
        super().__init__(coordinator, device_id, cap_type, instance)
        self.spec = spec
        self._attr_unique_id = unique_id_for(device_id, cap_type, instance, spec.suffix)
        self._attr_device_class = spec.device_class
        self._attr_entity_category = spec.entity_category
        self._attr_entity_registry_enabled_default = spec.enabled_default
        if spec.translation_key:
            self._attr_translation_key = spec.translation_key
        if instance is not None:
            self._attr_translation_key = spec.translation_key or "instance"
            self._attr_translation_placeholders = {"instance": instance}

    @property
    def is_on(self) -> bool | None:
        value = self.field(self.spec.field)
        if value is None:
            return None
        return value == self.spec.on_value


class HejhomeConnectivity(HejhomeBinarySensor):
    """연결 상태는 기기가 오프라인이어도 값을 보여 줘야 한다."""

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.device_id in self.coordinator.devices
