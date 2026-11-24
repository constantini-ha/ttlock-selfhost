from __future__ import annotations

import datetime as dt
import json
import time
from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.ttlock_selfhost.cloud_push import callback_path, callback_url
from custom_components.ttlock_selfhost.cloud_record import bolt_of, log_entry_of
from ttlock_ble import LogOperate


def _row(code: int, *, ago: float = -1.0, **fields):
    return {
        "recordType": code,
        "success": 1,
        "lockDate": int((time.time() - ago) * 1000),
        "electricQuantity": 70,
        **fields,
    }


async def _post(hass, hass_client_no_auth, entry, rows, **fields):
    client = await hass_client_no_auth()
    reply = await client.post(
        callback_path(entry),
        data={
            "notifyType": "1",
            "lockId": str(entry.runtime_data.virtual_keys[0].lockId),
            "records": json.dumps(rows),
            **fields,
        },
    )
    await hass.async_block_till_done()
    assert reply.status == 200
    assert await reply.text() == "success"


async def _later(hass, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + dt.timedelta(seconds=seconds))
    await hass.async_block_till_done()


def _lock(hass):
    return hass.states.async_all("lock")[0]


def _log(hass):
    return hass.states.async_all("event")[0]


@pytest.mark.parametrize(
    ("code", "success", "expected"),
    [
        (1, 1, LogOperate.MOBILE_UNLOCK),
        (8, 1, LogOperate.FR_UNLOCK_SUCCEED),
        (8, 0, LogOperate.FR_UNLOCK_FAILED),
        (46, 1, LogOperate.OPERATE_KEY_UNLOCK),
        (31, 1, LogOperate.DOOR_SENSOR_UNLOCK),
        (45, 1, 45),
        (12, 0, None),
        (5, 1, None),
    ],
)
def test_a_cloud_record_reads_as_the_lock_would_log_it(code, success, expected) -> None:
    entry = log_entry_of(_row(code, success=success), battery=10)
    assert (entry and entry.record_type) == expected


def test_a_cloud_record_keeps_the_name_and_drops_the_door_code() -> None:
    stamp = int(dt.datetime(2026, 11, 24, 15, 0, tzinfo=dt.UTC).timestamp() * 1000)
    code = log_entry_of(
        {
            "recordType": 4,
            "lockDate": stamp,
            "keyboardPwd": "135790",
            "username": "Ana",
        },
        battery=33,
    )
    assert code.password is None
    assert code.username == "Ana"
    assert code.lock_battery == 33
    assert code.operate_date == dt_util.as_local(
        dt.datetime(2026, 11, 24, 15, 0, tzinfo=dt.UTC)
    ).replace(tzinfo=None)
    finger = log_entry_of(_row(8, keyboardPwd="77", username=""), battery=0)
    assert (finger.password, finger.username, finger.lock_battery) == ("77", None, 70)
    assert log_entry_of({"recordType": 4}, battery=0) is None
    assert log_entry_of({"lockDate": stamp}, battery=0) is None


def test_only_a_successful_lock_or_unlock_tells_the_bolt() -> None:
    assert bolt_of({"recordType": 11}) is True
    assert bolt_of({"recordType": 8}) is False
    assert bolt_of({"recordType": 8, "success": 0}) is None
    assert bolt_of({"recordType": 31}) is None
    assert bolt_of({"recordType": 999}) is None
    assert bolt_of({}) is None


async def test_an_unlock_pushed_by_the_cloud_shows_at_once(
    hass, hass_client_no_auth, hass_ws_client, gateway_entry, sample_virtual_key
) -> None:
    entry = await gateway_entry()
    assert _lock(hass).state == "locked"
    await _post(
        hass,
        hass_client_no_auth,
        entry,
        [_row(8, keyboardPwd="77", username="Ana", electricQuantity=41)],
    )
    assert _lock(hass).state == "unlocked"
    event = _log(hass)
    assert event.attributes["event_type"] == "unlock"
    assert event.attributes["record_type"] == "fr_unlock_succeed"
    assert event.attributes["credential_name"] == "Ana"
    assert event.attributes["battery"] == 41
    mac = sample_virtual_key.lockMac
    assert entry.runtime_data.coordinator.data[mac]["battery_level"] == 41
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "ttlock_selfhost/locks"})
    callback = (await client.receive_json())["result"][0]["gateway"]["callback"]
    assert callback["received_at"] == int(entry.runtime_data.gateway.pushed_at * 1000)


