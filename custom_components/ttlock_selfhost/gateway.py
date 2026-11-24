"""The gateway route of one config entry: commands and state through the cloud."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, TypedDict, cast

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.httpx_client import get_async_client

from .cloud_record import bolt_of, log_entry_of
from .connection import log_signal
from .const import CONF_GATEWAY, LOGGER
from .lock_command import TtlockBleLockCommand
from .openapi import (
    Json,
    TtlockBleGatewayConfig,
    TtlockBleGatewayToken,
    TtlockOpenApi,
    TtlockOpenApiError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import CALLBACK_TYPE, HomeAssistant

    from ttlock_ble import VirtualKey

    from .coordinator import TtlockBleDataUpdateCoordinator
    from .data import TtlockBleConfigEntry
    from .record_echo import TtlockBleRecordEcho

REFRESH_INTERVAL = timedelta(minutes=30)
# A Bluetooth reading younger than this needs no question to the gateway,
# which wakes the lock to answer.
FRESH_SECONDS = 30 * 60
# A lock that locks itself again writes no record, so the bolt is asked for
# this long after a push, and once more if it was still open.
RELOCK_READ_DELAYS = (20.0, 120.0)
# A record uploaded this close to when the lock stamped it happened just now.
# Wide, because nothing sets the clock of a lock Bluetooth never reaches.
LIVE_SECONDS = 300


class TtlockBleGatewayLink(TypedDict):
    """What the cloud last said about one lock's gateway route."""

    has_gateway: bool | None
    battery: int | None
    gateways: list[dict[str, object]]
    error: str | None


