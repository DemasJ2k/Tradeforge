"""
Migration: Add new columns to optimizations table.
Run from the backend/ directory:
    python _migrate_optimization.py
"""
import sys
from sqlalchemy import text
from app.core.database import engine

MIGRATIONS = [
    # (column_name, DDL fragment)
    ("method",             "ALTER TABLE optimizations ADD COLUMN method VARCHAR(20) DEFAULT 'bayesian'"),
    ("min_trades",         "ALTER TABLE optimizations ADD COLUMN min_trades INTEGER DEFAULT 30"),
    ("walk_forward",       "ALTER TABLE optimizations ADD COLUMN walk_forward BOOLEAN DEFAULT FALSE"),
    ("param_importance",   "ALTER TABLE optimizations ADD COLUMN param_importance JSON"),
    ("robustness_result",  "ALTER TABLE optimizations ADD COLUMN robustness_result JSON"),
]


def column_exists(conn, table: str, column: str) -> bool:
    try:
        result = conn.execute(text(f"SELECT {column} FROM {table} LIMIT 1"))
        result.fetchone()
        return True
    except Exception:
        return False


def main():
    added = 0
    skipped = 0
    with engine.connect() as conn:
        for col, ddl in MIGRATIONS:
            if column_exists(conn, "optimizations", col):
                print(f"  [skip]  {col} — already exists")
                skipped += 1
            else:
                try:
                    conn.execute(text(ddl))
                    conn.commit()
                    print(f"  [added] {col}")
                    added += 1
                except Exception as e:
                    print(f"  [error] {col}: {e}", file=sys.stderr)

    print(f"\nDone: {added} columns added, {skipped} already present.")


if __name__ == "__main__":
    main()
