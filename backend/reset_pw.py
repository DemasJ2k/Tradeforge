import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from app.core.auth import hash_password
import sqlite3

new_hash = hash_password("Tradeforge2025!")
conn = sqlite3.connect("data/tradeforge.db")
conn.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE username=?", (new_hash, "TradeforgeAdmin"))
conn.commit()
print("Password reset OK for TradeforgeAdmin")
conn.close()
