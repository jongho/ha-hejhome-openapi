"""상수."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "hejhome_openapi"
MANUFACTURER: Final = "Hejhome (GoQual)"

CONF_SPACE_ID: Final = "space_id"
CONF_LINKED_ACCOUNT_ID: Final = "linked_account_id"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_REFRESH_HOURS: Final = "device_refresh_hours"

# 폴링 간격: 기본이자 최소 30초 (design.md 7절)
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 300
DEFAULT_SCAN_INTERVAL: Final = 30

# 기기 목록·능력 다시 받는 간격
DEFAULT_REFRESH_HOURS: Final = 6
MIN_REFRESH_HOURS: Final = 1
MAX_REFRESH_HOURS: Final = 48

# 429 물러서기: 30초부터 두 배씩, 최대 10분
BACKOFF_START: Final = 30.0
BACKOFF_MAX: Final = 600.0

# 연속 실패 몇 번까지 이전 데이터를 유지할지
MAX_SILENT_POLL_FAILURES: Final = 3

# 제어 뒤 다시 조회하기까지, 낙관적 값을 유지하는 최대 시간
REFRESH_AFTER_CONTROL: Final = timedelta(seconds=2)
OPTIMISTIC_TIMEOUT: Final = timedelta(seconds=10)

# 플러그·멀티탭 이름으로 switch device_class를 outlet으로 (모델명이 API에 없다)
OUTLET_NAME_HINTS: Final = ("플러그", "멀티탭", "plug", "outlet", "power strip")