async def test_a_door_code_never_leaves_the_push(
    hass, hass_client_no_auth, gateway_entry
) -> None:
    entry = await gateway_entry()
    await _post(
        hass,
        hass_client_no_auth,
        entry,
        [_row(4, keyboardPwd="135790", username="Cleaner")],
    )
    event = _log(hass)
    assert event.attributes["credential_name"] == "Cleaner"
    assert "135790" not in str(event.as_dict())


async def test_the_same_record_pushed_twice_counts_once(
    hass, hass_client_no_auth, gateway_entry
) -> None:
    entry = await gateway_entry()
    row = _row(8)
    await _post(hass, hass_client_no_auth, entry, [row])
    first = _log(hass).state
    await _post(hass, hass_client_no_auth, entry, [row])
    assert _log(hass).state == first


async def test_an_old_record_does_not_move_the_bolt(
    hass, hass_client_no_auth, gateway_entry
) -> None:
    entry = await gateway_entry()
    await _post(hass, hass_client_no_auth, entry, [_row(8, ago=3600, username="Ana")])
    assert _lock(hass).state == "locked"
    assert _log(hass).attributes["credential_name"] == "Ana"


async def test_a_slow_lock_clock_does_not_hide_an_unlock(
    hass, hass_client_no_auth, gateway_entry
) -> None:
    entry = await gateway_entry()
    stamp = int((time.time() - 200) * 1000)
    await _post(
        hass,
        hass_client_no_auth,
        entry,
        [{"recordType": 8, "success": 1, "lockDate": stamp, "serverDate": stamp + 900}],
    )
    assert _lock(hass).state == "unlocked"


async def test_a_record_older_than_the_last_one_taken_is_ignored(
    hass, hass_client_no_auth, gateway_entry
) -> None:
    entry = await gateway_entry()
    await _post(hass, hass_client_no_auth, entry, [_row(8, ago=-5)])
    await _post(hass, hass_client_no_auth, entry, [_row(11, ago=10)])
    assert _lock(hass).state == "unlocked"
    await _post(hass, hass_client_no_auth, entry, [_row(11, ago=-6)])
    assert _lock(hass).state == "locked"


async def test_the_newest_record_of_a_batch_decides(
    hass, hass_client_no_auth, gateway_entry, mock_api
) -> None:
    entry = await gateway_entry()
    mock_api.async_open_state.reset_mock()
    await _post(
        hass,
        hass_client_no_auth,
        entry,
        [_row(11, ago=-3), _row(8, ago=-1), _row(31, ago=-2), _row(47, ago=-4)],
    )
    assert _lock(hass).state == "locked"
    await _later(hass, 300)
    mock_api.async_open_state.assert_not_awaited()


async def test_a_door_record_feeds_the_door_sensor(
    hass, hass_client_no_auth, gateway_entry, sample_virtual_key
) -> None:
    entry = await gateway_entry()
    await _post(hass, hass_client_no_auth, entry, [_row(31)])
    door = er.async_get(hass).async_get_entity_id(
        "binary_sensor", "ttlock_selfhost", f"{sample_virtual_key.lockMac}_door"
    )
    assert hass.states.get(door).state == "on"


async def test_the_bolt_is_asked_for_after_an_unlock_until_it_locks(
    hass, hass_client_no_auth, gateway_entry, mock_api
) -> None:
    entry = await gateway_entry()
    mock_api.async_open_state.reset_mock()
    mock_api.async_open_state.return_value = False
    await _post(hass, hass_client_no_auth, entry, [_row(8)])
    await _later(hass, 21)
    assert mock_api.async_open_state.await_count == 1
    assert _lock(hass).state == "unlocked"
    mock_api.async_open_state.return_value = True
    await _later(hass, 121)
    assert mock_api.async_open_state.await_count == 2
    assert _lock(hass).state == "locked"
    await _later(hass, 600)
    assert mock_api.async_open_state.await_count == 2


