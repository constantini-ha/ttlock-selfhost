"""Serves the panel and the commands it runs: one screen per lock, like the app."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import probatio as vol
from homeassistant.components import bluetooth, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.loader import async_get_integration

from ttlock_ble import TTLockError

from .const import (
    CONF_GATEWAY,
    CONF_PERMANENT_CONNECTION,
    CONF_ROUTE,
    DOMAIN,
    LOGGER,
    ROUTE_AUTO,
    ROUTE_GATEWAY,
    ROUTES,
)
from .credential_store import async_get_credential_store
from .credential_type import TtlockBleCredentialType
from .history_store import async_get_history_store
from .key_privileges import can_administer
from .openapi import (
    DEFAULT_REGION,
    REGIONS,
    VIA_BLUETOOTH,
    Json,
    TtlockOpenApi,
    TtlockOpenApiError,
)

if TYPE_CHECKING:
    from homeassistant.components.websocket_api import ActiveConnection

    from ttlock_ble import VirtualKey

    from .data import TtlockBleConfigEntry
    from .gateway import TtlockBleGateway

PANEL_FILE = "ttlock-selfhost-panel.js"
CARD_FILE = "ttlock-selfhost-doors-card.js"
PANEL_URL_PATH = "ttlock-selfhost"
FRONTEND_URL = f"/{DOMAIN}/frontend"
READY_FLAG = f"{DOMAIN}_panel"
RECORD_DAYS = 30
ERR_FAILED = "failed"
ERR_NOT_FOUND = "not_found"
ERR_NO_GATEWAY = "no_gateway"

# Cloud record type -> (what happened, the credential behind it).
CLOUD_RECORDS: dict[int, tuple[str, str | None]] = {
    1: ("unlock", "app"),
    4: ("unlock", "passcode"),
    7: ("unlock", "card"),
    8: ("unlock", "fingerprint"),
    9: ("unlock", "key_fob"),
    10: ("unlock", "mechanical_key"),
    11: ("lock", "app"),
    12: ("unlock", "gateway"),
    29: ("alarm", None),
    30: ("door_closed", None),
    31: ("door_open", None),
    32: ("unlock", "inside"),
    33: ("lock", "fingerprint"),
    34: ("lock", "passcode"),
    35: ("lock", "card"),
    36: ("lock", "mechanical_key"),
    44: ("alarm", None),
    45: ("lock", "auto"),
    46: ("unlock", "button"),
    47: ("lock", "button"),
    48: ("alarm", None),
    55: ("unlock", "key_fob"),
    92: ("unlock", "passcode"),
}

type Message = dict[str, object]


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register the panel and its commands, once per Home Assistant run."""
    if hass.data.get(READY_FLAG):
        return
    hass.data[READY_FLAG] = True
    for command in (
        websocket_locks,
        websocket_records,
        websocket_credentials,
        websocket_ekeys,
        websocket_add_passcode,
        websocket_delete_passcode,
        websocket_refresh,
        websocket_options,
        websocket_connect_gateway,
        websocket_disconnect_gateway,
    ):
        websocket_api.async_register_command(hass, command)
    # Headless setups (and the tests) run without the frontend.
    if hass.http is None or "panel_custom" not in hass.config.components:
        return
    from homeassistant.components import panel_custom  # noqa: PLC0415

    integration = await async_get_integration(hass, DOMAIN)
    # Served under the version, so a relative import cannot load a stale file.
    base = f"{FRONTEND_URL}/{integration.version}"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                base, str(Path(__file__).parent / "frontend"), cache_headers=True
            )
        ]
    )
    if "frontend" in hass.config.components:
        from homeassistant.components.frontend import (  # noqa: PLC0415
            add_extra_js_url,
        )

        add_extra_js_url(hass, f"{base}/{CARD_FILE}")
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="ttlock-selfhost-panel",
        frontend_url_path=PANEL_URL_PATH,
        module_url=f"{base}/{PANEL_FILE}",
        sidebar_title="TTLock Selfhost",
        sidebar_icon="mdi:lock-smart",
        require_admin=True,
        embed_iframe=False,
    )