class TtlockBleGateway:
    """Reach the entry's locks through TTLock's cloud and their gateway."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: TtlockBleConfigEntry,
        coordinator: TtlockBleDataUpdateCoordinator,
        keys: list[VirtualKey],
        echo: TtlockBleRecordEcho,
    ) -> None:
        """Build the client from what the entry stores."""
        config = cast("TtlockBleGatewayConfig", entry.data[CONF_GATEWAY])
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._keys = keys
        self._echo = echo
        self._links: dict[str, TtlockBleGatewayLink] = {}
        self._token_stored = False
        self._watches: dict[str, CALLBACK_TYPE] = {}
        self.pushed_at: float | None = None
        self.api = TtlockOpenApi(
            client=get_async_client(hass),
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            region=config["region"],
            token=config["token"],
            on_token=self._async_store_token,
        )

    @callback
    def link(self, mac: str) -> TtlockBleGatewayLink | None:
        """Return what is known about a lock's gateway route."""
        return self._links.get(mac)

    @callback
    def reaches(self, mac: str) -> bool:
        """Report whether a command through the cloud is worth sending."""
        link = self._links.get(mac)
        return link is None or link["has_gateway"] is not False

    @callback
    def async_consume_token_update(self) -> bool:
        """Tell, once, that the entry changed only because the session renewed."""
        stored, self._token_stored = self._token_stored, False
        return stored

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Refresh now and every `REFRESH_INTERVAL`; return the way to stop."""
        self._entry.async_create_background_task(
            self._hass, self.async_refresh(), "ttlock_selfhost.gateway_refresh"
        )
        stop_refresh = async_track_time_interval(
            self._hass, self.async_refresh, REFRESH_INTERVAL
        )

        @callback
        def stop() -> None:
            stop_refresh()
            for mac in list(self._watches):
                self._watches.pop(mac)()

        return stop

    @callback
    def async_push(self, lock_id: int, rows: list[Json]) -> None:
        """Take the records the cloud just pushed for one lock."""
        self.pushed_at = time.time()
        key = next((key for key in self._keys if key.lockId == lock_id), None)
        LOGGER.debug(
            "Cloud pushed %d record(s) of types %s for %s",
            len(rows),
            [row.get("recordType") for row in rows],
            "an unknown lock" if key is None else key.lockMac,
        )
        if key is None or not rows:
            return
        mac = key.lockMac
        rows = sorted(rows, key=_when)
        level = rows[-1].get("electricQuantity")
        # A backlog uploaded late says what happened, not how the bolt is now.
        bolt = next(
            (row for row in reversed(rows) if bolt_of(row) is not None and _live(row)),
            None,
        )
        self._coordinator.async_apply_cloud_state(
            mac,
            locked=None if bolt is None else bolt_of(bolt),
            battery=level if isinstance(level, int) else None,
            replace_battery=True,
        )
        battery = self._coordinator.async_battery(mac)
        for row in rows:
            entry = log_entry_of(row, battery=battery)
            # Bluetooth, when it hears the lock, reads the same record off it.
            if entry is not None and self._echo.first(mac, entry):
                async_dispatcher_send(self._hass, log_signal(mac), entry)
        # A lock or unlock that was not taken leaves the bolt in doubt.
        self._async_watch_bolt(
            key, ask=bolt is None and any(bolt_of(row) is not None for row in rows)
        )

    @callback
    def _async_watch_bolt(self, key: VirtualKey, *, ask: bool) -> None:
        cancel = self._watches.pop(key.lockMac, None)
        if cancel is not None:
            cancel()
        if ask or not self._coordinator.async_locked(key.lockMac):
            self._async_arm_watch(key, RELOCK_READ_DELAYS, ask=ask)

    @callback
    def _async_arm_watch(
        self, key: VirtualKey, delays: tuple[float, ...], *, ask: bool = False
    ) -> None:
        mac = key.lockMac

        async def read(_now: datetime) -> None:
            self._watches.pop(mac, None)
            # Bluetooth or a later record may have told it already.
            if not ask and self._coordinator.async_locked(mac):
                return
            still_open = await self.async_read_state(key) is False
            # A push that came in during the read has already armed its own.
            if still_open and delays[1:] and mac not in self._watches:
                self._async_arm_watch(key, delays[1:])

        self._watches[mac] = async_call_later(self._hass, delays[0], read)

    async def async_command(
        self, key: VirtualKey, action: TtlockBleLockCommand
    ) -> None:
        """Send lock or unlock through the gateway."""
        if action is TtlockBleLockCommand.LOCK:
            await self.api.async_lock(key.lockId)
        else:
            await self.api.async_unlock(key.lockId)

    async def async_read_state(self, key: VirtualKey) -> bool | None:
        """Ask the lock for its bolt through the gateway and publish the answer."""
        try:
            locked = await self.api.async_open_state(key.lockId)
        except TtlockOpenApiError as exc:
            LOGGER.debug("Gateway state read failed for %s: %s", key.lockMac, exc)
            self._note_error(key.lockMac, exc)
            return None
        if locked is not None:
            self._coordinator.async_apply_cloud_state(key.lockMac, locked=locked)
        return locked

    async def async_refresh(self, _now: datetime | None = None) -> None:
        """Read the account's lock list, then the bolts Bluetooth has not told."""
        try:
            rows = {row.get("lockId"): row for row in await self.api.async_locks()}
        except TtlockOpenApiError as exc:
            LOGGER.warning("TTLock cloud lock list failed: %s", exc)
            for key in self._keys:
                self._note_error(key.lockMac, exc)
            return
        for key in self._keys:
            row = rows.get(key.lockId)
            await self._async_refresh_lock(key, row)

    async def _async_refresh_lock(
        self, key: VirtualKey, row: dict[str, object] | None
    ) -> None:
        mac = key.lockMac
        battery = row.get("electricQuantity") if row else None
        link: TtlockBleGatewayLink = {
            # A lock shared with this account is absent from the list.
            "has_gateway": None if row is None else row.get("hasGateway") == 1,
            "battery": battery if isinstance(battery, int) else None,
            "gateways": [],
            "error": None,
        }
        self._links[mac] = link
        if link["battery"] is not None:
            self._coordinator.async_apply_cloud_state(mac, battery=link["battery"])
        if link["has_gateway"] is False:
            return
        try:
            link["gateways"] = await self.api.async_gateways_of(key.lockId)
        except TtlockOpenApiError as exc:
            self._note_error(mac, exc)
            return
        if self._coordinator.async_state_age(mac) > FRESH_SECONDS:
            await self.async_read_state(key)

    def _note_error(self, mac: str, exc: TtlockOpenApiError) -> None:
        link = self._links.setdefault(
            mac, {"has_gateway": None, "battery": None, "gateways": [], "error": None}
        )
        link["error"] = str(exc) if exc.errcode is None else f"{exc} ({exc.errcode})"

    @callback
    def _async_store_token(self, token: TtlockBleGatewayToken) -> None:
        """Keep a renewed session on the entry, without reloading it."""
        config = {**self._entry.data[CONF_GATEWAY], "token": token}
        self._token_stored = True
        self._hass.config_entries.async_update_entry(
            self._entry, data={**self._entry.data, CONF_GATEWAY: config}
        )


def _when(row: Json) -> int:
    stamp = row.get("lockDate")
    return stamp if isinstance(stamp, int) else 0


def _live(row: Json) -> bool:
    uploaded = row.get("serverDate")
    reference = uploaded if isinstance(uploaded, int) else time.time() * 1000
    return reference - _when(row) < LIVE_SECONDS * 1000
