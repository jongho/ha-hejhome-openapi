"""HA 없이 `api/` 패키지를 불러오고 HTTP를 흉내 내는 도구.

- `api/`는 `custom_components/hejhome_openapi/api`를 최상위 패키지 `api`로 불러온다
  (통합의 `__init__.py`는 homeassistant를 import하므로 건너뛴다).
- aiohttp가 설치돼 있지 않으면 클라이언트가 쓰는 이름만 담은 가짜 모듈을 끼운다.
- `FakeSession`: 정해 둔 응답을 돌려주고 받은 요청을 기록한다.
- `UrllibSession`: 실제 API를 urllib로 부른다(aiohttp 없이 실제 응답 확인용).
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import types
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "docs" / "samples"

try:
    import aiohttp  # noqa: F401
except ImportError:
    stub = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ContentTypeError(ClientError, ValueError):
        pass

    class ClientSession:  # 타입 표기용
        pass

    stub.ClientError = ClientError
    stub.ContentTypeError = ContentTypeError
    stub.ClientSession = ClientSession
    sys.modules["aiohttp"] = stub

sys.path.insert(0, str(ROOT / "custom_components" / "hejhome_openapi"))
import api  # noqa: E402

aiohttp = sys.modules["aiohttp"]


def sample(name: str) -> Any:
    return json.loads((SAMPLES / name).read_text())


class _Response:
    def __init__(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}
        self.content_length = None if body is None else len(json.dumps(body))

    async def json(self, content_type: Any = None) -> Any:
        return self._body

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakeSession:
    """routes: {(method, path): [응답, …]} — 응답은 (status, body[, headers]). 목록이면 차례로."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = {k: list(v) if isinstance(v, list) else [v] for k, v in routes.items()}
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, *, params=None, json=None, headers=None):
        path = urllib.parse.urlsplit(url).path
        self.calls.append(
            {"method": method, "path": path, "params": params or [], "json": json, "headers": headers}
        )
        queue = self.routes.get((method, path))
        if not queue:
            return _Response(404, {"status": 404, "title": "Not Found"})
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return _Response(*item)


class UrllibSession:
    """aiohttp 세션처럼 보이는 urllib 래퍼(실제 호출 확인용, 읽기 전용으로만 쓴다)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def request(self, method: str, url: str, *, params=None, json=None, headers=None):
        session = self

        class _Ctx:
            async def __aenter__(self_inner):
                q = urllib.parse.urlencode(params or [])
                full = url + (f"?{q}" if q else "")
                session.calls.append(f"{method} {urllib.parse.urlsplit(full).path}")
                data = None if json is None else __import__("json").dumps(json).encode()
                req = urllib.request.Request(full, data=data, method=method, headers=dict(headers or {}))
                if data is not None:
                    req.add_header("Content-Type", "application/json")

                def _do():
                    try:
                        with urllib.request.urlopen(req, timeout=20) as r:
                            raw = r.read()
                            return r.status, raw, dict(r.headers)
                    except urllib.error.HTTPError as e:
                        return e.code, e.read(), dict(e.headers)

                status, raw, hdrs = await asyncio.to_thread(_do)
                body = __import__("json").loads(raw) if raw.strip() else None
                return _Response(status, body, hdrs)

            async def __aexit__(self_inner, *exc):
                return None

        return _Ctx()


def load_api_key(path: pathlib.Path = ROOT / "api-key.env") -> str:
    for line in path.read_text().splitlines():
        if line.startswith("HEJHOME_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{path}에 HEJHOME_API_KEY가 없습니다")