def _entries(hass: HomeAssistant) -> list[TtlockBleConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _find(
    hass: HomeAssistant, mac: str
) -> tuple[TtlockBleConfigEntry, VirtualKey] | None:
    for entry in _entries(hass):
        for key in entry.runtime_data.virtual_keys:
            if key.lockMac == mac:
                return entry, key
    return None


def _entities(
    hass: HomeAssistant, entry: TtlockBleConfigEntry, mac: str
) -> dict[str, str]:
    """Map each entity of a lock by what follows the MAC in its unique id."""
    registry = er.async_get(hass)
    prefix = f"{mac}_"
    return {
        entity.unique_id[len(prefix) :]: entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.unique_id.startswith(prefix)
    }


def _describe(
    hass: HomeAssistant, entry: TtlockBleConfigEntry, key: VirtualKey
) -> Message:
    data = entry.runtime_data
    mac = key.lockMac
    state = (data.coordinator.data or {}).get(mac) or {}
    heard = bluetooth.async_last_service_info(hass, mac, connectable=False)
    description = data.coordinator.async_device_description(mac)
    link = data.gateway.link(mac) if data.gateway else None
    return {
        "entry_id": entry.entry_id,
        "mac": mac,
        "lock_id": key.lockId,
        "name": key.lockAlias or key.lockName or mac,
        "model": description["model"] if description else None,
        "admin": can_administer(key),
        "account": entry.data.get("username"),
        "locked": state.get("locked"),
        "battery": state.get("battery_level"),
        "bluetooth": {
            "connected": data.connections[mac].is_connected,
            "rssi": heard.rssi if heard else None,
        },
        "gateway": {
            "configured": data.gateway is not None,
            "has_gateway": link["has_gateway"] if link else None,
            "gateways": [
                {"name": row.get("gatewayName"), "rssi": row.get("rssi")}
                for row in (link["gateways"] if link else [])
            ],
            "error": link["error"] if link else None,
        },
        "route": entry.options.get(CONF_ROUTE, ROUTE_AUTO),
        "permanent_connection": bool(
            entry.options.get(CONF_PERMANENT_CONNECTION, False)
        ),
        "entities": _entities(hass, entry, mac),
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/locks"})
@websocket_api.require_admin
@callback
def websocket_locks(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Every configured lock, with what both routes know about it."""
    connection.send_result(
        cast("int", msg["id"]),
        [
            _describe(hass, entry, key)
            for entry in _entries(hass)
            for key in entry.runtime_data.virtual_keys
        ],
    )


def _cloud_record(row: Json) -> Message:
    kind, how = CLOUD_RECORDS.get(
        cast("int", row.get("recordType") or 0), ("other", None)
    )
    return {
        "at": row.get("lockDate"),
        "type": kind if row.get("success", 1) else f"{kind}_failed",
        "how": how,
        "who": row.get("username") or None,
        "code": row.get("recordType"),
    }


def _local_record(row: dict[str, str | int | bool | None]) -> Message:
    stamp = row.get("timestamp")
    return {
        # The lock's clock is wall time; the browser reads it the same way.
        "at": int(datetime.fromisoformat(stamp).timestamp() * 1000)
        if isinstance(stamp, str)
        else None,
        "type": row.get("type"),
        "how": row.get("credential_type"),
        "who": row.get("credential_name") or row.get("credential"),
        "code": row.get("record_type"),
    }


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/records", vol.Required("mac"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_records(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Return the recent records: the cloud's when there is one, else our own."""
    found = _find(hass, cast("str", msg["mac"]))
    if found is None:
        connection.send_error(cast("int", msg["id"]), ERR_NOT_FOUND, "Unknown lock")
        return
    entry, key = found
    gateway = entry.runtime_data.gateway
    if gateway is not None:
        since = int((time.time() - RECORD_DAYS * 86400) * 1000)
        try:
            rows = await gateway.api.async_records(key.lockId, since_ms=since)
        except TtlockOpenApiError as exc:
            LOGGER.debug("Cloud records failed for %s: %s", key.lockMac, exc)
        else:
            connection.send_result(
                cast("int", msg["id"]),
                {"source": "cloud", "records": [_cloud_record(row) for row in rows]},
            )
            return
    history = await async_get_history_store(hass)
    connection.send_result(
        cast("int", msg["id"]),
        {
            "source": "lock",
            "records": [_local_record(row) for row in history.recent(key.lockMac)],
        },
    )


async def _async_cloud_lists(gateway: TtlockBleGateway | None, lock_id: int) -> Message:
    if gateway is None:
        return {}
    try:
        return {
            "passcodes": [
                {
                    "id": row.get("keyboardPwdId"),
                    "code": row.get("keyboardPwd"),
                    "name": row.get("keyboardPwdName"),
                    "kind": row.get("keyboardPwdType"),
                    "start": row.get("startDate"),
                    "end": row.get("endDate"),
                }
                for row in await gateway.api.async_passcodes(lock_id)
            ],
            "cards": [
                {
                    "id": row.get("cardId"),
                    "label": row.get("cardNumber"),
                    "name": row.get("cardName"),
                    "start": row.get("startDate"),
                    "end": row.get("endDate"),
                }
                for row in await gateway.api.async_cards(lock_id)
            ],
            "fingerprints": [
                {
                    "id": row.get("fingerprintId"),
                    "label": row.get("fingerprintNumber"),
                    "name": row.get("fingerprintName"),
                    "start": row.get("startDate"),
                    "end": row.get("endDate"),
                }
                for row in await gateway.api.async_fingerprints(lock_id)
            ],
        }
    except TtlockOpenApiError as exc:
        LOGGER.debug("Cloud credential lists failed for lock %s: %s", lock_id, exc)
        return {"error": str(exc)}


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/credentials", vol.Required("mac"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_credentials(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Return the credentials the lock listed and the ones the cloud holds."""
    found = _find(hass, cast("str", msg["mac"]))
    if found is None:
        connection.send_error(cast("int", msg["id"]), ERR_NOT_FOUND, "Unknown lock")
        return
    entry, key = found
    store = await async_get_credential_store(hass)
    local = {
        name: [
            {
                "label": credential.label,
                "name": store.name_of(key.lockMac, kind, credential.key),
            }
            for credential in store.known(key.lockMac, kind) or []
        ]
        for name, kind in (
            ("passcodes", TtlockBleCredentialType.PASSCODE),
            ("cards", TtlockBleCredentialType.CARD),
            ("fingerprints", TtlockBleCredentialType.FINGERPRINT),
        )
    }
    cloud = await _async_cloud_lists(entry.runtime_data.gateway, key.lockId)
    connection.send_result(cast("int", msg["id"]), {"lock": local, "cloud": cloud})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/ekeys", vol.Required("mac"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_ekeys(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Return the eKeys shared for a lock; only the cloud knows them."""
    found = _find(hass, cast("str", msg["mac"]))
    gateway = found[0].runtime_data.gateway if found else None
    if found is None or gateway is None:
        connection.send_error(cast("int", msg["id"]), ERR_NO_GATEWAY, "No cloud route")
        return
    try:
        rows = await gateway.api.async_ekeys(found[1].lockId)
    except TtlockOpenApiError as exc:
        connection.send_error(cast("int", msg["id"]), ERR_FAILED, str(exc))
        return
    connection.send_result(
        cast("int", msg["id"]),
        [
            {
                "id": row.get("keyId"),
                "name": row.get("keyName"),
                "user": row.get("username"),
                "status": row.get("keyStatus"),
                "start": row.get("startDate"),
                "end": row.get("endDate"),
                "admin": row.get("keyRight") == 1,
            }
            for row in rows
        ],
    )


def _lock_clock(ms: int) -> str:
    """Render a moment as the lock's own YYMMDDHHmm wall time."""
    return datetime.fromtimestamp(ms / 1000).strftime("%y%m%d%H%M")  # noqa: DTZ006


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/passcode/add",
        vol.Required("mac"): str,
        vol.Optional("code"): vol.All(str, vol.Match(r"^\d{4,9}$")),
        vol.Optional("name", default=""): str,
        vol.Optional("start"): int,
        vol.Optional("end"): int,
        vol.Optional("random"): vol.All(int, vol.Range(min=1, max=14)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_add_passcode(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Create a passcode: generated by the cloud, or written to the lock."""
    found = _find(hass, cast("str", msg["mac"]))
    if found is None:
        connection.send_error(cast("int", msg["id"]), ERR_NOT_FOUND, "Unknown lock")
        return
    entry, key = found
    try:
        result = await _async_add_passcode(entry, key, msg)
    except (TTLockError, TtlockOpenApiError) as exc:
        connection.send_error(cast("int", msg["id"]), ERR_FAILED, str(exc))
        return
    connection.send_result(cast("int", msg["id"]), result)


async def _async_add_passcode(
    entry: TtlockBleConfigEntry, key: VirtualKey, msg: Message
) -> Message:
    gateway = entry.runtime_data.gateway
    name = cast("str", msg["name"])
    start = cast("int | None", msg.get("start"))
    end = cast("int | None", msg.get("end"))
    if "random" in msg:
        if gateway is None:
            raise TtlockOpenApiError(ERR_NO_GATEWAY)
        code = await gateway.api.async_random_passcode(
            key.lockId,
            name=name,
            kind=cast("int", msg["random"]),
            start_ms=start or int(time.time() * 1000),
            end_ms=end,
        )
        return {"code": code, "via": "cloud"}
    code = cast("str", msg["code"])
    route = entry.options.get(CONF_ROUTE, ROUTE_AUTO)
    if can_administer(key) and (route != ROUTE_GATEWAY or gateway is None):
        try:
            await entry.runtime_data.connections[key.lockMac].async_add_passcode(
                code,
                start=_lock_clock(start or int(time.time() * 1000)) if end else None,
                end=_lock_clock(end) if end else None,
            )
        except TTLockError:
            if gateway is None:
                raise
        else:
            if gateway is not None:
                # The lock holds it now; this only lets the app list it too.
                try:
                    await gateway.api.async_add_passcode(
                        key.lockId,
                        code=code,
                        name=name,
                        start_ms=start,
                        end_ms=end,
                        via=VIA_BLUETOOTH,
                    )
                except TtlockOpenApiError as exc:
                    LOGGER.debug("Passcode not recorded in the cloud: %s", exc)
            return {"code": code, "via": "bluetooth"}
    if gateway is None:
        raise TtlockOpenApiError(ERR_NO_GATEWAY)
    await gateway.api.async_add_passcode(
        key.lockId, code=code, name=name, start_ms=start, end_ms=end
    )
    return {"code": code, "via": "gateway"}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/passcode/delete",
        vol.Required("mac"): str,
        vol.Required("passcode_id"): int,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_delete_passcode(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Remove a passcode the cloud lists, through the gateway."""
    found = _find(hass, cast("str", msg["mac"]))
    gateway = found[0].runtime_data.gateway if found else None
    if found is None or gateway is None:
        connection.send_error(cast("int", msg["id"]), ERR_NO_GATEWAY, "No cloud route")
        return
    try:
        await gateway.api.async_delete_passcode(
            found[1].lockId, cast("int", msg["passcode_id"])
        )
    except TtlockOpenApiError as exc:
        connection.send_error(cast("int", msg["id"]), ERR_FAILED, str(exc))
        return
    connection.send_result(cast("int", msg["id"]))


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/refresh", vol.Required("mac"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_refresh(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Read the lock now: over Bluetooth, and through the gateway when that fails."""
    found = _find(hass, cast("str", msg["mac"]))
    if found is None:
        connection.send_error(cast("int", msg["id"]), ERR_NOT_FOUND, "Unknown lock")
        return
    entry, key = found
    data = entry.runtime_data
    result = await data.connections[key.lockMac].async_query_state()
    via = "bluetooth"
    if result is not None:
        await data.coordinator.async_refresh()
    elif data.gateway is not None and data.gateway.reaches(key.lockMac):
        via = "gateway"
        await data.gateway.async_refresh()
        if await data.gateway.async_read_state(key) is None:
            via = "none"
    else:
        via = "none"
    connection.send_result(cast("int", msg["id"]), {"via": via})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/options",
        vol.Required("entry_id"): str,
        vol.Optional(CONF_ROUTE): vol.In(ROUTES),
        vol.Optional(CONF_PERMANENT_CONNECTION): bool,
    }
)
@websocket_api.require_admin
@callback
def websocket_options(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Change how commands travel; the entry reloads on its own."""
    entry = hass.config_entries.async_get_entry(cast("str", msg["entry_id"]))
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(cast("int", msg["id"]), ERR_NOT_FOUND, "Unknown entry")
        return
    changed = {
        name: msg[name]
        for name in (CONF_ROUTE, CONF_PERMANENT_CONNECTION)
        if name in msg
    }
    hass.config_entries.async_update_entry(entry, options={**entry.options, **changed})
    connection.send_result(cast("int", msg["id"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/gateway/connect",
        vol.Required("entry_id"): str,
        vol.Required("client_id"): str,
        vol.Required("client_secret"): str,
        vol.Optional("region", default=DEFAULT_REGION): vol.In(list(REGIONS)),
        vol.Optional("username"): str,
        vol.Optional("password"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_connect_gateway(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Sign in to the Open API and keep the session on the entry."""
    entry = hass.config_entries.async_get_entry(cast("str", msg["entry_id"]))
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(cast("int", msg["id"]), ERR_NOT_FOUND, "Unknown entry")
        return
    username = cast("str | None", msg.get("username") or entry.data.get("username"))
    password = cast("str | None", msg.get("password") or entry.data.get("password"))
    if not username or not password:
        connection.send_error(cast("int", msg["id"]), "need_account", "Account needed")
        return
    client_id = cast("str", msg["client_id"]).strip()
    client_secret = cast("str", msg["client_secret"]).strip()
    api = TtlockOpenApi(
        client=get_async_client(hass),
        client_id=client_id,
        client_secret=client_secret,
        region=cast("str", msg["region"]),
    )
    try:
        token = await api.async_login(username, password)
        locks = await api.async_locks()
    except TtlockOpenApiError as exc:
        code = "unreachable" if exc.errcode is None else ERR_FAILED
        connection.send_error(cast("int", msg["id"]), code, str(exc))
        return
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_GATEWAY: {
                "client_id": client_id,
                "client_secret": client_secret,
                "region": msg["region"],
                "token": token,
                "username": username,
            },
        },
    )
    connection.send_result(cast("int", msg["id"]), {"locks": len(locks)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/gateway/disconnect",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.require_admin
@callback
def websocket_disconnect_gateway(
    hass: HomeAssistant, connection: ActiveConnection, msg: Message
) -> None:
    """Forget the Open API session; Bluetooth keeps working."""
    entry = hass.config_entries.async_get_entry(cast("str", msg["entry_id"]))
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(cast("int", msg["id"]), ERR_NOT_FOUND, "Unknown entry")
        return
    data = {name: value for name, value in entry.data.items() if name != CONF_GATEWAY}
    hass.config_entries.async_update_entry(entry, data=data)
    connection.send_result(cast("int", msg["id"]))
