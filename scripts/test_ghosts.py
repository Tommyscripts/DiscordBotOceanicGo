#!/usr/bin/env python3
"""Prueba rápida de la BD de ghosts y settings.
No importa `bot.py` para evitar efectos secundarios; usa SQL directo en `furby_stats.db`.
"""
import sqlite3
import os
import random

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Respect FURBY_DB_PATH environment variable if present, otherwise use repo-local DB
DB_PATH = os.getenv('FURBY_DB_PATH') or os.path.join(ROOT, 'furby_stats.db')

print('DB_PATH:', DB_PATH)
if not os.path.isfile(DB_PATH):
    print('ERROR: DB file not found. Run the bot once to create the DB or check path.')
    raise SystemExit(1)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print('\nTables in DB:')
for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
    print(' -', row[0])

# Test settings (staff role)
print('\n--- Testing settings (staff_role) ---')
TEST_GUILD_ID = 999999999999
TEST_ROLE_ID = 123456789012

print('Setting staff_role_id ->', TEST_ROLE_ID)
cur.execute("INSERT INTO settings(guild_id, staff_role_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET staff_role_id = ?", (TEST_GUILD_ID, TEST_ROLE_ID, TEST_ROLE_ID))
conn.commit()
row = cur.execute("SELECT staff_role_id FROM settings WHERE guild_id = ?", (TEST_GUILD_ID,)).fetchone()
print('Read back staff_role_id:', row[0] if row else None)

print('Clearing staff_role (setting to NULL)')
cur.execute("INSERT INTO settings(guild_id, staff_role_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET staff_role_id = NULL", (TEST_GUILD_ID, None))
conn.commit()
row = cur.execute("SELECT staff_role_id FROM settings WHERE guild_id = ?", (TEST_GUILD_ID,)).fetchone()
print('Read back staff_role_id after clear:', row[0] if row and row[0] is not None else None)

# Test ghosts balances
print('\n--- Testing ghosts balances ---')
TEST_USER_ID = 888888888888

print('Adding 10 ghosts to user', TEST_USER_ID)
cur.execute("INSERT INTO ghosts_balances(user_id, ghosts) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET ghosts = ghosts + ?", (TEST_USER_ID, 10, 10))
conn.commit()
row = cur.execute("SELECT ghosts FROM ghosts_balances WHERE user_id = ?", (TEST_USER_ID,)).fetchone()
print('Balance after +10:', row[0] if row else 0)

print('Setting ghosts to 42 for user', TEST_USER_ID)
cur.execute("INSERT INTO ghosts_balances(user_id, ghosts) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET ghosts = ?", (TEST_USER_ID, 42, 42))
conn.commit()
row = cur.execute("SELECT ghosts FROM ghosts_balances WHERE user_id = ?", (TEST_USER_ID,)).fetchone()
print('Balance after set 42:', row[0] if row else 0)

print('Subtracting 5 ghosts')
cur.execute("INSERT INTO ghosts_balances(user_id, ghosts) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET ghosts = ghosts + ?", (TEST_USER_ID, -5, -5))
conn.commit()
row = cur.execute("SELECT ghosts FROM ghosts_balances WHERE user_id = ?", (TEST_USER_ID,)).fetchone()
print('Balance after -5:', row[0] if row else 0)

print('\nTest finished. NOTE: Test rows were written to the DB (guild_id and user_id used).')
conn.close()
