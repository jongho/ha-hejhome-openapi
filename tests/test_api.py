"""`api/` 패키지 단위 테스트 (표준 라이브러리만 사용, HA 불필요).

    python3 -I tests/test_api.py
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from api_harness import FakeSession, aiohttp, api, sample  # noqa: E402

PREFIX = "/v3"


def client(routes):
    session = FakeSession(routes)
    return api.HejhomeClient(session, "test-key"), session


class ModelTests(unittest.TestCase):
    def test_parse_samples(self):
        states = sample("devices-states.json")["items"]
        parsed = {s.device_id: s for s in (api.DeviceState.from_api(d) for d in states)}
        thermo = parsed["device-2"]
        self.assertEqual(thermo.get("temperatureSensor").value, {"celsius": 20.1})
        self.assertEqual(thermo.get("humiditySensor").value["percent"], 39.7)
        self.assertTrue(thermo.online)
        t = thermo.get("battery").field_time("percent")
        self.assertIsNotNone(t)
        self.assertIsNotNone(t.tzinfo)
        bulb = parsed["device-3"]
        self.assertIsNone(bulb.get("brightness"))  # 보고하지 않은 능력
        self.assertEqual(bulb.get("onOff").value, {"on": False})

    def test_capabilities(self):
        caps = [api.Capability.from_api(c) for c in sample("capabilities.json")["device-3"]["capabilities"]]
        by = {c.key: c for c in caps}
        mode = by[("mode", "run_mode")]
        self.assertEqual(mode.values, ("white", "color", "scene", "music"))
        self.assertTrue(mode.can_write("current"))
        ct = by[("colorTemperature", None)]
        self.assertEqual((ct.range.min, ct.range.max), (3000.0, 9000.0))
        color = by[("colorSetting", None)]
        self.assertTrue(color.can_write("hsv.hue"))  # 묶음 이름(hsv)만 있어도 하위 필드 가능
        self.assertEqual(color.range_for("hsv.hue").max, 360.0)
        trans = by[("onOffTransition", None)]
        self.assertFalse(trans.writable)
        sul = by[("startUpLight", None)]
        # writableFields가 ["behavior", "light"]면 light 묶음 아래 필드도 보낼 수 있다
        self.assertTrue(sul.can_write("light.mode"))
        self.assertFalse(sul.can_write("other"))

    def test_state_unknown_capability_kept(self):
        s = api.DeviceState.from_api(
            {"deviceId": "d", "reported": [{"newThing": {"x": 1}, "reportedAt": "2026-11-21T00:00:00+09:00"}]}
        )
        self.assertEqual(s.get("newThing").value, {"x": 1})

    def test_unavailable_flag(self):
        s = api.DeviceState.from_api(
            {"deviceId": "d", "reported": [{"onlineStatus": {"online": True}, "readStatus": "UNAVAILABLE"}]}
        )
        self.assertTrue(s.get("onlineStatus").unavailable)
        self.assertIsNone(s.online)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_pagination_and_key_header(self):
        c, s = client(
            {
                ("GET", f"{PREFIX}/devices"): [
                    (200, {"items": [{"id": "a", "name": "A", "linkedAccountId": "x"}], "page": {"nextPageToken": "t1"}}),
                    (200, {"items": [{"id": "b", "name": "B", "linkedAccountId": "x", "connection": "IR"}], "page": {}}),
                ]
            }
        )
        devices = await c.devices(space_ids=["home_1"])
        self.assertEqual([d.id for d in devices], ["a", "b"])
        self.assertEqual(devices[1].connection, "IR")
        self.assertEqual(s.calls[0]["headers"]["X-API-Key"], "test-key")
        self.assertIn(("spaceId", "home_1"), s.calls[1]["params"])  # 조건은 페이지마다 같게
        self.assertIn(("pageToken", "t1"), s.calls[1]["params"])
        self.assertNotIn("pageToken", dict(s.calls[0]["params"]))

    async def test_states_from_samples(self):
        c, _ = client({("GET", f"{PREFIX}/devices/states"): (200, sample("devices-states.json"))})
        states = await c.states()
        self.assertEqual(set(states), {"device-1", "device-2", "device-3"})
        self.assertFalse(states["device-1"].get("motionSensor").value["detected"])

    async def test_control_body_and_202(self):
        c, s = client({("POST", f"{PREFIX}/devices/a%2Fb/control"): (202, None)})
        await c.control("a/b", [{"onOff": {"on": True}, "instance": "2"}])
        self.assertEqual(s.calls[0]["json"], {"desired": [{"onOff": {"on": True}, "instance": "2"}]})

    async def test_command_body(self):
        c, s = client({("POST", f"{PREFIX}/devices/ir1/commands"): (202, None)})
        await c.command("ir1", "irKey", "SEND", arguments={"key": "power"})
        self.assertEqual(
            s.calls[0]["json"], {"capability": "irKey", "command": "SEND", "arguments": {"key": "power"}}
        )

    async def _raises(self, status, body, exc, headers=None):
        c, _ = client({("GET", f"{PREFIX}/linked-accounts"): (status, body, headers or {})})
        with self.assertRaises(exc) as ctx:
            await c.linked_accounts()
        return ctx.exception

    async def test_errors(self):
        await self._raises(401, {"status": 401, "title": "Unauthorized"}, api.HejhomeAuthError)
        e = await self._raises(403, {"status": 403, "code": "API_KEY_IP_NOT_ALLOWED"}, api.HejhomeForbiddenError)
        self.assertEqual(e.code, "API_KEY_IP_NOT_ALLOWED")
        await self._raises(403, {"status": 403, "code": "ORGANIZATION_INACTIVE"}, api.HejhomeForbiddenError)
        await self._raises(403, {"status": 403, "code": "PERMISSION_DENIED"}, api.HejhomePermissionDeniedError)
        await self._raises(404, {"status": 404, "code": "DEVICE_NOT_FOUND"}, api.HejhomeNotFoundError)
        await self._raises(409, {"status": 409, "code": "ABORTED"}, api.HejhomeNotReadyError)
        e = await self._raises(429, {"status": 429}, api.HejhomeRateLimitError, {"Retry-After": "12"})
        self.assertEqual(e.retry_after, 12.0)
        e = await self._raises(429, None, api.HejhomeRateLimitError)
        self.assertIsNone(e.retry_after)
        e = await self._raises(503, {"status": 503, "code": "DEVICE_OFFLINE"}, api.HejhomeDeviceOfflineError)
        self.assertIsInstance(e, api.HejhomeServerError)
        await self._raises(500, {"status": 500, "code": "INTERNAL_ERROR"}, api.HejhomeServerError)
        e = await self._raises(
            400,
            {
                "status": 400,
                "code": "INVALID_ARGUMENT",
                "detail": "bad",
                "errors": [{"code": "VALUE_OUT_OF_RANGE", "pointer": "/desired/0/brightness/percent", "detail": "Allowed range: 0 to 100."}],
            },
            api.HejhomeRequestError,
        )
        self.assertEqual(e.problems[0].pointer, "/desired/0/brightness/percent")
        await self._raises(422, {"status": 422, "code": "NOT_SUPPORTED"}, api.HejhomeRequestError)

    async def test_connection_error(self):
        c, _ = client({("GET", f"{PREFIX}/spaces"): aiohttp.ClientError("boom")})
        with self.assertRaises(api.HejhomeConnectionError):
            await c.spaces()

    async def test_timeout(self):
        c, _ = client({("GET", f"{PREFIX}/spaces"): TimeoutError()})
        with self.assertRaises(api.HejhomeConnectionError):
            await c.spaces()

    async def test_spaces_filter(self):
        c, s = client({("GET", f"{PREFIX}/spaces"): (200, sample("spaces.json"))})
        homes = await c.spaces(space_type="HOME")
        self.assertEqual(homes[0].type, "HOME")
        self.assertIn(("type", "HOME"), s.calls[0]["params"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
