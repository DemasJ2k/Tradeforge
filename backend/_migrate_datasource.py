"""
Migration: Add instrument profile columns to datasources table.
Run from the backend/ directory:
    python _migrate_datasource.py
"""
import sys
from sqlalchemy import text
from app.core.database import engine

MIGRATIONS = [
    ("pip_value",          "ALTER TABLE datasources ADD COLUMN pip_value REAL DEFAULT 10.0"),
    ("is_jpy_pair",        "ALTER TABLE datasources ADD COLUMN is_jpy_pair BOOLEAN DEFAULT FALSE"),
    ("point_value",        "ALTER TABLE datasources ADD COLUMN point_value REAL DEFAULT 1.0"),
    ("lot_size",           "ALTER TABLE datasources ADD COLUMN lot_size REAL DEFAULT 100000.0"),
    ("default_spread",     "ALTER TABLE datasources ADD COLUMN default_spread REAL DEFAULT 0.3"),
    ("commission_model",   "ALTER TABLE datasources ADD COLUMN commission_model VARCHAR(20) DEFAULT 'per_lot'"),
    ("default_commission", "ALTER TABLE datasources ADD COLUMN default_commission REAL DEFAULT 7.0"),
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
            if column_exists(conn, "datasources", col):
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
