from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.lock import SERVICE_LOCK, SERVICE_UNLOCK
from homeassistant.exceptions import HomeAssistantError

from custom_components.ttlock_selfhost.const import CONF_GATEWAY
from custom_components.ttlock_selfhost.openapi import TtlockOpenApiError
from ttlock_ble import TTLockError


async def _call(hass, service):
    state = hass.states.async_all("lock")[0]
    await hass.services.async_call(
        LOCK_DOMAIN, service, {"entity_id": state.entity_id}, blocking=True
    )
    return hass.states.get(state.entity_id)


async def test_setup_reads_the_cloud_once_bluetooth_is_silent(
    hass, gateway_entry, mock_api, sample_virtual_key
) -> None:
    entry = await gateway_entry()
    gateway = entry.runtime_data.gateway
    link = gateway.link(sample_virtual_key.lockMac)
    assert link["has_gateway"] is True
    assert link["gateways"] == [{"gatewayName": "G2", "rssi": -60}]
    mock_api.async_open_state.assert_awaited_once()
    assert hass.states.async_all("lock")[0].state == "locked"
    snapshot = entry.runtime_data.coordinator.data[sample_virtual_key.lockMac]
    assert snapshot["battery_level"] == 55


async def test_a_fresh_bluetooth_reading_spares_the_gateway(
    hass, gateway_entry, mock_api, sample_virtual_key
) -> None:
    entry = await gateway_entry()
    mock_api.async_open_state.reset_mock()
    await entry.runtime_data.gateway.async_refresh()
    mock_api.async_open_state.assert_not_awaited()
    coordinator = entry.runtime_data.coordinator
    assert coordinator.async_state_age(sample_virtual_key.lockMac) < 60
    assert coordinator.async_state_age("unknown") == float("inf")
    # Battery read over Bluetooth is not replaced by the cloud's older one.
    coordinator.async_set_updated_data(
        {sample_virtual_key.lockMac: {"locked": True, "battery_level": 80}}
    )
    coordinator.async_apply_cloud_state(sample_virtual_key.lockMac, battery=10)
    assert coordinator.data[sample_virtual_key.lockMac]["battery_level"] == 80


async def test_bluetooth_goes_first_and_the_gateway_is_left_alone(
    hass, gateway_entry, mock_api, mock_ttlock_connection
) -> None:
    await gateway_entry()
    state = await _call(hass, SERVICE_UNLOCK)
    mock_ttlock_connection.async_unlock.assert_awaited_once()
    mock_api.async_unlock.assert_not_awaited()
    assert state.attributes["last_route"] == "bluetooth"


async def test_the_gateway_takes_over_when_bluetooth_fails(
    hass, gateway_entry, mock_api, mock_ttlock_connection
) -> None:
    await gateway_entry()
    mock_ttlock_connection.async_lock = AsyncMock(side_effect=TTLockError("far"))
    state = await _call(hass, SERVICE_LOCK)
    mock_api.async_lock.assert_awaited_once()
    assert state.attributes["last_route"] == "gateway"


async def test_route_bluetooth_never_reaches_the_cloud(
    hass, gateway_entry, mock_api, mock_ttlock_connection
) -> None:
    await gateway_entry("bluetooth")
    mock_ttlock_connection.async_unlock = AsyncMock(side_effect=TTLockError("far"))
    with pytest.raises(HomeAssistantError):
        await _call(hass, SERVICE_UNLOCK)
    mock_api.async_unlock.assert_not_awaited()


async def test_route_gateway_skips_bluetooth(
    hass, gateway_entry, mock_api, mock_ttlock_connection
) -> None:
    await gateway_entry("gateway")
    await _call(hass, SERVICE_UNLOCK)
    mock_ttlock_connection.async_unlock.assert_not_awaited()
    mock_api.async_unlock.assert_awaited_once()


async def test_a_cloud_refusal_fails_the_command(hass, gateway_entry, mock_api) -> None:
    await gateway_entry("gateway")
    mock_api.async_unlock = AsyncMock(side_effect=TtlockOpenApiError("off", -4043))
    with pytest.raises(HomeAssistantError, match="gateway: off"):
        await _call(hass, SERVICE_UNLOCK)


async def test_a_lock_without_gateway_stays_on_bluetooth(
    hass, gateway_entry, mock_api, mock_ttlock_connection, sample_virtual_key
) -> None:
    mock_api.async_locks.return_value = [
        {"lockId": sample_virtual_key.lockId, "hasGateway": 0}
    ]
    entry = await gateway_entry("gateway")
    assert not entry.runtime_data.gateway.reaches(sample_virtual_key.lockMac)
    mock_api.async_gateways_of.assert_not_awaited()
    await _call(hass, SERVICE_UNLOCK)
    mock_ttlock_connection.async_unlock.assert_awaited_once()
    mock_api.async_unlock.assert_not_awaited()


async def test_cloud_failures_are_kept_as_the_link_error(
    hass, gateway_entry, mock_api, sample_virtual_key
) -> None:
    mock_api.async_locks.side_effect = TtlockOpenApiError("down")
    entry = await gateway_entry()
    gateway = entry.runtime_data.gateway
    mac = sample_virtual_key.lockMac
    assert gateway.link(mac)["error"] == "down"
    assert gateway.reaches(mac)
    mock_api.async_locks.side_effect = None
    mock_api.async_gateways_of.side_effect = TtlockOpenApiError("busy", -3003)
    await gateway.async_refresh()
    assert gateway.link(mac)["error"] == "busy (-3003)"
    mock_api.async_open_state.side_effect = TtlockOpenApiError("off")
    assert await gateway.async_read_state(sample_virtual_key) is None


async def test_a_shared_lock_missing_from_the_list_is_still_tried(
    hass, gateway_entry, mock_api, sample_virtual_key
) -> None:
    mock_api.async_locks.return_value = []
    entry = await gateway_entry()
    gateway = entry.runtime_data.gateway
    assert gateway.link(sample_virtual_key.lockMac)["has_gateway"] is None
    assert gateway.reaches(sample_virtual_key.lockMac)


async def test_a_renewed_session_is_stored_without_reloading(
    hass, gateway_entry, mock_api
) -> None:
    entry = await gateway_entry()
    runtime = entry.runtime_data
    on_token = mock_api.cls.call_args.kwargs["on_token"]
    token = {"access_token": "n", "refresh_token": "r", "expires_at": time.time()}
    on_token(token)
    await hass.async_block_till_done()
    assert entry.data[CONF_GATEWAY]["token"] == token
    assert entry.runtime_data is runtime
    assert not runtime.gateway.async_consume_token_update()


async def test_the_settle_query_asks_the_gateway_when_bluetooth_is_silent(
    hass, gateway_entry, mock_api, mock_ttlock_connection
) -> None:
    await gateway_entry("gateway")
    mock_ttlock_connection.async_query_state.return_value = None
    mock_api.async_open_state.reset_mock()
    mock_api.async_open_state.return_value = False
    await _call(hass, SERVICE_UNLOCK)
    entity = hass.data["lock"].get_entity(hass.states.async_all("lock")[0].entity_id)
    await entity._async_query_and_apply()
    mock_api.async_open_state.assert_awaited()
