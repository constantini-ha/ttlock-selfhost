from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.ttlock_selfhost.cloud_push import callback_path
from custom_components.ttlock_selfhost.const import CONF_GATEWAY, CONF_ROUTE
from custom_components.ttlock_selfhost.history_store import async_get_history_store
from custom_components.ttlock_selfhost.openapi import TtlockOpenApiError
from ttlock_ble import TTLockError

MAC = "AA:BB:CC:DD:EE:FF"


async def _ask(hass, hass_ws_client, command, **fields):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"ttlock_selfhost/{command}", **fields})
    return await client.receive_json()


async def test_locks_describe_both_routes(
    hass, hass_ws_client, gateway_entry, sample_virtual_key
) -> None:
    entry = await gateway_entry()
    reply = await _ask(hass, hass_ws_client, "locks")
    (lock,) = reply["result"]
    mac = sample_virtual_key.lockMac
    assert lock["mac"] == mac
    assert lock["entry_id"] == entry.entry_id
    assert lock["locked"] is True
    assert lock["battery"] == 55
    assert lock["route"] == "auto"
    assert lock["gateway"] == {
        "configured": True,
        "has_gateway": True,
        "gateways": [{"name": "G2", "rssi": -60}],
        "error": None,
        "callback": {
            "url": None,
            "path": callback_path(entry),
            "received_at": None,
        },
    }
    assert lock["entities"]["lock"].startswith("lock.")
    assert lock["account"] == "user@example.com"


async def test_locks_without_a_gateway(hass, hass_ws_client, setup_integration) -> None:
    reply = await _ask(hass, hass_ws_client, "locks")
    assert reply["result"][0]["gateway"]["configured"] is False


async def test_unknown_lock_is_refused(hass, hass_ws_client, setup_integration) -> None:
    for command in ("records", "credentials", "refresh"):
        reply = await _ask(hass, hass_ws_client, command, mac="00:00")
        assert reply["error"]["code"] == "not_found"
    reply = await _ask(hass, hass_ws_client, "passcode/add", mac="00:00", code="1234")
    assert reply["error"]["code"] == "not_found"
    for command in ("ekeys",):
        reply = await _ask(hass, hass_ws_client, command, mac="00:00")
        assert reply["error"]["code"] == "no_gateway"
    reply = await _ask(
        hass, hass_ws_client, "passcode/delete", mac="00:00", passcode_id=1
    )
    assert reply["error"]["code"] == "no_gateway"
    for command in ("options", "gateway/disconnect"):
        reply = await _ask(hass, hass_ws_client, command, entry_id="nope")
        assert reply["error"]["code"] == "not_found"
    reply = await _ask(
        hass,
        hass_ws_client,
        "gateway/connect",
        entry_id="nope",
        client_id="a",
        client_secret="b",
    )
    assert reply["error"]["code"] == "not_found"


async def test_records_come_from_our_history_without_a_cloud(
    hass, hass_ws_client, setup_integration, sample_virtual_key
) -> None:
    history = await async_get_history_store(hass)
    mac = sample_virtual_key.lockMac
    history.async_add(
        mac,
        {
            "type": "unlock",
            "record_type": "fr_unlock_succeed",
            "timestamp": "2026-11-23T10:00:00",
            "credential_type": "fingerprint",
            "credential_name": "Ana",
        },
    )
    history.async_add(mac, {"type": "lock", "record_type": "operate_key_lock"})
    reply = await _ask(hass, hass_ws_client, "records", mac=mac)
    assert reply["result"]["source"] == "lock"
    newest, oldest = reply["result"]["records"]
    assert newest == {
        "at": None,
        "type": "lock",
        "how": None,
        "who": None,
        "code": "operate_key_lock",
    }
    assert oldest["who"] == "Ana"
    assert oldest["how"] == "fingerprint"
    assert isinstance(oldest["at"], int)


