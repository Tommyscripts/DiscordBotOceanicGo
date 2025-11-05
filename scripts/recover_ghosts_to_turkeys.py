#!/usr/bin/env python3
"""Safely recover existing `ghosts_balances` into `turkeys_balances`.
- Respects FURBY_DB_PATH env var, otherwise ./furby_stats.db in repo root.
- Creates a timestamped backup copy before modifying.
- Copies rows with INSERT OR REPLACE so existing turkeys balances are preserved
  (it will overwrite if conflict; adjust behavior below if you prefer additive).
- Leaves `ghosts_balances` intact so you can inspect/verify before removing it.
"""
import os, shutil, sqlite3, time, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DB_PATH = os.getenv('FURBY_DB_PATH') or os.path.join(ROOT, 'furby_stats.db')

if not os.path.isfile(DB_PATH):
    print('ERROR: DB not found at', DB_PATH)
    sys.exit(1)

bak = DB_PATH + '.bak.' + time.strftime('%Y%m%dT%H%M%S')
shutil.copy2(DB_PATH, bak)
print('Backup created:', bak)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Ensure turkeys table exists
cur.execute('''
CREATE TABLE IF NOT EXISTS turkeys_balances (
    user_id INTEGER PRIMARY KEY,
    turkeys INTEGER NOT NULL DEFAULT 0
)
''')
conn.commit()

# Check if legacy ghosts table exists
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ghosts_balances'")
if not cur.fetchone():
    print('No ghosts_balances table found. Nothing to recover.')
    conn.close()
    sys.exit(0)

# Copy rows: if a user already has turkeys, overwrite with ghosts value so we recover exact prior amounts.
# If you prefer to add instead (sum), change the SQL to DO UPDATE SET turkeys = turkeys + excluded.turkeys
print('Copying rows from ghosts_balances -> turkeys_balances (overwrite if present)')
cur.execute("INSERT OR REPLACE INTO turkeys_balances(user_id, turkeys) SELECT user_id, ghosts FROM ghosts_balances")
conn.commit()

# Show counts and samples
count_t = cur.execute('SELECT COUNT(*) FROM turkeys_balances').fetchone()[0]
count_g = cur.execute('SELECT COUNT(*) FROM ghosts_balances').fetchone()[0]
print(f'Rows in turkeys_balances: {count_t}')
print(f'Rows in ghosts_balances: {count_g}')
print('\nSample turkeys_balances (up to 20):')
for r in cur.execute('SELECT user_id, turkeys FROM turkeys_balances ORDER BY user_id LIMIT 20').fetchall():
    print(' ', r)

conn.close()
print('\nRecovery complete. DB backed up at:', bak)
print('If everything looks good, you may optionally drop ghosts_balances later.')
