from __future__ import annotations

from custom_components.ttlock_selfhost.history_store import (
    MAX_RECORDS_PER_LOCK,
    TtlockBleHistoryStore,
    async_get_history_store,
)

MAC = "AA:BB:CC:DD:EE:FF"


async def test_records_come_back_newest_first_and_capped(hass) -> None:
    store = await async_get_history_store(hass)
    assert store.recent(MAC) == []
    for number in range(MAX_RECORDS_PER_LOCK + 5):
        store.async_add(MAC, {"type": "unlock", "uid": number})
    recent = store.recent(MAC)
    assert len(recent) == MAX_RECORDS_PER_LOCK
    assert recent[0]["uid"] == MAX_RECORDS_PER_LOCK + 4
    assert recent[-1]["uid"] == 5


async def test_history_survives_a_restart(hass, hass_storage) -> None:
    hass_storage["ttlock_selfhost.history"] = {
        "version": 1,
        "data": {MAC: [{"type": "lock"}]},
    }
    store = TtlockBleHistoryStore(hass)
    await store.async_load()
    assert store.recent(MAC) == [{"type": "lock"}]
