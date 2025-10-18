import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(__file__))
# Use same DB override mechanism as the bot
DB_PATH = os.getenv('FURBY_DB_PATH') or os.path.join(ROOT, 'furby_stats.db')

def column_exists(conn, table, column):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall()
    return any(r[1] == column for r in rows)

def main():
    if not os.path.isfile(DB_PATH):
        print('DB not found:', DB_PATH)
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        for col in ('mod_ban_role_id', 'mod_kick_role_id', 'mod_mute_role_id'):
            if not column_exists(conn, 'settings', col):
                try:
                    print('Adding column', col)
                    conn.execute(f"ALTER TABLE settings ADD COLUMN {col} INTEGER")
                except Exception as e:
                    print('Failed to add', col, e)
        # add mod_log table if missing
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mod_log'")
        if not cur.fetchone():
            cur.execute('''CREATE TABLE mod_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                action TEXT,
                target_id INTEGER,
                moderator_id INTEGER,
                reason TEXT,
                created_at TEXT
            )''')
        conn.commit()
    finally:
        conn.close()

if __name__ == '__main__':
    main()
