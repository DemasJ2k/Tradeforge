"""One-time script to clean up system strategies — keep only Gold Breakout + 2 MSS."""
import os, sqlite3

os.chdir(os.path.dirname(os.path.abspath(__file__)))
conn = sqlite3.connect("data/flowrexalgo.db")

# Rename id=2 to MSS Classic
conn.execute("UPDATE strategies SET name='MSS Classic – Market Structure Shift' WHERE id=2")

# Delete unwanted: Gold Breakout Trader(3), VWAP+MACD(4), RSI+BB(5), 200-EMA(6), Pivot(7),
#   user MSS(16), MSS CRYPTO(20), Gold Breakout copy(21), Gold Breakout Trader copy(22)
conn.execute("DELETE FROM strategies WHERE id IN (3, 4, 5, 6, 7, 16, 20, 21, 22)")

conn.commit()

# Verify
rows = conn.execute("SELECT id, name, is_system FROM strategies ORDER BY id").fetchall()
print("Remaining strategies:")
for r in rows:
    print(f"  id={r[0]}  system={r[2]}  {r[1]}")

conn.close()
print("Done.")
