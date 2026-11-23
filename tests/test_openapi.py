from __future__ import annotations

import time
from urllib.parse import parse_qs

import httpx
import pytest

from custom_components.ttlock_selfhost.openapi import (
    VIA_BLUETOOTH,
    TtlockOpenApi,
    TtlockOpenApiError,
)

TOKEN = {"access_token": "old", "refresh_token": "ref", "expires_at": time.time() + 999}


def _api(handler, token=TOKEN, on_token=None) -> TtlockOpenApi:
    return TtlockOpenApi(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        client_id="cid",
        client_secret="sec",
        token=None if token is None else dict(token),
        on_token=on_token,
    )


def _fields(request: httpx.Request) -> dict[str, str]:
    raw = request.content.decode() or request.url.query.decode()
    return {name: values[0] for name, values in parse_qs(raw).items()}


async def test_login_sends_the_password_as_md5_and_keeps_the_token() -> None:
    seen = []

    def handler(request):
        seen.append(_fields(request))
        return httpx.Response(
            200,
            json={"access_token": "new", "refresh_token": "r2", "expires_in": 60},
        )

    stored = []
    api = _api(handler, token=None, on_token=stored.append)
    token = await api.async_login("user@example.com", "123456")
    assert seen[0]["password"] == "e10adc3949ba59abbe56e057f20f883e"
    assert seen[0]["clientSecret"] == "sec"
    assert token["access_token"] == "new"
    assert stored == [token]


async def test_login_without_a_token_in_the_answer_fails() -> None:
    api = _api(lambda _r: httpx.Response(200, json={}), token=None)
    with pytest.raises(TtlockOpenApiError):
        await api.async_login("u", "p")


async def test_a_call_without_a_session_is_refused() -> None:
    api = _api(lambda _r: httpx.Response(200, json={}), token=None)
    with pytest.raises(TtlockOpenApiError) as err:
        await api.async_locks()
    assert err.value.errcode == 10003


async def test_pages_are_read_until_the_last() -> None:
    def handler(request):
        page = int(_fields(request)["pageNo"])
        return httpx.Response(
            200, json={"list": [{"lockId": page}, "junk"], "pages": 2}
        )

    assert await _api(handler).async_locks() == [{"lockId": 1}, {"lockId": 2}]


async def test_a_dead_token_is_refreshed_once_and_the_call_repeated() -> None:
    calls = []

    def handler(request):
        fields = _fields(request)
        calls.append((request.url.path, fields.get("accessToken")))
        if request.url.path == "/oauth2/token":
            assert fields["grant_type"] == "refresh_token"
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 9})
        if fields["accessToken"] == "old":
            return httpx.Response(200, json={"errcode": 10004, "errmsg": "revoked"})
        return httpx.Response(200, json={"errcode": 0})

    await _api(handler).async_unlock(7)
    assert calls == [
        ("/v3/lock/unlock", "old"),
        ("/oauth2/token", None),
        ("/v3/lock/unlock", "fresh"),
    ]


async def test_an_expired_token_is_refreshed_before_the_call() -> None:
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"access_token": "fresh", "expires_in": 9})

    await _api(handler, token={**TOKEN, "expires_at": 0}).async_lock(7)
    assert paths == ["/oauth2/token", "/v3/lock/lock"]


async def test_a_refusal_carries_the_cloud_code() -> None:
    api = _api(
        lambda _r: httpx.Response(200, json={"errcode": -2012, "errmsg": "no gw"})
    )
    with pytest.raises(TtlockOpenApiError) as err:
        await api.async_lock(7)
    assert err.value.errcode == -2012
    assert "no gw" in str(err.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="nope"),
        httpx.Response(200, json=[]),
    ],
)
async def test_an_unusable_answer_has_no_code(response) -> None:
    with pytest.raises(TtlockOpenApiError) as err:
        await _api(lambda _r: response).async_lock(7)
    assert err.value.errcode is None


@pytest.mark.parametrize(("state", "locked"), [(0, True), (1, False), (2, None)])
async def test_open_state(state, locked) -> None:
    api = _api(lambda _r: httpx.Response(200, json={"state": state}))
    assert await api.async_open_state(7) is locked


async def test_lists_and_passcodes() -> None:
    seen = {}

    def handler(request):
        seen[request.url.path] = _fields(request)
        return httpx.Response(
            200,
            json={"list": [{"x": 1}], "keyboardPwdId": 5, "keyboardPwd": "112233"},
        )

    api = _api(handler)
    for call in (
        api.async_gateways_of,
        api.async_passcodes,
        api.async_cards,
        api.async_fingerprints,
        api.async_ekeys,
    ):
        assert await call(7) == [{"x": 1}]
    assert await api.async_records(7, since_ms=1) == [{"x": 1}]
    assert (
        await api.async_add_passcode(
            7, code="1234", name="n", start_ms=None, end_ms=None, via=VIA_BLUETOOTH
        )
        == 5
    )
    assert seen["/v3/keyboardPwd/add"]["keyboardPwdType"] == "2"
    assert seen["/v3/keyboardPwd/add"]["addType"] == "1"
    await api.async_add_passcode(7, code="1234", name="n", start_ms=None, end_ms=99)
    assert seen["/v3/keyboardPwd/add"]["keyboardPwdType"] == "3"
    assert seen["/v3/keyboardPwd/add"]["endDate"] == "99"
    assert (
        await api.async_random_passcode(7, name="n", kind=3, start_ms=1, end_ms=2)
        == "112233"
    )
    assert seen["/v3/keyboardPwd/get"]["endDate"] == "2"
    await api.async_random_passcode(7, name="n", kind=2, start_ms=1, end_ms=None)
    assert "endDate" not in seen["/v3/keyboardPwd/get"]
    await api.async_delete_passcode(7, 5)
    assert seen["/v3/keyboardPwd/delete"]["deleteType"] == "2"