async def test_records_come_from_the_cloud_when_it_answers(
    hass, hass_ws_client, gateway_entry, mock_api, sample_virtual_key
) -> None:
    await gateway_entry()
    mock_api.async_records = AsyncMock(
        return_value=[
            {"recordType": 8, "success": 1, "username": "Ana", "lockDate": 5},
            {"recordType": 4, "success": 0, "lockDate": 4},
            {"recordType": 999, "success": 1, "lockDate": 3},
        ]
    )
    mac = sample_virtual_key.lockMac
    reply = await _ask(hass, hass_ws_client, "records", mac=mac)
    assert reply["result"]["source"] == "cloud"
    assert reply["result"]["records"] == [
        {"at": 5, "type": "unlock", "how": "fingerprint", "who": "Ana", "code": 8},
        {"at": 4, "type": "unlock_failed", "how": "passcode", "who": None, "code": 4},
        {"at": 3, "type": "other", "how": None, "who": None, "code": 999},
    ]
    mock_api.async_records.side_effect = TtlockOpenApiError("down")
    reply = await _ask(hass, hass_ws_client, "records", mac=mac)
    assert reply["result"] == {"source": "lock", "records": []}


async def test_credentials_join_the_lock_and_the_cloud(
    hass, hass_ws_client, gateway_entry, mock_api, sample_virtual_key
) -> None:
    await gateway_entry()
    mock_api.async_passcodes = AsyncMock(
        return_value=[
            {"keyboardPwdId": 1, "keyboardPwd": "1234", "keyboardPwdName": "A"}
        ]
    )
    mock_api.async_cards = AsyncMock(return_value=[{"cardId": 2, "cardNumber": "77"}])
    mock_api.async_fingerprints = AsyncMock(
        return_value=[{"fingerprintId": 3, "fingerprintName": "Ana"}]
    )
    mac = sample_virtual_key.lockMac
    reply = await _ask(hass, hass_ws_client, "credentials", mac=mac)
    result = reply["result"]
    assert result["lock"] == {"passcodes": [], "cards": [], "fingerprints": []}
    assert result["cloud"]["passcodes"][0]["code"] == "1234"
    assert result["cloud"]["cards"][0]["label"] == "77"
    assert result["cloud"]["fingerprints"][0]["name"] == "Ana"
    mock_api.async_cards.side_effect = TtlockOpenApiError("down")
    reply = await _ask(hass, hass_ws_client, "credentials", mac=mac)
    assert reply["result"]["cloud"] == {"error": "down"}


async def test_credentials_without_a_cloud(
    hass, hass_ws_client, setup_integration, sample_virtual_key
) -> None:
    reply = await _ask(
        hass, hass_ws_client, "credentials", mac=sample_virtual_key.lockMac
    )
    assert reply["result"]["cloud"] == {}


async def test_ekeys(
    hass, hass_ws_client, gateway_entry, mock_api, sample_virtual_key
) -> None:
    await gateway_entry()
    mock_api.async_ekeys = AsyncMock(
        return_value=[{"keyId": 1, "keyName": "Ana", "keyRight": 1}]
    )
    mac = sample_virtual_key.lockMac
    reply = await _ask(hass, hass_ws_client, "ekeys", mac=mac)
    assert reply["result"][0]["name"] == "Ana"
    assert reply["result"][0]["admin"] is True
    mock_api.async_ekeys.side_effect = TtlockOpenApiError("down")
    reply = await _ask(hass, hass_ws_client, "ekeys", mac=mac)
    assert reply["error"]["code"] == "failed"


