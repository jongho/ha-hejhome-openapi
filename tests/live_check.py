"""통합의 `api/` 클라이언트로 실제 API를 조회만 해 본다(제어 없음, HA·aiohttp 불필요).

    python3 -I tests/live_check.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from api_harness import UrllibSession, api, load_api_key  # noqa: E402


async def main() -> None:
    session = UrllibSession()
    c = api.HejhomeClient(session, load_api_key())

    accounts = await c.linked_accounts()
    print(f"연결 계정 {len(accounts)}개, 사용 가능 {sum(a.available for a in accounts)}개")
    homes = await c.spaces(space_type="HOME")
    spaces = await c.spaces()
    print(f"집 {len(homes)}곳: {', '.join(h.name for h in homes)} / 전체 장소 {len(spaces)}곳 "
          f"(방 {sum(s.type == 'ROOM' for s in spaces)}곳)")
    home = homes[0]
    devices = await c.devices(space_ids=[home.id])
    states = await c.states(space_ids=[home.id])
    print(f"'{home.name}' 기기 {len(devices)}대, 상태 {len(states)}대")
    for d in devices:
        caps = await c.capabilities(d.id)
        st = states.get(d.id)
        vals = {f"{k[0]}{'/' + k[1] if k[1] else ''}": v.value for k, v in (st.capabilities.items() if st else [])}
        print(f"  - {d.name}: 능력 {len(caps)}개 "
              f"(쓰기 {sum(x.writable for x in caps)}), 온라인={st.online if st else None}")
        print(f"      {vals}")
    try:
        await c.capabilities("does-not-exist")
    except api.HejhomeError as err:
        print(f"없는 기기 조회 → {type(err).__name__} ({err.status} {err.code})")
    ids = {d.id: f"device-{i}" for i, d in enumerate(devices, 1)}
    calls = sorted({next((c.replace(k, v) for k, v in ids.items() if k in c), c) for c in session.calls})
    print(f"호출 {c.request_count}회: {', '.join(calls)}")


if __name__ == "__main__":
    asyncio.run(main())
