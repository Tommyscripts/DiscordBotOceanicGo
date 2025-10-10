#!/usr/bin/env python3
import sqlite3
import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DB_PATH = os.path.join(ROOT, 'furby_stats.db')
print('DB_PATH:', DB_PATH)
if not os.path.isfile(DB_PATH):
    print('ERROR: DB file not found')
    raise SystemExit(1)
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute('CREATE TABLE IF NOT EXISTS settings (guild_id INTEGER PRIMARY KEY, staff_role_id INTEGER)')
conn.commit()
conn.close()
print('Created/ensured settings table')
