#!/usr/bin/env python3
import sys
import os
from datetime import date

# Ensure repo root is on sys.path so we can import top-level modules
repo_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, repo_root)

# Run the async analysis report
import json
try:
    with open('tools/async_analysis.json', 'r', encoding='utf-8') as f:
        report = json.load(f)
except Exception as e:
    print('Could not load async_analysis.json:', e)
    sys.exit(2)

candidates = report.get('candidates', [])
if candidates:
    print('Async->sync candidates remain:')
    for c in candidates:
        print(f" - {c['file']}:{c['lineno']} {c['name']}")
    sys.exit(2)
else:
    print('No async->sync candidates found. OK.')

# Tests for bot_time_utils.local_slot_to_utc (moved to oceanic_bot.utils)
print('\nRunning bot_time_utils tests...')
from oceanic_bot.utils import local_slot_to_utc

# Basic sanity tests
# Stronger checks with expected outputs for known cases
cases = [
    # slot, tzname, local_date, expected_utc_date, expected_utc_slot
    (1, 'Etc/UTC', date(2026,4,7), '2026-04-07', 0),
    (24, 'Etc/UTC', date(2026,4,7), '2026-04-07', 23),
    (12, 'Europe/Madrid', date(2026,4,7), '2026-04-07', 9),
]

for slot, tzname, d, expected_date, expected_slot in cases:
    try:
        utc_date, utc_slot, utc_dt, local_dt = local_slot_to_utc(slot, tzname, d)
    except Exception as e:
        print(f'FAIL: local_slot_to_utc({slot},{tzname},{d}) raised {e}')
        sys.exit(2)
    # basic type checks
    assert isinstance(utc_date, str)
    assert isinstance(utc_slot, int) and 0 <= utc_slot < 24
    assert utc_dt.tzinfo is not None
    assert local_dt.tzinfo is not None
    # concrete value checks to avoid false positives
    assert utc_date == expected_date, f"expected utc_date {expected_date} but got {utc_date}"
    assert utc_slot == expected_slot, f"expected utc_slot {expected_slot} but got {utc_slot}"
    print(f'PASS: slot {slot} {tzname} -> {utc_date} slot {utc_slot}')

# invalid slot should raise
try:
    local_slot_to_utc(0, 'Etc/UTC')
    print('FAIL: expected ValueError for slot 0')
    sys.exit(2)
except ValueError:
    print('PASS: invalid slot 0 raised ValueError')

print('\nAll tests passed.')
sys.exit(0)