async def test_a_passcode_goes_over_bluetooth_and_is_told_to_the_cloud(
    hass,
    hass_ws_client,
    gateway_entry,
    mock_api,
    mock_ttlock_connection,
    sample_virtual_key,
) -> None:
    await gateway_entry()
    mock_ttlock_connection.async_add_passcode = AsyncMock()
    mock_api.async_add_passcode = AsyncMock(side_effect=TtlockOpenApiError("down"))
    mac = sample_virtual_key.lockMac
    with patch(
        "custom_components.ttlock_selfhost.panel.can_administer", return_value=True
    ):
        reply = await _ask(
            hass,
            hass_ws_client,
            "passcode/add",
            mac=mac,
            code="123456",
            name="Ana",
            start=1_700_000_000_000,
            end=1_700_003_600_000,
        )
    assert reply["result"] == {"code": "123456", "via": "bluetooth"}
    sent = mock_ttlock_connection.async_add_passcode.await_args
    assert sent.args == ("123456",)
    assert len(sent.kwargs["start"]) == 10
    assert mock_api.async_add_passcode.await_args.kwargs["via"] == 1


async def test_a_passcode_falls_back_to_the_gateway(
    hass,
    hass_ws_client,
    gateway_entry,
    mock_api,
    mock_ttlock_connection,
    sample_virtual_key,
) -> None:
    await gateway_entry()
    mock_ttlock_connection.async_add_passcode = AsyncMock(
        side_effect=TTLockError("far")
    )
    mock_api.async_add_passcode = AsyncMock(return_value=9)
    mac = sample_virtual_key.lockMac
    with patch(
        "custom_components.ttlock_selfhost.panel.can_administer", return_value=True
    ):
        reply = await _ask(hass, hass_ws_client, "passcode/add", mac=mac, code="1234")
    assert reply["result"]["via"] == "gateway"
    mock_api.async_add_passcode.side_effect = TtlockOpenApiError("off", -2012)
    reply = await _ask(hass, hass_ws_client, "passcode/add", mac=mac, code="1234")
    assert reply["error"]["code"] == "failed"


async def test_a_generated_passcode_comes_from_the_cloud(
    hass, hass_ws_client, gateway_entry, mock_api, sample_virtual_key
) -> None:
    await gateway_entry()
    mock_api.async_random_passcode = AsyncMock(return_value="998877")
    reply = await _ask(
        hass,
        hass_ws_client,
        "passcode/add",
        mac=sample_virtual_key.lockMac,
        random=2,
    )
    assert reply["result"] == {"code": "998877", "via": "cloud"}


async def test_passcodes_without_a_cloud(
    hass, hass_ws_client, setup_integration, mock_ttlock_connection, sample_virtual_key
) -> None:
    mac = sample_virtual_key.lockMac
    reply = await _ask(hass, hass_ws_client, "passcode/add", mac=mac, random=2)
    assert reply["error"]["message"] == "no_gateway"
    with patch(
        "custom_components.ttlock_selfhost.panel.can_administer", return_value=False
    ):
        reply = await _ask(hass, hass_ws_client, "passcode/add", mac=mac, code="1234")
    assert reply["error"]["message"] == "no_gateway"
    mock_ttlock_connection.async_add_passcode = AsyncMock(
        side_effect=TTLockError("far")
    )
    with patch(
        "custom_components.ttlock_selfhost.panel.can_administer", return_value=True
    ):
        reply = await _ask(hass, hass_ws_client, "passcode/add", mac=mac, code="1234")
        assert reply["error"]["message"] == "far"
        mock_ttlock_connection.async_add_passcode = AsyncMock()
        reply = await _ask(hass, hass_ws_client, "passcode/add", mac=mac, code="1234")
    assert reply["result"]["via"] == "bluetooth"
    mock_ttlock_connection.async_add_passcode.assert_awaited_once_with(
        "1234", start=None, end=None
    )


async def test_delete_passcode(
    hass, hass_ws_client, gateway_entry, mock_api, sample_virtual_key
) -> None:
    await gateway_entry()
    mock_api.async_delete_passcode = AsyncMock()
    mac = sample_virtual_key.lockMac
    reply = await _ask(hass, hass_ws_client, "passcode/delete", mac=mac, passcode_id=4)
    assert reply["success"]
    mock_api.async_delete_passcode.side_effect = TtlockOpenApiError("down")
    reply = await _ask(hass, hass_ws_client, "passcode/delete", mac=mac, passcode_id=4)
    assert reply["error"]["code"] == "failed"


