"""헤이홈 Open API v3 비동기 클라이언트.

Home Assistant에 의존하지 않는다. aiohttp 세션은 밖에서 받는다(HA에서는 공용 세션).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

import aiohttp

from .errors import HejhomeConnectionError, HejhomeError, error_from_response
from .models import Capability, Device, DeviceState, LinkedAccount, Space

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openapi.goqual.com"
DEFAULT_TIMEOUT = 20
PAGE_SIZE = 100


def _q(device_id: str) -> str:
    return quote(device_id, safe="")


class HejhomeClient:
    """엔드포인트별 메서드. 목록 API는 페이지를 끝까지 이어 받는다."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self.request_count = 0  # 진단용(호출 수)

    # ── 저수준 ──────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        json: Any = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = {"X-API-Key": self._api_key, "Accept": "application/json"}
        self.request_count += 1
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.request(
                    method, url, params=params, json=json, headers=headers
                ) as resp:
                    if resp.status == 204 or (resp.status == 202 and not resp.content_length):
                        return None
                    try:
                        body = await resp.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError):
                        body = None
                    if resp.status >= 400:
                        raise error_from_response(
                            resp.status,
                            body,
                            retry_after=resp.headers.get("Retry-After"),
                            path=f"{method} {path}",
                        )
                    return body
        except HejhomeError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise HejhomeConnectionError(f"{method} {path}: {err!r}") from err

    async def _list(self, path: str, params: list[tuple[str, str]] | None = None) -> list[dict]:
        """`page.nextPageToken`이 없을 때까지 이어 받는다. 조건(params)은 페이지마다 같게."""
        items: list[dict] = []
        token: str | None = None
        while True:
            p = list(params or []) + [("pageSize", str(PAGE_SIZE))]
            if token:
                p.append(("pageToken", token))
            body = await self._request("GET", path, params=p) or {}
            items.extend(body.get("items") or [])
            token = (body.get("page") or {}).get("nextPageToken")
            if not token:
                return items

    # ── 조회 ────────────────────────────────────────────

    async def linked_accounts(self) -> list[LinkedAccount]:
        return [LinkedAccount.from_api(d) for d in await self._list("/v3/linked-accounts")]

    async def spaces(
        self, *, space_type: str | None = None, linked_account_id: str | None = None
    ) -> list[Space]:
        params: list[tuple[str, str]] = []
        if space_type:
            params.append(("type", space_type))
        if linked_account_id:
            params.append(("linkedAccountId", linked_account_id))
        return [Space.from_api(d) for d in await self._list("/v3/spaces", params)]

    async def devices(self, *, space_ids: Sequence[str] = ()) -> list[Device]:
        params = [("spaceId", s) for s in space_ids]
        return [Device.from_api(d) for d in await self._list("/v3/devices", params)]

    async def capabilities(self, device_id: str) -> list[Capability]:
        body = await self._request("GET", f"/v3/devices/{_q(device_id)}/capabilities") or {}
        return [Capability.from_api(c) for c in body.get("capabilities") or []]

    async def states(self, *, space_ids: Sequence[str] = ()) -> dict[str, DeviceState]:
        params = [("spaceId", s) for s in space_ids]
        items = await self._list("/v3/devices/states", params)
        return {s.device_id: s for s in (DeviceState.from_api(d) for d in items)}

    async def state(self, device_id: str) -> DeviceState:
        body = await self._request("GET", f"/v3/devices/{_q(device_id)}/state")
        return DeviceState.from_api(body)

    # ── 제어 ────────────────────────────────────────────

    async def control(self, device_id: str, desired: list[dict[str, Any]]) -> None:
        """상태 바꾸기. 202면 접수된 것이고 결과는 상태 조회로 확인한다. 자동 재시도는 하지 않는다."""
        if not desired:
            raise ValueError("desired is empty")
        await self._request(
            "POST", f"/v3/devices/{_q(device_id)}/control", json={"desired": desired}
        )

    async def command(
        self,
        device_id: str,
        capability: str,
        command: str,
        *,
        instance: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        """일회성 동작(RESET, SELF_TEST, irKey SEND 등)."""
        body: dict[str, Any] = {"capability": capability, "command": command}
        if instance is not None:
            body["instance"] = instance
        if arguments:
            body["arguments"] = arguments
        await self._request("POST", f"/v3/devices/{_q(device_id)}/commands", json=body)
