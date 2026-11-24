# TTLock Selfhost

Home Assistant integration for TTLock smart locks that works **by Bluetooth, through the gateway, or both**.

- **Bluetooth** — lock, unlock, state, battery, records and credential lists straight from the lock, inside the house, with Home Assistant's own Bluetooth radio or an ESPHome proxy.
- **Gateway** — when the lock is out of Bluetooth range, the same commands go through TTLock's official Open API and your TTLock gateway (G2 and the like) or the lock's built-in Wi-Fi.
- **Hybrid** — by default Bluetooth goes first and the gateway takes over when Bluetooth fails. You can pin either route per entry.
- **A panel laid out like the phone app** — one big button (touch to unlock, hold to lock), then eKeys, Passcodes, Cards, Fingerprints, Records, Gateway and Settings. English, Portuguese (Brazil) and Spanish.

> The gateway only talks to TTLock's cloud; there is no local protocol to reach it. "Gateway route" therefore always means the TTLock cloud. The Bluetooth route never leaves your network.

## Install

HACS → Custom repositories → `https://github.com/constantini-ha/ttlock-selfhost` (Integration) → install → restart Home Assistant.

## Set up

1. **Settings → Devices & services → Add integration → TTLock Selfhost.**
2. **Sign in to a TTLock account** (the one you use in the TTLock app). The account is used once to download each lock's Bluetooth keys. TTLock may email a verification code the first time. Or **enter a lock key manually** for a lock that never touched the cloud.
3. Open **TTLock Selfhost** in the sidebar.

### Gateway route (optional)

1. Create an application at <https://euopen.ttlock.com> (or <https://open.ttlock.com>) and wait for it to be approved.
2. In the panel: **Gateway → paste `client_id` and `client_secret` → Connect.**
3. In the TTLock app, turn on **Remote unlock** in the lock's settings (error `-4043` means it is off).

| What | Bluetooth only | With the gateway connected |
| --- | --- | --- |
| Lock / unlock, state, battery | yes | yes, also out of range |
| Records | read from the lock, kept locally | from the cloud, with names |
| Passcodes | list (masked), custom passcode with an admin key | list, generate, custom, delete |
| Cards, fingerprints | what the lock listed | names and validity |
| eKeys | no | list |

#### Know the moment a door opens

A lock that only the gateway reaches is otherwise asked for its state every 30 minutes. To hear about each unlock, lock and door opening within seconds:

1. In the panel, open **Gateway** and copy the address under **Notice when the door opens**.
2. At <https://euopen.ttlock.com> (or <https://open.ttlock.com>), open your application and paste it in **Callback URL**.

Home Assistant has to be reachable from the internet at that address (set the external URL in **Settings → System → Network**). Keep the address private: TTLock does not sign what it sends, so whoever has it can make a door look open or closed. It cannot operate a lock.

## Dashboard card

```yaml
type: custom:ttlock-selfhost-doors-card
```

One animated door per lock. Tapping a locked door asks before opening; tapping an open one locks it at once. Optional: `title`, and `entities` to pick the locks.

## Development

```bash
uv sync --all-groups
uv run ruff format --check . && uv run ruff check . && uv run mypy custom_components/ttlock_selfhost && uv run pytest
```

See `AGENTS.md` for how the pieces fit.

## Credits

The Bluetooth side is [roquerodrigo/ha-ttlock-ble](https://github.com/roquerodrigo/ha-ttlock-ble) and its [`ttlock-ble`](https://github.com/roquerodrigo/ttlock-ble) library (MIT). This project adds the gateway route, the hybrid command path and the panel. The Open API calls were written against TTLock's public documentation.

Not affiliated with TTLock / Sciener.
