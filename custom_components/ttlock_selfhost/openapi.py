"""
TTLock Open API client: the route to a lock through its gateway.

The gateway only talks to TTLock's cloud, so this is the one part of the
integration that leaves the house. It signs in with the app account and
the developer application's `client_id`/`client_secret`, and every call
carries the access token, refreshed once when the cloud rejects it.
"""

from __future__ import annotations

import time
from hashlib import md5
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

import httpx

from .const import LOGGER

if TYPE_CHECKING:
    from collections.abc import Callable

REGIONS: dict[str, str] = {
    "eu": "https://euapi.ttlock.com",
    "cn": "https://cnapi.ttlock.com",
}
DEFAULT_REGION = "eu"
ERR_TOKEN = frozenset({10003, 10004})
ERR_NO_GATEWAY = -2012
ERR_REMOTE_UNLOCK_OFF = -4043
PAGE_SIZE = 100
MAX_PAGES = 10
REQUEST_TIMEOUT_SECONDS = 20.0
VIA_GATEWAY = 2
VIA_BLUETOOTH = 1

type Json = dict[str, object]


class TtlockBleGatewayToken(TypedDict):
    """The Open API session kept on the config entry."""

    access_token: str
    refresh_token: str
    expires_at: float


class TtlockBleGatewayConfig(TypedDict):
    """What the config entry stores to reach the gateway route."""

    client_id: str
    client_secret: str
    region: str
    token: TtlockBleGatewayToken
    username: NotRequired[str]


class TtlockOpenApiError(Exception):
    """The cloud refused a call, or could not be reached (`errcode` is None)."""

    def __init__(self, message: str, errcode: int | None = None) -> None:
        """Keep the cloud's error code next to its message."""
        super().__init__(message)
        self.errcode = errcode