async def test_refresh_reports_the_route_that_answered(
    hass,
    hass_ws_client,
    gateway_entry,
    mock_api,
    mock_ttlock_connection,
    sample_virtual_key,
) -> None:
    await gateway_entry()
    mac = sample_virtual_key.lockMac
    reply = await _ask(hass, hass_ws_client, "refresh", mac=mac)
    assert reply["result"] == {"via": "bluetooth"}
    mock_ttlock_connection.async_query_state.return_value = None
    reply = await _ask(hass, hass_ws_client, "refresh", mac=mac)
    assert reply["result"] == {"via": "gateway"}
    mock_api.async_open_state.return_value = None
    reply = await _ask(hass, hass_ws_client, "refresh", mac=mac)
    assert reply["result"] == {"via": "none"}


async def test_refresh_without_any_route(
    hass, hass_ws_client, setup_integration, mock_ttlock_connection, sample_virtual_key
) -> None:
    mock_ttlock_connection.async_query_state.return_value = None
    reply = await _ask(hass, hass_ws_client, "refresh", mac=sample_virtual_key.lockMac)
    assert reply["result"] == {"via": "none"}


async def test_options_change_the_route(
    hass, hass_ws_client, setup_integration
) -> None:
    entry = setup_integration
    reply = await _ask(
        hass, hass_ws_client, "options", entry_id=entry.entry_id, route="bluetooth"
    )
    assert reply["success"]
    await hass.async_block_till_done()
    assert entry.options[CONF_ROUTE] == "bluetooth"


@pytest.fixture
def mock_login():
    with patch("custom_components.ttlock_selfhost.panel.TtlockOpenApi") as cls:
        api = cls.return_value
        api.async_login = AsyncMock(
            return_value={"access_token": "a", "refresh_token": "r", "expires_at": 9e12}
        )
        api.async_locks = AsyncMock(return_value=[{"lockId": 1}])
        yield api


async def test_connecting_the_gateway_keeps_the_session_and_reloads(
    hass,
    hass_ws_client,
    setup_integration,
    mock_login,
    mock_api,
) -> None:
    entry = setup_integration
    reply = await _ask(
        hass,
        hass_ws_client,
        "gateway/connect",
        entry_id=entry.entry_id,
        client_id=" cid ",
        client_secret="sec",
    )
    assert reply["result"] == {"locks": 1}
    mock_login.async_login.assert_awaited_once_with("user@example.com", "pass")
    await hass.async_block_till_done()
    assert entry.data[CONF_GATEWAY]["client_id"] == "cid"
    assert entry.runtime_data.gateway is not None
    reply = await _ask(
        hass, hass_ws_client, "gateway/disconnect", entry_id=entry.entry_id
    )
    assert reply["success"]
    await hass.async_block_till_done()
    assert CONF_GATEWAY not in entry.data
    assert entry.runtime_data.gateway is None


async def test_connecting_reports_why_it_failed(
    hass, hass_ws_client, setup_integration, mock_login
) -> None:
    entry = setup_integration
    fields = {"entry_id": entry.entry_id, "client_id": "c", "client_secret": "s"}
    mock_login.async_login.side_effect = TtlockOpenApiError("bad", 10007)
    reply = await _ask(hass, hass_ws_client, "gateway/connect", **fields)
    assert reply["error"]["code"] == "failed"
    mock_login.async_login.side_effect = TtlockOpenApiError("down")
    reply = await _ask(hass, hass_ws_client, "gateway/connect", **fields)
    assert reply["error"]["code"] == "unreachable"
    hass.config_entries.async_update_entry(entry, data={"keys": entry.data["keys"]})
    await hass.async_block_till_done()
    reply = await _ask(hass, hass_ws_client, "gateway/connect", **fields)
    assert reply["error"]["code"] == "need_account"
