#!/usr/bin/env python3
"""Test migration: create a temp DB with `ghosts_balances`, then run the
migration SQL (same logic as in bot.py) and verify rows end up in
`turkeys_balances` and the legacy table is removed.
"""
import sqlite3
import os
import sys

HERE = os.path.dirname(__file__)
DB_PATH = os.path.join(HERE, 'tmp_migration_test.db')

# Clean up any previous test DB
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Create legacy ghosts table and seed data
cur.execute(
    """
    CREATE TABLE ghosts_balances (
        user_id INTEGER PRIMARY KEY,
        ghosts INTEGER NOT NULL DEFAULT 0
    )
    """
)
cur.execute("INSERT INTO ghosts_balances(user_id, ghosts) VALUES (?, ?)", (111, 5))
cur.execute("INSERT INTO ghosts_balances(user_id, ghosts) VALUES (?, ?)", (222, 10))
conn.commit()

# Now run migration SQL that bot.py uses
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS turkeys_balances (
        user_id INTEGER PRIMARY KEY,
        turkeys INTEGER NOT NULL DEFAULT 0
    )
    """
)

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ghosts_balances'")
if cur.fetchone():
    try:
        # Fast path: rename the table
        cur.execute("ALTER TABLE ghosts_balances RENAME TO turkeys_balances")
        try:
            cur.execute("ALTER TABLE turkeys_balances RENAME COLUMN ghosts TO turkeys")
        except Exception:
            # older SQLite may not support RENAME COLUMN; fallback will handle
            pass
    except Exception:
        # Fallback: copy rows and drop old table
        try:
            cur.execute(
                "INSERT OR IGNORE INTO turkeys_balances(user_id, turkeys) SELECT user_id, ghosts FROM ghosts_balances"
            )
            cur.execute("DROP TABLE IF EXISTS ghosts_balances")
        except Exception as e:
            print("Fallback migration failed:", e)
            conn.close()
            sys.exit(2)

conn.commit()

# Verify results
rows = cur.execute("SELECT user_id, turkeys FROM turkeys_balances ORDER BY user_id").fetchall()
print('turkeys rows:', rows)

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ghosts_balances'")
if cur.fetchone():
    print('ERROR: ghosts_balances still exists')
    conn.close()
    sys.exit(3)

expected = [(111, 5), (222, 10)]
if rows == expected:
    print('Migration SUCCESS')
    conn.close()
    # keep DB for inspection if you want; remove it to be clean
    # os.remove(DB_PATH)
    sys.exit(0)
else:
    print('Migration FAILED: unexpected rows')
    conn.close()
    sys.exit(4)
