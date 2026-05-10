import sqlite3
import os

db_path = 'instance/vui_academia.db'
if not os.path.exists(db_path):
    db_path = 'vui_academia.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'student'")
    print("Added 'role' to user table.")
except Exception as e:
    print(f"Role column error: {e}")

try:
    cursor.execute("ALTER TABLE recent_view ADD COLUMN time_spent INTEGER DEFAULT 0")
    print("Added 'time_spent' to recent_view table.")
except Exception as e:
    print(f"Time_spent column error: {e}")

try:
    cursor.execute("ALTER TABLE document ADD COLUMN uploader_id INTEGER REFERENCES user(id)")
    print("Added 'uploader_id' to document table.")
except Exception as e:
    print(f"Uploader_id column error: {e}")

conn.commit()
conn.close()
print("Migration finished.")
