import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app.core.auth import hash_password
import sqlite3

new_hash = hash_password("Flowrex2025!")
conn = sqlite3.connect("data/flowrexalgo.db")
conn.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE username=?", (new_hash, "FlowrexAdmin"))
conn.commit()
print("Password reset OK for FlowrexAdmin")
conn.close()
