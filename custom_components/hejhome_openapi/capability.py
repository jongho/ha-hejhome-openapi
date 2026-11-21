"""능력 → HA 엔터티 매핑 표 (design.md 9절, 1차 범위).

1차: sensor, binary_sensor, switch, light. 나머지 능력은 진단에만 남는다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

from .api import Capability

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import HejhomeCoordinator

_LOGGER = logging.getLogger(__name__)

LIGHT_FEATURES = frozenset({"brightness", "colorTemperature", "colorSetting"})
CLIMATE_HINTS = frozenset({"targetTemperature", "thermostatRunningState"})


@dataclass(frozen=True, slots=True)
class SensorSpec:
    field: str
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    translation_key: str | None = None
    entity_category: EntityCategory | None = None
    enabled_default: bool = True
    options: tuple[str, ...] | None = None  # ENUM일 때 선택지
    suffix: str | None = None  # 한 능력에서 센서가 여러 개일 때 고유 ID 꼬리


SENSORS: dict[str, tuple[SensorSpec, ...]] = {
    "temperatureSensor": (
        SensorSpec("celsius", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    ),
    "humiditySensor": (SensorSpec("percent", SensorDeviceClass.HUMIDITY, PERCENTAGE),),
    "battery": (
        SensorSpec(
            "percent",
            SensorDeviceClass.BATTERY,
            PERCENTAGE,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorSpec(
            "chargeState",
            SensorDeviceClass.ENUM,
            state_class=None,
            translation_key="charge_state",
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_default=False,
            options=("not_charging", "charging", "fully_charged"),
            suffix="charge_state",
        ),
    ),
    "illuminanceSensor": (SensorSpec("lux", SensorDeviceClass.ILLUMINANCE, LIGHT_LUX),),
    "energyMeter": (
        SensorSpec("powerWatts", SensorDeviceClass.POWER, UnitOfPower.WATT, suffix="power"),
        SensorSpec(
            "currentAmperes",
            SensorDeviceClass.CURRENT,
            UnitOfElectricCurrent.AMPERE,
            suffix="current",
        ),
        SensorSpec(
            "voltageVolts",
            SensorDeviceClass.VOLTAGE,
            UnitOfElectricPotential.VOLT,
            suffix="voltage",
        ),
    ),
    "airQualitySensor": (
        SensorSpec(
            "coPpm",
            SensorDeviceClass.CO,
            CONCENTRATION_PARTS_PER_MILLION,
        ),
    ),
    "filterState": (
        SensorSpec("lifeRemainingPercent", None, PERCENTAGE, translation_key="filter_life"),
    ),
    "deviceTemperature": (
        SensorSpec(
            "celsius",
            SensorDeviceClass.TEMPERATURE,
            UnitOfTemperature.CELSIUS,
            translation_key="device_temperature",
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_default=False,
        ),
    ),
    "actuationCount": (
        SensorSpec(
            "count",
            None,
            None,
            state_class=None,  # 단조 증가가 아니다
            translation_key="actuation_count",
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_default=False,
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class BinarySpec:
    field: str
    device_class: BinarySensorDeviceClass | None = None
    translation_key: str | None = None
    entity_category: EntityCategory | None = None
    enabled_default: bool = True
    on_value: object = True  # 이 값이면 켜짐
    suffix: str | None = None


BINARY_SENSORS: dict[str, tuple[BinarySpec, ...]] = {
    "contactSensor": (BinarySpec("open", BinarySensorDeviceClass.DOOR),),
    "motionSensor": (BinarySpec("detected", BinarySensorDeviceClass.MOTION),),
    "presenceSensor": (BinarySpec("present", BinarySensorDeviceClass.OCCUPANCY),),
    "leakSensor": (BinarySpec("detected", BinarySensorDeviceClass.MOISTURE),),
    "smokeSensor": (BinarySpec("detected", BinarySensorDeviceClass.SMOKE),),
    "carbonMonoxideSensor": (
        BinarySpec("detected", BinarySensorDeviceClass.CO),
        BinarySpec(
            "testInProgress",
            None,
            translation_key="co_test_in_progress",
            entity_category=EntityCategory.DIAGNOSTIC,
            suffix="test",
        ),
    ),
    # lock은 제어 스키마에 없어 읽기 전용. HA lock 기기 클래스는 "켜짐 = 열림"
    "lock": (BinarySpec("state", BinarySensorDeviceClass.LOCK, on_value="UNLOCKED"),),
    "onlineStatus": (
        BinarySpec(
            "online",
            BinarySensorDeviceClass.CONNECTIVITY,
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_default=False,
        ),
    ),
}

SWITCH_TYPES = frozenset({"onOff", "toggle"})
HANDLED_TYPES = frozenset(SENSORS) | frozenset(BINARY_SENSORS) | SWITCH_TYPES | LIGHT_FEATURES


# ── 묶음 규칙 ───────────────────────────────────────────


def light_parts(caps: Iterable[Capability]) -> tuple[Capability, list[Capability]] | None:
    """조명이면 (onOff, 조명 기능 능력들). 표시등 밝기(instance=indicator)는 조명이 아니다."""
    caps = list(caps)
    on_off = [c for c in caps if c.type == "onOff"]
    features = [
        c for c in caps if c.type in LIGHT_FEATURES and c.instance in (None,) and c.writable
    ]
    if len(on_off) != 1 or not features:
        return None
    return on_off[0], features


def is_climate(caps: Iterable[Capability], connection: str | None) -> bool:
    types = {c.type for c in caps}
    return bool(types & CLIMATE_HINTS) or (
        connection == "IR" and {"mode", "targetTemperature"} <= types
    )


def switch_caps(caps: Iterable[Capability], connection: str | None) -> list[Capability]:
    """스위치로 만들 능력: 조명·에어컨에 묶이지 않은 onOff, 그리고 toggle."""
    caps = list(caps)
    if connection == "IR":  # IR 기기는 2차(remote·climate)에서 다룬다
        return []
    light = light_parts(caps)
    used = {light[0].key} if light else set()
    climate = is_climate(caps, connection)
    return [
        c
        for c in caps
        if c.writable
        and c.key not in used
        and (c.type == "toggle" or (c.type == "onOff" and not climate))
    ]


def unhandled_types(caps: Iterable[Capability]) -> set[str]:
    return {c.type for c in caps if c.type not in HANDLED_TYPES}


# ── 플랫폼 공통: 지금 기기 + 나중에 생기는 기기 ──────────────


@callback
def async_setup_device_entities(
    coordinator: HejhomeCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[str], list[Entity]],
) -> None:
    """기기마다 build(기기 id)로 엔터티를 만들고, 새 기기가 생기면 다시 부른다."""

    def _add(device_ids: Iterable[str]) -> None:
        entities: list[Entity] = []
        for device_id in device_ids:
            if device_id in coordinator.devices:
                entities.extend(build(device_id))
        if entities:
            async_add_entities(entities)

    _add(list(coordinator.devices))
    coordinator.config_entry.async_on_unload(coordinator.async_add_new_device_listener(_add))
