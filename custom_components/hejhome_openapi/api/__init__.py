"""헤이홈 Open API v3 클라이언트 (Home Assistant 비의존, 나중에 PyPI로 분리할 부분)."""

from .client import DEFAULT_BASE_URL, HejhomeClient
from .errors import (
    FieldProblem,
    HejhomeAuthError,
    HejhomeConnectionError,
    HejhomeDeviceOfflineError,
    HejhomeError,
    HejhomeForbiddenError,
    HejhomeNotFoundError,
    HejhomeNotReadyError,
    HejhomePermissionDeniedError,
    HejhomeRateLimitError,
    HejhomeRequestError,
    HejhomeServerError,
)
from .models import (
    Capability,
    CapabilityState,
    CapKey,
    Device,
    DeviceState,
    LinkedAccount,
    Space,
    ValueRange,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "CapKey",
    "Capability",
    "CapabilityState",
    "Device",
    "DeviceState",
    "FieldProblem",
    "HejhomeAuthError",
    "HejhomeClient",
    "HejhomeConnectionError",
    "HejhomeDeviceOfflineError",
    "HejhomeError",
    "HejhomeForbiddenError",
    "HejhomeNotFoundError",
    "HejhomeNotReadyError",
    "HejhomePermissionDeniedError",
    "HejhomeRateLimitError",
    "HejhomeRequestError",
    "HejhomeServerError",
    "LinkedAccount",
    "Space",
    "ValueRange",
]
