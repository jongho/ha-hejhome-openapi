"""헤이홈 Open API 응답 모델.

모르는 능력·필드·enum 값은 버리지 않는다. 능력 값은 응답 그대로의 dict로 두고,
원본은 `raw`에 남겨 진단에 쓴다(API는 필드·값을 예고 없이 추가할 수 있다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# (능력 type, instance) — instance가 없으면 None
CapKey = tuple[str, str | None]

_STATE_META = frozenset(
    {"instance", "reportedAt", "fieldReportedAt", "receivedAt", "fieldReceivedAt", "readStatus"}
)


def parse_time(value: Any) -> datetime | None:
    """ISO 8601(시간대 포함) 문자열 → datetime. 형식이 틀리면 None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class LinkedAccount:
    id: str
    status: str
    username: str | None = None
    linked_at: datetime | None = None

    @property
    def available(self) -> bool:
        return self.status == "AVAILABLE"

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> LinkedAccount:
        return cls(
            id=d["id"],
            status=d.get("status", ""),
            username=d.get("username"),
            linked_at=parse_time(d.get("linkedAt")),
        )


@dataclass(frozen=True, slots=True)
class Space:
    id: str
    type: str  # HOME, ROOM, …
    name: str
    linked_account_id: str
    parent_id: str | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Space:
        return cls(
            id=d["id"],
            type=d.get("type", ""),
            name=d.get("name", ""),
            linked_account_id=d.get("linkedAccountId", ""),
            parent_id=d.get("parentId"),
        )


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    name: str
    linked_account_id: str
    connection: str | None = None  # "IR" 또는 None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Device:
        return cls(
            id=d["id"],
            name=d.get("name", ""),
            linked_account_id=d.get("linkedAccountId", ""),
            connection=d.get("connection"),
        )


@dataclass(frozen=True, slots=True)
class ValueRange:
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None

    @classmethod
    def from_api(cls, d: Any) -> ValueRange | None:
        if not isinstance(d, dict):
            return None
        return cls(d.get("min"), d.get("max"), d.get("step"), d.get("unit"))


@dataclass(frozen=True, slots=True)
class Capability:
    """기기 하나가 가진 능력 하나(능력 조회 결과)."""

    type: str
    access: str
    instance: str | None = None
    writable_fields: tuple[str, ...] = ()
    commands: tuple[str, ...] | None = None  # None이면 "알 수 없음"
    range: ValueRange | None = None
    field_ranges: dict[str, ValueRange] = field(default_factory=dict)
    values: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def key(self) -> CapKey:
        return (self.type, self.instance)

    @property
    def readable(self) -> bool:
        return "READ" in self.access

    @property
    def writable(self) -> bool:
        return "WRITE" in self.access

    def can_write(self, field_path: str | None = None) -> bool:
        """그 필드를 제어 요청에 넣을 수 있는가. 필드 없이 값 하나만 보내는 능력은 writable이면 된다."""
        if not self.writable:
            return False
        if field_path is None or not self.writable_fields:
            return True
        return any(
            field_path == f or field_path.startswith(f + ".") for f in self.writable_fields
        )

    def range_for(self, field_path: str) -> ValueRange | None:
        return self.field_ranges.get(field_path, self.range)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Capability:
        cmds = d.get("commands")
        return cls(
            type=d["type"],
            access=d.get("access", "READ"),
            instance=d.get("instance"),
            writable_fields=tuple(d.get("writableFields") or ()),
            commands=tuple(cmds) if isinstance(cmds, list) else None,
            range=ValueRange.from_api(d.get("range")),
            field_ranges={
                k: r
                for k, v in (d.get("fieldRanges") or {}).items()
                if (r := ValueRange.from_api(v)) is not None
            },
            values=tuple(d.get("values") or ()),
            raw=d,
        )


@dataclass(frozen=True, slots=True)
class CapabilityState:
    """상태 조회 `reported` 항목 하나(능력 하나의 값)."""

    type: str
    instance: str | None
    value: dict[str, Any]
    reported_at: datetime | None = None
    received_at: datetime | None = None
    field_received_at: dict[str, datetime] = field(default_factory=dict)
    unavailable: bool = False  # readStatus: UNAVAILABLE

    @property
    def key(self) -> CapKey:
        return (self.type, self.instance)

    def field_time(self, name: str) -> datetime | None:
        return self.field_received_at.get(name) or self.received_at

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> CapabilityState | None:
        cap_keys = [k for k in d if k not in _STATE_META]
        if len(cap_keys) != 1:
            return None  # 형식이 다르면 건너뛴다(진단에는 원본이 남는다)
        cap = cap_keys[0]
        value = d[cap] if isinstance(d[cap], dict) else {"value": d[cap]}
        return cls(
            type=cap,
            instance=d.get("instance"),
            value=value,
            reported_at=parse_time(d.get("reportedAt")),
            received_at=parse_time(d.get("receivedAt")),
            field_received_at={
                k: t
                for k, v in (d.get("fieldReceivedAt") or {}).items()
                if (t := parse_time(v)) is not None
            },
            unavailable=d.get("readStatus") == "UNAVAILABLE",
        )


@dataclass(frozen=True, slots=True)
class DeviceState:
    device_id: str
    capabilities: dict[CapKey, CapabilityState] = field(default_factory=dict)
    raw: list[dict[str, Any]] = field(default_factory=list, compare=False)

    def get(self, cap_type: str, instance: str | None = None) -> CapabilityState | None:
        return self.capabilities.get((cap_type, instance))

    @property
    def online(self) -> bool | None:
        s = self.get("onlineStatus")
        if s is None or s.unavailable:
            return None
        v = s.value.get("online")
        return v if isinstance(v, bool) else None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> DeviceState:
        reported = d.get("reported") or []
        caps: dict[CapKey, CapabilityState] = {}
        for item in reported:
            if isinstance(item, dict) and (s := CapabilityState.from_api(item)) is not None:
                caps[s.key] = s
        return cls(device_id=d["deviceId"], capabilities=caps, raw=reported)