class TtlockOpenApi:
    """Async client for the calls this integration makes."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        client: httpx.AsyncClient,
        client_id: str,
        client_secret: str,
        region: str = DEFAULT_REGION,
        token: TtlockBleGatewayToken | None = None,
        on_token: Callable[[TtlockBleGatewayToken], None] | None = None,
    ) -> None:
        """Bind to an HA-managed `httpx.AsyncClient` and one developer application."""
        self._client = client
        self._client_id = client_id
        self._client_secret = client_secret
        self._base = REGIONS.get(region, REGIONS[DEFAULT_REGION])
        self._token = token
        self._on_token = on_token

    async def async_login(self, username: str, password: str) -> TtlockBleGatewayToken:
        """Sign in with the app account; the password travels as its MD5."""
        return await self._async_token(
            username=username,
            # The Open API defines the password field as an MD5 digest.
            password=md5(password.encode(), usedforsecurity=False).hexdigest(),
        )

    async def async_locks(self) -> list[Json]:
        """Return the locks this account administers."""
        return await self._async_pages("/v3/lock/list")

    async def async_lock(self, lock_id: int) -> None:
        """Lock through the gateway."""
        await self._async_call("POST", "/v3/lock/lock", lockId=lock_id)

    async def async_unlock(self, lock_id: int) -> None:
        """Unlock through the gateway."""
        await self._async_call("POST", "/v3/lock/unlock", lockId=lock_id)

    async def async_open_state(self, lock_id: int) -> bool | None:
        """Read the bolt through the gateway: True locked, None unknown."""
        reply = await self._async_call("GET", "/v3/lock/queryOpenState", lockId=lock_id)
        state = reply.get("state")
        if state == 0:
            return True
        return False if state == 1 else None

    async def async_gateways_of(self, lock_id: int) -> list[Json]:
        """Return the gateways that hear this lock."""
        reply = await self._async_call("GET", "/v3/gateway/listByLock", lockId=lock_id)
        return _rows(reply)

    async def async_records(self, lock_id: int, *, since_ms: int) -> list[Json]:
        """Return the records the cloud holds for a lock since `since_ms`."""
        return await self._async_pages(
            "/v3/lockRecord/list",
            pages=2,
            lockId=lock_id,
            startDate=since_ms,
        )

    async def async_passcodes(self, lock_id: int) -> list[Json]:
        """Return the passcodes the cloud knows for a lock."""
        return await self._async_pages(
            "/v3/lock/listKeyboardPwd", lockId=lock_id, orderBy=1
        )

    async def async_add_passcode(  # noqa: PLR0913
        self,
        lock_id: int,
        *,
        code: str,
        name: str,
        start_ms: int | None,
        end_ms: int | None,
        via: int = VIA_GATEWAY,
    ) -> int | None:
        """Write a custom passcode through the gateway, or record one sent by BLE."""
        params: dict[str, object] = {
            "lockId": lock_id,
            "keyboardPwd": code,
            "keyboardPwdName": name,
            "keyboardPwdType": 2 if end_ms is None else 3,
            "addType": via,
        }
        if end_ms is not None:
            params["startDate"] = start_ms or int(time.time() * 1000)
            params["endDate"] = end_ms
        reply = await self._async_call("POST", "/v3/keyboardPwd/add", **params)
        return cast("int | None", reply.get("keyboardPwdId"))

    async def async_random_passcode(
        self,
        lock_id: int,
        *,
        name: str,
        kind: int,
        start_ms: int,
        end_ms: int | None,
    ) -> str:
        """Ask the cloud for a generated passcode; this needs no gateway."""
        params: dict[str, object] = {
            "lockId": lock_id,
            "keyboardPwdType": kind,
            "keyboardPwdName": name,
            "startDate": start_ms,
        }
        if end_ms is not None:
            params["endDate"] = end_ms
        reply = await self._async_call("POST", "/v3/keyboardPwd/get", **params)
        return str(reply.get("keyboardPwd") or "")

    async def async_delete_passcode(
        self, lock_id: int, passcode_id: int, *, via: int = VIA_GATEWAY
    ) -> None:
        """Remove a passcode through the gateway, or record a BLE removal."""
        await self._async_call(
            "POST",
            "/v3/keyboardPwd/delete",
            lockId=lock_id,
            keyboardPwdId=passcode_id,
            deleteType=via,
        )

    async def async_cards(self, lock_id: int) -> list[Json]:
        """Return the cards the cloud knows for a lock."""
        return await self._async_pages(
            "/v3/identityCard/list", lockId=lock_id, orderBy=1
        )

    async def async_fingerprints(self, lock_id: int) -> list[Json]:
        """Return the fingerprints the cloud knows for a lock."""
        return await self._async_pages(
            "/v3/fingerprint/list", lockId=lock_id, orderBy=1
        )

    async def async_ekeys(self, lock_id: int) -> list[Json]:
        """Return the eKeys shared for a lock."""
        return await self._async_pages("/v3/lock/listKey", lockId=lock_id, orderBy=1)

    async def _async_pages(
        self, path: str, *, pages: int = MAX_PAGES, **params: object
    ) -> list[Json]:
        rows: list[Json] = []
        for page in range(1, pages + 1):
            reply = await self._async_call(
                "GET", path, pageNo=page, pageSize=PAGE_SIZE, **params
            )
            rows.extend(_rows(reply))
            if page >= cast("int", reply.get("pages") or 1):
                break
        return rows

    async def _async_call(self, method: str, path: str, **params: object) -> Json:
        """Make one authenticated call, signing in again once if the token died."""
        if self._token is None:
            msg = "Not signed in to the TTLock Open API"
            raise TtlockOpenApiError(msg, 10003)
        if self._token["expires_at"] <= time.time():
            await self._async_refresh()
        try:
            return await self._async_send(method, path, params)
        except TtlockOpenApiError as exc:
            if exc.errcode not in ERR_TOKEN:
                raise
        await self._async_refresh()
        return await self._async_send(method, path, params)

    async def _async_send(
        self, method: str, path: str, params: dict[str, object]
    ) -> Json:
        token = cast("TtlockBleGatewayToken", self._token)
        fields = {
            **{name: str(value) for name, value in params.items()},
            "clientId": self._client_id,
            "accessToken": token["access_token"],
            "date": str(int(time.time() * 1000)),
        }
        if method == "GET":
            return await self._async_request(path, params=fields)
        return await self._async_request(path, data=fields)

    async def _async_refresh(self) -> None:
        token = cast("TtlockBleGatewayToken", self._token)
        await self._async_token(
            grant_type="refresh_token", refresh_token=token["refresh_token"]
        )

    async def _async_token(self, **fields: str) -> TtlockBleGatewayToken:
        reply = await self._async_request(
            "/oauth2/token",
            data={
                **fields,
                "clientId": self._client_id,
                "clientSecret": self._client_secret,
            },
        )
        access = reply.get("access_token")
        if not isinstance(access, str):
            msg = "The TTLock cloud answered the sign-in without a token"
            raise TtlockOpenApiError(msg)
        previous = self._token["refresh_token"] if self._token else ""
        self._token = {
            "access_token": access,
            "refresh_token": str(reply.get("refresh_token") or previous),
            "expires_at": time.time() + float(cast("int", reply.get("expires_in", 0))),
        }
        if self._on_token is not None:
            self._on_token(self._token)
        return self._token

    async def _async_request(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> Json:
        try:
            response = await self._client.request(
                "GET" if data is None else "POST",
                f"{self._base}{path}",
                params=params,
                data=data,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            reply = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            msg = f"Could not reach the TTLock cloud: {type(exc).__name__}"
            raise TtlockOpenApiError(msg) from exc
        if not isinstance(reply, dict):
            msg = "The TTLock cloud sent an answer that is not an object"
            raise TtlockOpenApiError(msg)
        errcode = reply.get("errcode")
        if errcode:
            message = str(reply.get("errmsg") or reply.get("description") or errcode)
            LOGGER.debug("Open API %s refused: %s (%s)", path, message, errcode)
            raise TtlockOpenApiError(message, cast("int", errcode))
        return cast("Json", reply)


def _rows(reply: Json) -> list[Json]:
    rows = reply.get("list")
    return (
        [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    )
