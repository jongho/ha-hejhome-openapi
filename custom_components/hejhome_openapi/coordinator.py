"""기기·능력 캐시와 상태 폴링 (design.md 7·8절)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    Capability,
    CapKey,
    Device,
    DeviceState,
    HejhomeAuthError,
    HejhomeClient,
    HejhomeDeviceOfflineError,
    HejhomeError,
    HejhomeForbiddenError,
    HejhomeNotFoundError,
    HejhomeNotReadyError,
    HejhomePermissionDeniedError,
    HejhomeRateLimitError,
    HejhomeRequestError,
)
from .const import (
    BACKOFF_MAX,
    BACKOFF_START,
    CONF_REFRESH_HOURS,
    CONF_SCAN_INTERVAL,
    CONF_SPACE_ID,
    DEFAULT_REFRESH_HOURS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SILENT_POLL_FAILURES,
    MIN_SCAN_INTERVAL,
    OPTIMISTIC_TIMEOUT,
    REFRESH_AFTER_CONTROL,
)

if TYPE_CHECKING:
    from . import HejhomeConfigEntry

_LOGGER = logging.getLogger(__name__)

RATE_LIMIT_ISSUE_COUNT = 3  # 1시간에 이만큼 429가 나면 수리 알림
RATE_LIMIT_WINDOW = timedelta(hours=1)


@dataclass(slots=True)
class _Pending:
    """제어 뒤 아직 상태로 확인되지 않은 값(낙관적 값)."""

    value: dict[str, Any]
    sent_at: datetime


class HejhomeCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """`data`는 {기기 id: DeviceState}. 기기 목록과 능력은 속성으로 따로 둔다."""

    config_entry: HejhomeConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: HejhomeConfigEntry, client: HejhomeClient
    ) -> None:
        interval = max(
            MIN_SCAN_INTERVAL, int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=interval),
            always_update=False,
        )
        self.client = client
        self.space_id: str = entry.data[CONF_SPACE_ID]
        self.devices: dict[str, Device] = {}
        self.capabilities: dict[str, list[Capability]] = {}
        self.areas: dict[str, str] = {}  # 기기 id → 방 이름
        self.unsupported: dict[str, str] = {}  # 기기 id → 사유 (진단용)
        self._refresh_every = timedelta(
            hours=float(entry.options.get(CONF_REFRESH_HOURS, DEFAULT_REFRESH_HOURS))
        )
        self._devices_fetched_at: datetime | None = None
        self._new_device_listeners: list[Callable[[set[str]], None]] = []
        self._pending: dict[tuple[str, CapKey], _Pending] = {}
        self._backoff: float = 0.0
        self._rate_limited_at: list[datetime] = []
        self._silent_failures = 0
        self.last_error: str | None = None

    # ── 기기 목록 ────────────────────────────────────────

    async def _async_setup(self) -> None:
        """첫 갱신 전에 한 번: 기기 목록·능력·방."""
        try:
            await self._refresh_devices()
        except HejhomeError as err:
            raise self._translate(err) from err

    async def _refresh_devices(self) -> None:
        client = self.client
        devices = {d.id: d for d in await client.devices(space_ids=[self.space_id])}

        # 새로 보이는 기기만 능력을 받는다. 능력은 잘 바뀌지 않지만 주기적 갱신 때는 모두 다시 받는다.
        full = self._devices_fetched_at is not None
        caps: dict[str, list[Capability]] = {}
        unsupported: dict[str, str] = {}
        for device_id in devices:
            if not full and device_id in self.capabilities:
                caps[device_id] = self.capabilities[device_id]
                continue
            try:
                caps[device_id] = await client.capabilities(device_id)
            except (HejhomeNotFoundError, HejhomePermissionDeniedError, HejhomeRequestError) as err:
                # 지원하지 않는 기기 등. 다른 오류(인증·한도·연결)는 위로 올린다.
                unsupported[device_id] = f"capabilities: {err}"
                caps[device_id] = self.capabilities.get(device_id, [])

        self.areas = await self._fetch_areas()

        added = set(devices) - set(self.devices)
        removed = set(self.devices) - set(devices)
        self.devices = devices
        self.capabilities = caps
        self.unsupported = unsupported
        self._devices_fetched_at = dt_util.utcnow()

        if removed and devices:  # 빈 목록은 일시 오류일 수 있으니 지우지 않는다
            self._remove_devices(removed)
        if added and full:
            _LOGGER.info("새 기기 %d대: %s", len(added), ", ".join(devices[d].name for d in added))
            for listener in list(self._new_device_listeners):
                listener(added)

    async def _fetch_areas(self) -> dict[str, str]:
        """방마다 기기 목록을 받아 기기 → 방 이름을 만든다. 깊은 방이 이긴다."""
        spaces = await self.client.spaces()
        by_id = {s.id: s for s in spaces}

        def depth(space_id: str) -> int | None:
            d, cur, seen = 0, by_id.get(space_id), set()
            while cur is not None and cur.id not in seen:
                if cur.id == self.space_id:
                    return d
                seen.add(cur.id)
                cur = by_id.get(cur.parent_id) if cur.parent_id else None
                d += 1
            return None

        rooms = sorted(
            ((dep, s) for s in spaces if s.id != self.space_id and (dep := depth(s.id))),
            key=lambda x: x[0],
        )
        areas: dict[str, str] = {}
        for _, room in rooms:
            for device in await self.client.devices(space_ids=[room.id]):
                areas[device.id] = room.name
        return areas

    def _remove_devices(self, removed: set[str]) -> None:
        registry = dr.async_get(self.hass)
        for device_id in removed:
            if entry := registry.async_get_device(identifiers={(DOMAIN, device_id)}):
                _LOGGER.info("없어진 기기를 지웁니다: %s", entry.name)
                registry.async_update_device(
                    entry.id, remove_config_entry_id=self.config_entry.entry_id
                )
            self.capabilities.pop(device_id, None)
            for key in [k for k in self._pending if k[0] == device_id]:
                del self._pending[key]

    @callback
    def async_add_new_device_listener(
        self, listener: Callable[[set[str]], None]
    ) -> CALLBACK_TYPE:
        self._new_device_listeners.append(listener)

        @callback
        def _remove() -> None:
            self._new_device_listeners.remove(listener)

        return _remove

    # ── 상태 폴링 ────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, DeviceState]:
        now = dt_util.utcnow()
        try:
            if self._devices_fetched_at is None or now - self._devices_fetched_at >= self._refresh_every:
                await self._refresh_devices()
            states = await self.client.states(space_ids=[self.space_id])
            if set(states) - set(self.devices):
                await self._refresh_devices()  # 모르는 기기 id가 보이면 목록 다시 받기
        except HejhomeError as err:
            return self._handle_poll_error(err)

        self._on_poll_success()
        merged = self._merge(states)
        self._expire_pending(merged, now)
        return merged

    def _merge(self, states: dict[str, DeviceState]) -> dict[str, DeviceState]:
        """읽기 실패(UNAVAILABLE)나 빠진 능력은 이전 값을 유지한다."""
        old = self.data or {}
        merged: dict[str, DeviceState] = {}
        for device_id, new in states.items():
            prev = old.get(device_id)
            caps = dict(prev.capabilities) if prev else {}
            for key, cap_state in new.capabilities.items():
                if cap_state.unavailable and key in caps:
                    continue
                caps[key] = cap_state
            merged[device_id] = DeviceState(device_id, caps, raw=new.raw)
        return merged

    def _expire_pending(self, data: dict[str, DeviceState], now: datetime) -> None:
        """상태가 보낸 뒤에 받은 값이면 확정, 오래되면 버린다(그 능력이 보고된 적이 있을 때만)."""
        for key, pending in list(self._pending.items()):
            device_id, (cap_type, instance) = key
            state = data.get(device_id)
            cap_state = state.get(cap_type, instance) if state else None
            if cap_state is None:
                continue  # 보고하지 않는 능력은 마지막으로 보낸 값을 그대로 쓴다
            times = [cap_state.field_time(f) for f in pending.value]
            if all(t is not None and t >= pending.sent_at for t in times):
                del self._pending[key]
            elif now - pending.sent_at > OPTIMISTIC_TIMEOUT:
                _LOGGER.debug("제어 결과가 상태에 반영되지 않았습니다: %s %s", device_id, key[1])
                del self._pending[key]

    def _handle_poll_error(self, err: HejhomeError) -> dict[str, DeviceState]:
        self.last_error = str(err)
        if isinstance(err, (HejhomeAuthError, HejhomeForbiddenError)):
            raise self._translate(err) from err
        if isinstance(err, HejhomeRateLimitError):
            now = dt_util.utcnow()
            self._rate_limited_at = [t for t in self._rate_limited_at if now - t < RATE_LIMIT_WINDOW]
            self._rate_limited_at.append(now)
            if len(self._rate_limited_at) >= RATE_LIMIT_ISSUE_COUNT:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"rate_limited_{self.config_entry.entry_id}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="rate_limited",
                    translation_placeholders={"title": self.config_entry.title},
                )
            self._backoff = min(BACKOFF_MAX, max(BACKOFF_START, self._backoff * 2))
            wait = max(self._backoff, err.retry_after or 0)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                translation_placeholders={"seconds": str(int(wait))},
                retry_after=wait,
            ) from err
        # 연결 오류·서버 오류: 몇 번은 이전 데이터를 유지한다
        self._silent_failures += 1
        if self.data is not None and self._silent_failures <= MAX_SILENT_POLL_FAILURES:
            _LOGGER.debug("폴링 실패 %d회째, 이전 데이터 유지: %s", self._silent_failures, err)
            return self.data
        raise UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    def _on_poll_success(self) -> None:
        self._silent_failures = 0
        self._backoff = 0.0
        self.last_error = None
        for issue in ("ip_not_allowed", "organization_inactive"):
            ir.async_delete_issue(self.hass, DOMAIN, f"{issue}_{self.config_entry.entry_id}")
        if self._rate_limited_at and dt_util.utcnow() - self._rate_limited_at[-1] > RATE_LIMIT_WINDOW:
            self._rate_limited_at.clear()
            ir.async_delete_issue(self.hass, DOMAIN, f"rate_limited_{self.config_entry.entry_id}")

    def _translate(self, err: HejhomeError) -> Exception:
        """설정 단계·폴링에서 HA 예외로."""
        if isinstance(err, HejhomeAuthError):
            return ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            )
        if isinstance(err, HejhomeForbiddenError):
            key = "ip_not_allowed" if err.code == "API_KEY_IP_NOT_ALLOWED" else "organization_inactive"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{key}_{self.config_entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=key,
                translation_placeholders={"title": self.config_entry.title},
            )
            return ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key=key)
        return UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"error": str(err)},
        )

    # ── 엔터티가 쓰는 값 ──────────────────────────────────

    def cap_value(self, device_id: str, cap_type: str, instance: str | None = None) -> dict[str, Any] | None:
        """능력 값(dict). 확인 전인 제어 값이 있으면 그 위에 덮어 보여 준다."""
        state = (self.data or {}).get(device_id)
        cap_state = state.get(cap_type, instance) if state else None
        value = dict(cap_state.value) if cap_state else None
        if pending := self._pending.get((device_id, (cap_type, instance))):
            value = {**(value or {}), **pending.value}
        return value

    def capability(self, device_id: str, cap_type: str, instance: str | None = None) -> Capability | None:
        for cap in self.capabilities.get(device_id, []):
            if cap.type == cap_type and cap.instance == instance:
                return cap
        return None

    def device_online(self, device_id: str) -> bool:
        state = (self.data or {}).get(device_id)
        return state is None or state.online is not False

    # ── 제어 ────────────────────────────────────────────

    async def async_control(self, device_id: str, desired: list[dict[str, Any]]) -> None:
        """POST /control → 낙관적 반영 → 2초 뒤 다시 조회. 재시도는 하지 않는다."""
        try:
            await self.client.control(device_id, desired)
        except HejhomeRequestError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_request",
                translation_placeholders={"error": err.detail or str(err)},
            ) from err
        except HejhomeDeviceOfflineError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="device_offline"
            ) from err
        except HejhomeNotReadyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_not_ready",
                translation_placeholders={"error": err.code or str(err)},
            ) from err
        except HejhomeAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except HejhomeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="control_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        sent_at = dt_util.utcnow()
        for item in desired:
            instance = item.get("instance")
            for cap_type, value in item.items():
                if cap_type == "instance" or not isinstance(value, dict):
                    continue
                key = (device_id, (cap_type, instance))
                prev = self._pending.get(key)
                merged = {**prev.value, **value} if prev else dict(value)
                self._pending[key] = _Pending(merged, sent_at)
        self.async_update_listeners()

        @callback
        def _refresh(_now: datetime) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        async_call_later(self.hass, REFRESH_AFTER_CONTROL, _refresh)

    # ── 진단 ────────────────────────────────────────────

    def diagnostics(self) -> dict[str, Any]:
        return {
            "space_id": self.space_id,
            "update_interval": self.update_interval.total_seconds() if self.update_interval else None,
            "request_count": self.client.request_count,
            "backoff_seconds": self._backoff,
            "rate_limited_last_hour": len(self._rate_limited_at),
            "silent_failures": self._silent_failures,
            "last_error": self.last_error,
            "devices_fetched_at": self._devices_fetched_at.isoformat() if self._devices_fetched_at else None,
            "devices": {
                d.id: {
                    "name": d.name,
                    "connection": d.connection,
                    "area": self.areas.get(d.id),
                    "capabilities": [c.raw for c in self.capabilities.get(d.id, [])],
                    "state": (self.data or {}).get(d.id).raw if (self.data or {}).get(d.id) else None,
                    "unsupported": self.unsupported.get(d.id),
                }
                for d in self.devices.values()
            },
            "pending": {
                f"{k[0]}:{k[1][0]}:{k[1][1]}": {"value": p.value, "sent_at": p.sent_at.isoformat()}
                for k, p in self._pending.items()
            },
        }
