#!/usr/bin/env python3
import sys
import os
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Ensure repo root is on sys.path so we can import top-level modules
repo_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, repo_root)

from bot_time_utils import local_slot_to_utc


def main():
    slot = 1
    tzname = 'Europe/London'
    local_d = date(2026,4,7)
    utc_date, utc_slot, utc_dt, local_dt = local_slot_to_utc(slot, tzname, local_d)
    print("Computed:", utc_date, utc_slot, utc_dt.isoformat(), local_dt.isoformat())

    viewer_tz = ZoneInfo(tzname)
    local_today = local_d

    local_start = datetime(local_today.year, local_today.month, local_today.day, 0, 0, 0, tzinfo=viewer_tz)
    local_end = local_start + timedelta(days=1)
    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_end.astimezone(timezone.utc)
    utc_date_start = utc_start.strftime("%Y-%m-%d")
    utc_date_end = (utc_end - timedelta(seconds=1)).strftime("%Y-%m-%d")

    print("Viewer local range:", local_start.isoformat(), "->", local_end.isoformat())
    print("UTC date range:", utc_date_start, "->", utc_date_end)

    rows = [(utc_date, utc_slot, 1234, 'game', tzname, slot)]

    slots = {i: [] for i in range(24)}
    for row in rows:
        row_date, utc_slot_, user_id, game, local_tz, local_slot = row
        slot_utc = datetime.strptime(f"{row_date} {utc_slot_:02d}:00:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        slot_local_for_viewer = slot_utc.astimezone(viewer_tz)
        print("Row:", row_date, utc_slot_, "slot_utc:", slot_utc.isoformat(), "slot_local:", slot_local_for_viewer.isoformat())
        if slot_local_for_viewer.date() != local_today:
            print(" -> not in local today")
            continue
        slots[slot_local_for_viewer.hour].append((user_id,game,local_tz,slot_utc))

    for hour in range(24):
        entries = slots[hour]
        if entries:
            print("Hour", hour, "slot_label", hour+1, "entries:", entries)


if __name__=='__main__':
    main()
