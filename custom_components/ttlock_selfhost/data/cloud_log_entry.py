"""An operation record as TTLock's cloud pushes it."""

from __future__ import annotations

from dataclasses import dataclass

from ttlock_ble import LogEntry


@dataclass(frozen=True, slots=True)
class TtlockBleCloudLogEntry(LogEntry):
    """A record the cloud pushed, which also carries the name behind it."""

    username: str | None = None
