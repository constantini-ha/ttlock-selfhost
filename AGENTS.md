# AGENTS.md

Read `CLAUDE.md` and `CODE_STYLE.md` first: they are the base project's (roquerodrigo/ha-ttlock-ble) and still describe the whole Bluetooth side. This file covers what TTLock Selfhost adds.

## What this fork is

- Domain `ttlock_selfhost`. The Python package `ttlock_ble` is the **SDK from PyPI**, not this integration: never rename its imports. `known-first-party = ["ttlock_ble"]` in `pyproject.toml` keeps the base project's import order so upstream merges stay small.
- Class names keep the `TtlockBle` prefix for the same reason.
- Remote `upstream` is the base project. Merge it rather than copying files.

## The two routes

- **Bluetooth**: unchanged from upstream (`connection.py`, `coordinator.py`).
- **Gateway**: `openapi.py` (TTLock Open API client) and `gateway.py` (one per config entry, on `runtime_data.gateway`). The gateway has no local protocol; this route always crosses TTLock's cloud.
- The Open API **cannot** give the Bluetooth keys, and the app account login **cannot** drive the gateway. That is why an entry holds both: keys from the app login (or typed by hand), plus an optional `gateway` block (`client_id`, `client_secret`, region, token) in `entry.data`.
- `lock.py::_async_send` picks the route from the `route` option: `auto` (Bluetooth, then gateway on `TTLockError`), `bluetooth`, `gateway`. A cloud refusal is re-raised as `TTLockError` so the existing error path handles it. The lock entity exposes `last_route`.
- A lock the cloud says has no gateway (`hasGateway == 0`) is never sent through the cloud. A lock missing from `/v3/lock/list` (a shared eKey) is still tried.
- Gateway state reads wake the lock. `gateway.py` asks for the bolt only when the Bluetooth reading is older than 30 minutes; the cloud's battery only fills in when Bluetooth has none.
- **Cloud push**: `cloud_push.py` registers one webhook per entry with a gateway; TTLock posts new records to it (`notifyType=1`, form-encoded, `records` is a JSON string) and must be answered with the raw body `success` or it sends them again. The webhook id is an HMAC of the entry id keyed by `client_secret`: secret, stable, nothing to store or migrate. Never name the module `callback.py`; the submodule attribute shadows `homeassistant.core.callback` in `__init__.py`.
- `cloud_record.py` turns a cloud record into a `TtlockBleCloudLogEntry` and sends it on `log_signal`, so the event entity, door sensor, last-unlock sensor and history need no second path. Cloud record types differ from `LogOperate` below 29 and agree from 29 up. A door code (`keyboardPwd` of a passcode record) is dropped there; the cloud's `username` is the only name a gateway-only lock has.
- A push is ignored for a lock Bluetooth hears (it already reports everything, and both would double the events). A record moves the bolt only when it is live: uploaded (`serverDate`) within 5 minutes of the lock's own stamp, because the clock of a lock Bluetooth never reaches is set by nobody, and not older than the last record taken.
- These locks write no record when they lock themselves again, so after a push that leaves the bolt not locked `gateway.py` reads it 20 s later and once more at 120 s. Each read wakes the lock; do not turn this into polling.
- A renewed token is stored on the entry **without** reloading it (`async_consume_token_update`); every other entry update reloads.

## Panel

- `panel.py` registers the websocket commands always, and the sidebar panel only when `http` and `panel_custom` are loaded (tests run without the frontend, so they are `after_dependencies`, not `dependencies`).
- Frontend is plain custom elements in `frontend/`, served under the integration version. Strings live in `frontend/i18n.js` in **en, pt-BR and es**; the three tables must have the same keys. Config-flow strings live in `translations/` (en, pt-BR, es, he).
- All commands are admin-only: they return door codes.
- Passcodes never reach entities or the local history (`history_store.py` gets what the resolver already masked). The panel shows cloud passcodes masked until the eye is pressed.
- A custom passcode goes over Bluetooth first (needs an admin key) and is then reported to the cloud with `addType=1` so the app lists it; out of range it goes through the gateway with `addType=2`. Generated passcodes come from the cloud and need no gateway hardware.
- Schemas use `probatio as vol`, like the rest of the project.

## Dashboard card

- `frontend/ttlock-selfhost-doors-card.js` (`custom:ttlock-selfhost-doors-card`), loaded with `add_extra_js_url` next to the panel. No config lists every lock of the integration; `entities` and `title` are optional.
- **The tiles are built once and repainted in place** (`_tile` builds, `_paint` updates). Rebuilding the DOM on every state change, as 2026.11.2 did, puts a new door straight in its final pose and the swing never plays.
- The door is two stacked `<svg>`: the doorway and the leaf. The leaf swings with `perspective() rotateY()` on the `<svg>` element itself, because 3D transforms do not work on elements inside an SVG. It uses transitions only, never keyframes: a keyframe animation that ends makes the next transition start from the resting pose and the door jumps.
- Owner's taste (23/11/2026): no yellow in the confirm dialog. The dialog and the door leaf use `--primary-color`; amber stays only as the unlocked mark on the tile (badge, label, border).
- The panel's "Add to dashboard" button (`_toDashboard`, a small icon at the right of the top bar on each lock's home screen; the owner found a full-width button too big) is **per lock, never all at once** (owner, 23/11/2026). It walks every view of the default dashboard first (`cardsIn`) and adds nothing when a doors card already shows that lock (no `entities` list, or the lock is in it). An existing doors card with a fixed list takes the lock, so doors stay side by side; otherwise a new card with only that lock goes to the first view. An automatic dashboard has no views to write to and gets the `dashboard_auto` message.
- It reads only `hass.states`, `hass.entities` and `hass.devices`, never the admin-only websocket commands, so non-admin users of a dashboard can use it.
- Owner's rule (22/11/2026): **opening asks for confirmation, locking does not.** The confirmation is a native `<dialog>` appended to `<body>` so no card transform clips it.

## Checks

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy custom_components/ttlock_selfhost && uv run pytest
```

Coverage gate is 90%. The panel has no JS test runner; check it in a browser with a fake `hass` (states, `callWS`, `callService`) at 390 px and desktop width.

## Never

- Never send lock/unlock to a real lock while testing; the owner tests on their network.
- Never log or print tokens, `client_secret`, AES keys or passcodes.

## Brand

`brand/icon.svg` is the family logo (indigo-to-blue tile, white house, cyan pins) with a padlock in place of Tuya Selfhost's ring. The PNGs in `custom_components/ttlock_selfhost/brand/` are rendered from it; change the SVG and re-render, never edit a PNG.
