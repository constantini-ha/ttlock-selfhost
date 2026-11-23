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
- A renewed token is stored on the entry **without** reloading it (`async_consume_token_update`); every other entry update reloads.

## Panel

- `panel.py` registers the websocket commands always, and the sidebar panel only when `http` and `panel_custom` are loaded (tests run without the frontend, so they are `after_dependencies`, not `dependencies`).
- Frontend is plain custom elements in `frontend/`, served under the integration version. Strings live in `frontend/i18n.js` in **en, pt-BR and es**; the three tables must have the same keys. Config-flow strings live in `translations/` (en, pt-BR, es, he).
- All commands are admin-only: they return door codes.
- Passcodes never reach entities or the local history (`history_store.py` gets what the resolver already masked). The panel shows cloud passcodes masked until the eye is pressed.
- A custom passcode goes over Bluetooth first (needs an admin key) and is then reported to the cloud with `addType=1` so the app lists it; out of range it goes through the gateway with `addType=2`. Generated passcodes come from the cloud and need no gateway hardware.
- Schemas use `probatio as vol`, like the rest of the project.

## Checks

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy custom_components/ttlock_selfhost && uv run pytest
```

Coverage gate is 90%. The panel has no JS test runner; check it in a browser with a fake `hass` (states, `callWS`, `callService`) at 390 px and desktop width.

## Never

- Never send lock/unlock to a real lock while testing; the owner tests on their network.
- Never log or print tokens, `client_secret`, AES keys or passcodes.
