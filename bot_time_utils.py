from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def local_slot_to_utc(slot: int, tz_name: str, local_date: Optional[date] = None):
    """Convert a user-selected slot (1-24) in given timezone to UTC date and slot.
    Returns (utc_date_str, utc_slot_int, utc_dt, local_dt).
    
    ZoneInfo automatically handles DST for the specific date/time.
    """
    if slot < 1 or slot > 24:
        raise ValueError("slot must be between 1 and 24")
    user_tz = ZoneInfo(tz_name)
    if local_date is None:
        local_date = datetime.now(user_tz).date()
    # ZoneInfo applies the correct DST offset for this specific date/time
    local_dt = datetime(local_date.year, local_date.month, local_date.day, slot - 1, 0, 0, tzinfo=user_tz)
    utc_dt = local_dt.astimezone(timezone.utc)
    utc_date = utc_dt.strftime("%Y-%m-%d")
    utc_slot = utc_dt.hour
    return utc_date, utc_slot, utc_dt, local_dt
