"""What a cloud record means, and the same record as the lock's own log tells it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ttlock_ble import LogOperate

from .credential_resolver import PASSCODE_RECORD_TYPES
from .data import TtlockBleCloudLogEntry

if TYPE_CHECKING:
    from .openapi import Json

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

# The cloud renumbers the lock's records below this; from here up the two agree.
SHARED_FROM = 29

_LOG_TYPES: dict[int, int] = {
    1: LogOperate.MOBILE_UNLOCK,
    4: LogOperate.KEYBOARD_PASSWORD_UNLOCK,
    7: LogOperate.IC_UNLOCK_SUCCEED,
    8: LogOperate.FR_UNLOCK_SUCCEED,
    9: LogOperate.BONG_UNLOCK,
    10: LogOperate.OPERATE_KEY_UNLOCK,
    11: LogOperate.OPERATE_BLE_LOCK,
    12: LogOperate.GATEWAY_UNLOCK,
    46: LogOperate.OPERATE_KEY_UNLOCK,
    47: LogOperate.OPERATE_KEY_LOCK,
}

_FAILED_LOG_TYPES: dict[int, int] = {
    4: LogOperate.ERROR_PASSWORD_UNLOCK,
    7: LogOperate.IC_UNLOCK_FAILED,
    8: LogOperate.FR_UNLOCK_FAILED,
}


def bolt_of(row: Json) -> bool | None:
    """Return whether a cloud record left the bolt locked, `None` if it says nothing."""
    code = row.get("recordType")
    kind = CLOUD_RECORDS.get(code, ("other", None))[0] if isinstance(code, int) else ""
    if kind not in ("lock", "unlock") or not row.get("success", 1):
        return None
    return kind == "lock"


def _log_type(code: int, *, success: bool) -> int | None:
    if not success:
        return _FAILED_LOG_TYPES.get(code)
    if code in _LOG_TYPES:
        return _LOG_TYPES[code]
    return code if code >= SHARED_FROM else None


def log_entry_of(row: Json, *, battery: int) -> TtlockBleCloudLogEntry | None:
    """Translate a cloud record into the entry the lock's own log would have given."""
    code, stamp = row.get("recordType"), row.get("lockDate")
    if not isinstance(code, int) or not isinstance(stamp, int):
        return None
    record_type = _log_type(code, success=bool(row.get("success", 1)))
    if record_type is None:
        return None
    level, secret, name = (
        row.get("electricQuantity"),
        row.get("keyboardPwd"),
        row.get("username"),
    )
    return TtlockBleCloudLogEntry(
        record_number=-1,
        record_type=record_type,
        # The lock's own log is in wall time, without a zone.
        operate_date=dt_util.as_local(dt_util.utc_from_timestamp(stamp / 1000)).replace(
            tzinfo=None
        ),
        lock_battery=level if isinstance(level, int) else battery,
        # A door code stays out; a card or fingerprint number only identifies.
        password=secret
        if isinstance(secret, str) and record_type not in PASSCODE_RECORD_TYPES
        else None,
        username=name if isinstance(name, str) and name else None,
    )
