"""공통 기반 엔터티."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HejhomeCoordinator


def unique_id_for(device_id: str, cap_type: str, instance: str | None, suffix: str | None = None) -> str:
    """고유 ID: `{기기 id}_{능력}[_{instance}][_{필드}]`."""
    parts = [device_id, cap_type]
    if instance is not None:
        parts.append(instance)
    if suffix:
        parts.append(suffix)
    return "_".join(parts)


class HejhomeEntity(CoordinatorEntity[HejhomeCoordinator]):
    """기기 하나의 능력 하나(또는 묶음)를 나타내는 엔터티."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HejhomeCoordinator,
        device_id: str,
        cap_type: str,
        instance: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self.cap_type = cap_type
        self.instance = instance
        device = coordinator.devices[device_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model="IR remote" if device.connection == "IR" else None,
            suggested_area=coordinator.areas.get(device_id),
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.device_id in self.coordinator.devices
            and self.coordinator.device_online(self.device_id)
        )

    def cap_value(self, cap_type: str | None = None, instance: Any = ...) -> dict[str, Any] | None:
        """이 엔터티 능력(또는 같은 기기의 다른 능력)의 현재 값."""
        return self.coordinator.cap_value(
            self.device_id,
            cap_type or self.cap_type,
            self.instance if instance is ... else instance,
        )

    def field(self, name: str, cap_type: str | None = None, instance: Any = ...) -> Any:
        value = self.cap_value(cap_type, instance)
        return None if value is None else value.get(name)
