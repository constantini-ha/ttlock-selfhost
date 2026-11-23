"""The recent operation records of each lock, kept for the panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.singleton import singleton
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.history"
SAVE_DELAY_SECONDS = 10
MAX_RECORDS_PER_LOCK = 300

type TtlockBleHistoryRecord = dict[str, str | int | bool | None]


class TtlockBleHistoryStore:
    """
    Keep what the lock's own log said, newest last.

    The event entity fires each record once and Home Assistant's recorder
    purges it; a lock used only over Bluetooth has no cloud to ask again.
    Passcodes never reach a record here: the resolver withholds them.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Bind the history to HA's storage helper."""
        self._store: Store[dict[str, list[TtlockBleHistoryRecord]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._records: dict[str, list[TtlockBleHistoryRecord]] = {}

    async def async_load(self) -> None:
        """Read the persisted history, tolerating a missing or empty file."""
        self._records = dict(await self._store.async_load() or {})

    def recent(self, mac: str) -> list[TtlockBleHistoryRecord]:
        """Return the records of `mac`, newest first."""
        return list(reversed(self._records.get(mac, [])))

    def async_add(self, mac: str, record: TtlockBleHistoryRecord) -> None:
        """Append one record, dropping the oldest past the cap."""
        records = self._records.setdefault(mac, [])
        records.append(record)
        del records[:-MAX_RECORDS_PER_LOCK]
        self._store.async_delay_save(lambda: dict(self._records), SAVE_DELAY_SECONDS)


STORE_KEY: HassKey[TtlockBleHistoryStore] = HassKey(f"{DOMAIN}_history_store")


@singleton(STORE_KEY, async_=True)
async def async_get_history_store(hass: HomeAssistant) -> TtlockBleHistoryStore:
    """Return the one history this Home Assistant instance shares."""
    store = TtlockBleHistoryStore(hass)
    await store.async_load()
    return store
