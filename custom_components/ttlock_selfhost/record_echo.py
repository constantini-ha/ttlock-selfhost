"""Tell a record that Bluetooth and the cloud both deliver from one only one did."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from ttlock_ble import LogEntry

# Records remembered per lock; the two routes are seconds apart, not hours.
MEMORY = 64


class TtlockBleRecordEcho:
    """Remember what each lock's records already said, whichever route told it."""

    def __init__(self) -> None:
        """Start with nothing told."""
        self._told: dict[str, deque[tuple[int, datetime]]] = {}

    def first(self, mac: str, entry: LogEntry) -> bool:
        """Report whether `entry` is news, and remember it so the next copy is not."""
        if entry.operate_date is None:
            return True
        mark = (int(entry.record_type), entry.operate_date.replace(microsecond=0))
        told = self._told.setdefault(mac, deque(maxlen=MEMORY))
        if mark in told:
            return False
        told.append(mark)
        return True