async def test_a_lock_that_stays_open_is_asked_twice_and_left_alone(
    hass, hass_client_no_auth, gateway_entry, mock_api
) -> None:
    entry = await gateway_entry()
    mock_api.async_open_state.reset_mock()
    mock_api.async_open_state.return_value = False
    await _post(hass, hass_client_no_auth, entry, [_row(8)])
    await _later(hass, 21)
    await _later(hass, 121)
    await _later(hass, 600)
    assert mock_api.async_open_state.await_count == 2


async def test_a_new_push_restarts_the_wait(
    hass, hass_client_no_auth, gateway_entry, mock_api
) -> None:
    entry = await gateway_entry()
    mock_api.async_open_state.reset_mock()
    await _post(hass, hass_client_no_auth, entry, [_row(8)])
    await _later(hass, 15)
    await _post(hass, hass_client_no_auth, entry, [_row(30)])
    await _later(hass, 30)
    assert mock_api.async_open_state.await_count == 1
    assert _lock(hass).state == "locked"


async def test_a_push_during_the_read_keeps_its_own_wait(
    hass, hass_client_no_auth, gateway_entry, mock_api
) -> None:
    entry = await gateway_entry()
    gateway = entry.runtime_data.gateway
    key = entry.runtime_data.virtual_keys[0]

    async def pushed_meanwhile(_lock_id):
        gateway.async_push(key.lockId, [_row(31)])
        return False

    mock_api.async_open_state.reset_mock()
    mock_api.async_open_state.side_effect = pushed_meanwhile
    await _post(hass, hass_client_no_auth, entry, [_row(8)])
    await _later(hass, 21)
    assert mock_api.async_open_state.await_count == 1
    mock_api.async_open_state.side_effect = None
    await _later(hass, 21)
    assert mock_api.async_open_state.await_count == 2
    assert _lock(hass).state == "locked"


async def test_unloading_stops_the_wait(
    hass, hass_client_no_auth, gateway_entry, mock_api
) -> None:
    entry = await gateway_entry()
    mock_api.async_open_state.reset_mock()
    await _post(hass, hass_client_no_auth, entry, [_row(8)])
    assert await hass.config_entries.async_unload(entry.entry_id)
    await _later(hass, 300)
    mock_api.async_open_state.assert_not_awaited()
    client = await hass_client_no_auth()
    assert await (await client.post(callback_path(entry))).text() != "success"


async def test_a_lock_bluetooth_hears_is_left_to_bluetooth(
    hass, hass_client_no_auth, gateway_entry
) -> None:
    entry = await gateway_entry()
    with patch(
        "custom_components.ttlock_selfhost.gateway.bluetooth.async_address_present",
        return_value=True,
    ):
        await _post(hass, hass_client_no_auth, entry, [_row(8)])
    assert _lock(hass).state == "locked"
    assert _log(hass).state == "unknown"


async def test_what_cannot_be_read_is_still_answered(
    hass, hass_client_no_auth, gateway_entry
) -> None:
    entry = await gateway_entry()
    for fields in (
        {"lockId": "999"},
        {"lockId": "nope"},
        {"records": "{"},
        {"records": "7"},
        {"records": json.dumps(["x", {"recordType": "8"}])},
    ):
        await _post(hass, hass_client_no_auth, entry, [_row(8)], **fields)
    assert _lock(hass).state == "locked"
    assert _log(hass).state == "unknown"
    client = await hass_client_no_auth()
    assert await (await client.post(callback_path(entry))).text() == "success"


async def test_the_address_needs_an_external_url(hass, gateway_entry) -> None:
    entry = await gateway_entry()
    assert callback_url(hass, entry) is None
    hass.config.external_url = "https://ha.example.com"
    assert callback_url(hass, entry) == f"https://ha.example.com{callback_path(entry)}"
