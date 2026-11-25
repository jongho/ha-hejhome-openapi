"""설정 흐름: API 키 → 집 선택 / 재인증 / 재설정 / 옵션 (design.md 10절)."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import HejhomeConfigEntry
from .api import (
    HejhomeAuthError,
    HejhomeClient,
    HejhomeConnectionError,
    HejhomeError,
    HejhomeForbiddenError,
    HejhomeRateLimitError,
    Space,
)
from .const import (
    CONF_LINKED_ACCOUNT_ID,
    CONF_REFRESH_HOURS,
    CONF_SCAN_INTERVAL,
    CONF_SPACE_ID,
    DEFAULT_REFRESH_HOURS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_REFRESH_HOURS,
    MAX_SCAN_INTERVAL,
    MIN_REFRESH_HOURS,
    MIN_SCAN_INTERVAL,
    PORTAL_URL,
)

_LOGGER = logging.getLogger(__name__)

KEY_SCHEMA = vol.Schema(
    {vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)


class _NoHome(Exception):
    """연결 계정은 있는데 집이 없다."""


async def _homes(client: HejhomeClient) -> list[Space]:
    """키를 검사하고, 쓸 수 있는 연결 계정의 집 목록을 돌려준다. 오류는 errors 키로 바꾼다."""
    accounts = await client.linked_accounts()
    if not accounts:
        raise _NoHome("no_linked_account")
    available = {a.id for a in accounts if a.available}
    if not available:
        raise _NoHome("account_unavailable")
    homes = [s for s in await client.spaces(space_type="HOME") if s.linked_account_id in available]
    if not homes:
        raise _NoHome("no_home")
    return homes


def _error_key(err: Exception) -> str:
    if isinstance(err, _NoHome):
        return str(err)
    if isinstance(err, HejhomeAuthError):
        return "invalid_auth"
    if isinstance(err, HejhomeForbiddenError):
        return "ip_not_allowed" if err.code == "API_KEY_IP_NOT_ALLOWED" else "organization_inactive"
    if isinstance(err, HejhomeRateLimitError):
        return "rate_limited"
    if isinstance(err, (HejhomeConnectionError, HejhomeError)):
        return "cannot_connect"
    _LOGGER.exception("설정 중 예상하지 못한 오류")
    return "unknown"


class HejhomeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._homes: dict[str, Space] = {}

    async def _check(self, api_key: str) -> tuple[list[Space], dict[str, str]]:
        client = HejhomeClient(async_get_clientsession(self.hass), api_key)
        try:
            return await _homes(client), {}
        except Exception as err:  # noqa: BLE001 - 사용자에게 보여 줄 오류 키로 바꾼다
            return [], {"base": _error_key(err)}

    # ── 처음 설정 ───────────────────────────────────────

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            homes, errors = await self._check(api_key)
            if not errors:
                configured = {e.unique_id for e in self._async_current_entries()}
                self._api_key = api_key
                self._homes = {h.id: h for h in homes if h.id not in configured}
                if not self._homes:
                    return self.async_abort(reason="already_configured")
                if len(self._homes) == 1:
                    return await self._create(next(iter(self._homes.values())))
                return await self.async_step_space()
        return self.async_show_form(
            step_id="user",
            data_schema=KEY_SCHEMA,
            errors=errors,
            description_placeholders={"portal_url": PORTAL_URL},
        )

    async def async_step_space(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._create(self._homes[user_input[CONF_SPACE_ID]])
        options = [SelectOptionDict(value=h.id, label=h.name) for h in self._homes.values()]
        return self.async_show_form(
            step_id="space",
            data_schema=vol.Schema(
                {vol.Required(CONF_SPACE_ID): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    async def _create(self, home: Space) -> ConfigFlowResult:
        await self.async_set_unique_id(home.id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=home.name,
            data={
                CONF_API_KEY: self._api_key,
                CONF_SPACE_ID: home.id,
                CONF_LINKED_ACCOUNT_ID: home.linked_account_id,
            },
        )

    # ── 재인증 · 재설정 (키 바꾸기) ─────────────────────────

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._replace_key("reauth_confirm", self._get_reauth_entry(), user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._replace_key("reconfigure", self._get_reconfigure_entry(), user_input)

    async def _replace_key(
        self, step_id: str, entry: HejhomeConfigEntry, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            homes, errors = await self._check(api_key)
            if not errors:
                home = next((h for h in homes if h.id == entry.unique_id), None)
                if home is None:
                    errors["base"] = "wrong_home"
                else:
                    await self.async_set_unique_id(home.id)
                    self._abort_if_unique_id_mismatch(reason="wrong_home")
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_API_KEY: api_key,
                            CONF_LINKED_ACCOUNT_ID: home.linked_account_id,
                        },
                    )
        return self.async_show_form(
            step_id=step_id,
            data_schema=KEY_SCHEMA,
            errors=errors,
            description_placeholders={"title": entry.title, "portal_url": PORTAL_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: HejhomeConfigEntry) -> HejhomeOptionsFlow:
        return HejhomeOptionsFlow()


class HejhomeOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_REFRESH_HOURS: int(user_input[CONF_REFRESH_HOURS]),
                }
            )
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_REFRESH_HOURS,
                    default=opts.get(CONF_REFRESH_HOURS, DEFAULT_REFRESH_HOURS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_REFRESH_HOURS,
                        max=MAX_REFRESH_HOURS,
                        step=1,
                        unit_of_measurement="h",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
