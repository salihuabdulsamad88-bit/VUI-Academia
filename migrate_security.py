import sqlite3
import os

db_path = 'instance/vui_academia.db'
if not os.path.exists(db_path):
    db_path = 'vui_academia.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE user ADD COLUMN security_question VARCHAR(255)")
    print("Added security_question.")
except Exception as e:
    print(f"Error: {e}")

try:
    cursor.execute("ALTER TABLE user ADD COLUMN security_answer VARCHAR(255)")
    print("Added security_answer.")
except Exception as e:
    print(f"Error: {e}")

conn.commit()
conn.close()
print("Migration done.")
