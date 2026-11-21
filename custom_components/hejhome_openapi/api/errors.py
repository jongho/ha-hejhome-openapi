"""헤이홈 Open API 오류 → 예외.

응답 본문은 RFC 9457 Problem Details(`code`, `detail`, `errors[]`)다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FieldProblem:
    """400 INVALID_ARGUMENT의 고칠 위치 하나."""

    code: str
    pointer: str | None = None
    parameter: str | None = None
    detail: str | None = None


class HejhomeError(Exception):
    """모든 헤이홈 API 오류의 기반."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        detail: str | None = None,
        problems: tuple[FieldProblem, ...] = (),
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail
        self.problems = problems


class HejhomeConnectionError(HejhomeError):
    """네트워크 오류나 시간 초과. 응답을 받지 못했다."""


class HejhomeAuthError(HejhomeError):
    """401: 키가 틀렸거나 폐기됐다."""


class HejhomeForbiddenError(HejhomeError):
    """403 API_KEY_IP_NOT_ALLOWED·ORGANIZATION_INACTIVE: 키·조직 단위 거부."""


class HejhomePermissionDeniedError(HejhomeError):
    """403 PERMISSION_DENIED: 그 장소·기기에 권한이 없다(소유자가 아니거나 없어짐)."""


class HejhomeNotFoundError(HejhomeError):
    """404: 지원 목록에 없는 기기이거나 없는 자원."""


class HejhomeRequestError(HejhomeError):
    """400·415·422: 요청이 잘못됐다(범위 밖 값, 지원하지 않는 필드 등)."""


class HejhomeNotReadyError(HejhomeError):
    """409 ABORTED·DEVICE_NOT_READY: 상태를 다시 읽거나 기다렸다 보내야 한다."""


class HejhomeRateLimitError(HejhomeError):
    """429: 호출 한도 초과."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class HejhomeServerError(HejhomeError):
    """5xx: 서버나 기기 쪽 일시 오류."""


class HejhomeDeviceOfflineError(HejhomeServerError):
    """503 DEVICE_OFFLINE."""


FORBIDDEN_CODES = {"API_KEY_IP_NOT_ALLOWED", "ORGANIZATION_INACTIVE"}


@dataclass(slots=True)
class _Problem:
    code: str | None = None
    detail: str | None = None
    title: str | None = None
    problems: tuple[FieldProblem, ...] = field(default_factory=tuple)


def _parse_problem(body: Any) -> _Problem:
    if not isinstance(body, dict):
        return _Problem()
    problems = tuple(
        FieldProblem(
            code=str(e.get("code", "")),
            pointer=e.get("pointer"),
            parameter=e.get("parameter"),
            detail=e.get("detail"),
        )
        for e in body.get("errors") or ()
        if isinstance(e, dict)
    )
    return _Problem(body.get("code"), body.get("detail"), body.get("title"), problems)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP 날짜 형식은 쓰지 않고 기본 물러서기를 따른다


def error_from_response(
    status: int, body: Any, *, retry_after: str | None = None, path: str = ""
) -> HejhomeError:
    """HTTP 상태와 본문으로 알맞은 예외를 만든다."""
    p = _parse_problem(body)
    message = f"{path} → {status}" + (f" {p.code}" if p.code else "") + (
        f": {p.detail}" if p.detail else ""
    )
    kw: dict[str, Any] = {
        "status": status,
        "code": p.code,
        "detail": p.detail,
        "problems": p.problems,
    }
    if status == 401:
        return HejhomeAuthError(message, **kw)
    if status == 403:
        if p.code in FORBIDDEN_CODES:
            return HejhomeForbiddenError(message, **kw)
        return HejhomePermissionDeniedError(message, **kw)
    if status == 404:
        return HejhomeNotFoundError(message, **kw)
    if status == 409:
        return HejhomeNotReadyError(message, **kw)
    if status == 429:
        return HejhomeRateLimitError(message, retry_after=_parse_retry_after(retry_after), **kw)
    if status == 503 and p.code == "DEVICE_OFFLINE":
        return HejhomeDeviceOfflineError(message, **kw)
    if status >= 500:
        return HejhomeServerError(message, **kw)
    return HejhomeRequestError(message, **kw)
