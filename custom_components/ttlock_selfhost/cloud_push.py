"""The address TTLock's cloud posts a lock's records to, the moment they happen."""

from __future__ import annotations

import hashlib
import hmac
import json
from functools import partial
from typing import TYPE_CHECKING, cast

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.core import callback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import CONF_GATEWAY, DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant

    from .data import TtlockBleConfigEntry
    from .gateway import TtlockBleGateway
    from .openapi import TtlockBleGatewayConfig


def callback_id(entry: TtlockBleConfigEntry) -> str:
    """Return the entry's webhook id: secret, and the same for as long as the app is."""
    config = cast("TtlockBleGatewayConfig", entry.data[CONF_GATEWAY])
    return hmac.new(
        config["client_secret"].encode(), entry.entry_id.encode(), hashlib.sha256
    ).hexdigest()


def callback_path(entry: TtlockBleConfigEntry) -> str:
    """Return the path of the entry's callback, whatever the host in front of it."""
    return webhook.async_generate_path(callback_id(entry))


def callback_url(hass: HomeAssistant, entry: TtlockBleConfigEntry) -> str | None:
    """Return the callback as the cloud reaches it, `None` with no external address."""
    try:
        base = get_url(hass, allow_internal=False, allow_ip=False)
    except NoURLAvailableError:
        return None
    return f"{base}{callback_path(entry)}"


@callback
def async_register_callback(
    hass: HomeAssistant, entry: TtlockBleConfigEntry, gateway: TtlockBleGateway
) -> CALLBACK_TYPE:
    """Listen for the cloud's pushes; return the way to stop."""

    async def handle(
        _hass: HomeAssistant, _webhook_id: str, request: web.Request
    ) -> web.Response:
        form = await request.post()
        try:
            rows = json.loads(cast("str", form.get("records") or "[]"))
            gateway.async_push(
                int(cast("str", form.get("lockId"))),
                [row for row in rows if isinstance(row, dict)],
            )
        except (TypeError, ValueError) as exc:
            LOGGER.debug("Unreadable TTLock callback: %s", exc)
        # Anything but this body makes the cloud send the same records again.
        return web.Response(text="success")

    webhook_id = callback_id(entry)
    webhook.async_register(
        hass, DOMAIN, "TTLock Selfhost", webhook_id, handle, allowed_methods=["POST"]
    )
    return partial(webhook.async_unregister, hass, webhook_id)
