"""조명: onOff + brightness / colorTemperature / colorSetting.

헤이홈 컬러 전구는 흰색 모드와 컬러 모드가 따로다(mode run_mode: white·color·…).
- 흰색 모드: 밝기 = brightness.percent, 색온도 = colorTemperature.kelvin
- 컬러 모드: 색과 밝기 = colorSetting.hsv(hue, saturation, value)
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HejhomeConfigEntry
from .api import Capability, ValueRange
from .capability import async_setup_device_entities, light_parts
from .coordinator import HejhomeCoordinator
from .entity import HejhomeEntity, unique_id_for

PARALLEL_UPDATES = 1

RUN_MODE = "run_mode"
MODE_WHITE = "white"
MODE_COLOR = "color"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HejhomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    def build(device_id: str) -> list[HejhomeLight]:
        device = coordinator.devices[device_id]
        if device.connection == "IR":
            return []
        parts = light_parts(coordinator.capabilities.get(device_id, []))
        if parts is None:
            return []
        on_off, features = parts
        return [HejhomeLight(coordinator, device_id, on_off, features)]

    async_setup_device_entities(coordinator, async_add_entities, build)


def _clamp(value: float, rng: ValueRange | None, default_min: float, default_max: float) -> int:
    lo = rng.min if rng and rng.min is not None else default_min
    hi = rng.max if rng and rng.max is not None else default_max
    return int(round(min(max(value, lo), hi)))


def _pct_to_ha(pct: Any) -> int | None:
    if not isinstance(pct, (int, float)):
        return None
    return max(0, min(255, round(pct * 255 / 100)))


def _ha_to_pct(brightness: int) -> float:
    return max(1.0, brightness * 100 / 255)  # 0%로 켜지 않게


class HejhomeLight(HejhomeEntity, LightEntity):
    _attr_name = None  # 기기의 주 기능

    def __init__(
        self,
        coordinator: HejhomeCoordinator,
        device_id: str,
        on_off: Capability,
        features: list[Capability],
    ) -> None:
        super().__init__(coordinator, device_id, "onOff", on_off.instance)
        self._attr_unique_id = unique_id_for(device_id, "light", on_off.instance)
        by_type = {c.type: c for c in features}
        self._brightness_cap = by_type.get("brightness")
        self._ct_cap = by_type.get("colorTemperature")
        self._color_cap = by_type.get("colorSetting")
        self._mode_cap = coordinator.capability(device_id, "mode", RUN_MODE)
        self._last_mode: ColorMode | None = None

        modes: set[ColorMode] = set()
        if self._color_cap:
            modes.add(ColorMode.HS)
        if self._ct_cap:
            modes.add(ColorMode.COLOR_TEMP)
            rng = self._ct_cap.range
            self._attr_min_color_temp_kelvin = int(rng.min) if rng and rng.min else 2700
            self._attr_max_color_temp_kelvin = int(rng.max) if rng and rng.max else 6500
        if not modes:
            modes.add(ColorMode.BRIGHTNESS if self._brightness_cap else ColorMode.ONOFF)
        self._attr_supported_color_modes = modes

    # ── 상태 ────────────────────────────────────────────

    def _mode_value(self) -> str | None:
        if not self._mode_cap:
            return None
        value = self.field("current", "mode", RUN_MODE)
        return str(value).lower() if value is not None else None

    @property
    def color_mode(self) -> ColorMode:
        modes = self._attr_supported_color_modes or {ColorMode.ONOFF}
        if len(modes) == 1:
            return next(iter(modes))
        mode = self._mode_value()
        if mode == MODE_COLOR:
            return ColorMode.HS
        if mode == MODE_WHITE:
            return ColorMode.COLOR_TEMP
        return self._last_mode or ColorMode.COLOR_TEMP

    @property
    def is_on(self) -> bool | None:
        value = self.field("on")
        return value if isinstance(value, bool) else None

    def _hsv(self) -> dict[str, Any] | None:
        value = self.field("hsv", "colorSetting", None)
        return value if isinstance(value, dict) else None

    @property
    def brightness(self) -> int | None:
        if self.color_mode is ColorMode.HS and (hsv := self._hsv()):
            return _pct_to_ha(hsv.get("value"))
        if self._brightness_cap:
            return _pct_to_ha(self.field("percent", "brightness", None))
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        if not self._ct_cap:
            return None
        value = self.field("kelvin", "colorTemperature", None)
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        hsv = self._hsv()
        if not hsv or hsv.get("hue") is None or hsv.get("saturation") is None:
            return None
        return float(hsv["hue"]), float(hsv["saturation"])

    # ── 제어 ────────────────────────────────────────────

    def _mode_item(self, mode: str) -> dict[str, Any] | None:
        """모드를 바꿔야 하고 바꿀 수 있을 때만 mode 항목."""
        cap = self._mode_cap
        if not cap or not cap.writable or self._mode_value() == mode:
            return None
        value = next((v for v in cap.values if v.lower() == mode), None)
        if value is None:
            return None
        return {"instance": RUN_MODE, "mode": {"current": value}}

    def _with_instance(self, item: dict[str, Any]) -> dict[str, Any]:
        if self.instance is not None:
            item["instance"] = self.instance
        return item

    async def async_turn_on(self, **kwargs: Any) -> None:
        desired: list[dict[str, Any]] = []
        if self.is_on is not True:
            desired.append(self._with_instance({"onOff": {"on": True}}))

        brightness = kwargs.get(ATTR_BRIGHTNESS)
        hs = kwargs.get(ATTR_HS_COLOR)
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)

        if hs is not None and self._color_cap:
            target = ColorMode.HS
        elif kelvin is not None and self._ct_cap:
            target = ColorMode.COLOR_TEMP
        else:
            target = self.color_mode

        if target is ColorMode.HS and (hs is not None or brightness is not None):
            cur = self._hsv() or {}
            cap = self._color_cap
            assert cap is not None
            hue, sat = hs if hs is not None else (cur.get("hue", 0), cur.get("saturation", 100))
            value = _ha_to_pct(brightness) if brightness is not None else cur.get("value") or 100
            desired.append(
                {
                    "colorSetting": {
                        "hsv": {
                            "hue": _clamp(hue, cap.range_for("hsv.hue"), 0, 360),
                            "saturation": _clamp(sat, cap.range_for("hsv.saturation"), 0, 100),
                            "value": _clamp(value, cap.range_for("hsv.value"), 1, 100),
                        }
                    }
                }
            )
            if item := self._mode_item(MODE_COLOR):
                desired.append(item)
        elif target is ColorMode.COLOR_TEMP or target is ColorMode.BRIGHTNESS:
            if kelvin is not None and self._ct_cap:
                desired.append(
                    {"colorTemperature": {"kelvin": _clamp(kelvin, self._ct_cap.range, 2700, 6500)}}
                )
            if brightness is not None and self._brightness_cap:
                desired.append(
                    {
                        "brightness": {
                            "percent": _clamp(
                                _ha_to_pct(brightness), self._brightness_cap.range, 1, 100
                            )
                        }
                    }
                )
            if kelvin is not None and (item := self._mode_item(MODE_WHITE)):
                desired.append(item)

        if not desired:
            return
        self._last_mode = target if target in (ColorMode.HS, ColorMode.COLOR_TEMP) else None
        await self.coordinator.async_control(self.device_id, desired)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_control(
            self.device_id, [self._with_instance({"onOff": {"on": False}})]
        )
