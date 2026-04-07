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

# Tests for bot_time_utils.local_slot_to_utc
print('\nRunning bot_time_utils tests...')
from bot_time_utils import local_slot_to_utc

# Basic sanity tests
cases = [
    (1, 'Etc/UTC', date(2026,4,7)),
    (24, 'Etc/UTC', date(2026,4,7)),
    (12, 'Europe/Madrid', date(2026,4,7)),
]

for slot, tzname, d in cases:
    try:
        utc_date, utc_slot, utc_dt, local_dt = local_slot_to_utc(slot, tzname, d)
    except Exception as e:
        print(f'FAIL: local_slot_to_utc({slot},{tzname},{d}) raised {e}')
        sys.exit(2)
    # basic checks
    assert isinstance(utc_date, str)
    assert isinstance(utc_slot, int) and 0 <= utc_slot < 24
    assert utc_dt.tzinfo is not None
    assert local_dt.tzinfo is not None
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
