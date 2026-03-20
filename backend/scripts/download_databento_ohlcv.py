#!/usr/bin/env python3
"""
Download 5 years of OHLCV-1m data from Databento (CME Globex MDP 3.0).

Instruments:
  - US30  (YM.FUT)  — Dow Jones E-mini futures
  - Gold  (GC.FUT)  — Gold futures
  - BTC   (BTC.FUT) — Bitcoin futures (if available)
  - SPX500 (ES.FUT) — S&P 500 E-mini futures

Cost estimate: ~$20 per symbol for 5 years of OHLCV-1m (~300 MB each).

Usage:
  export DATABENTO_API_KEY=db-XXXX
  python scripts/download_databento_ohlcv.py

  # Or cost-check only (no download):
  python scripts/download_databento_ohlcv.py --cost-only

  # Download a single symbol:
  python scripts/download_databento_ohlcv.py --symbols US30
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve paths relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DATA_DIR = BACKEND_DIR / "data" / "databento"

# Symbols to download: local_name → (dataset, databento_parent_symbol)
SYMBOLS = {
    "US30":   ("GLBX.MDP3", "YM.FUT"),
    "XAUUSD": ("GLBX.MDP3", "GC.FUT"),
    "BTCUSD": ("GLBX.MDP3", "BTC.FUT"),
    "SPX500": ("GLBX.MDP3", "ES.FUT"),
}

SCHEMA = "ohlcv-1m"

# 5-year window ending today
END_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
START_DATE = (
    datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year - 5)
).strftime("%Y-%m-%d")


def get_client(api_key: str):
    try:
        import databento as db
    except ImportError:
        print("ERROR: databento package not installed. Run: pip install databento")
        sys.exit(1)
    return db.Historical(key=api_key)


def check_costs(client, symbols: dict[str, tuple[str, str]]):
    """Print estimated cost for each symbol without downloading."""
    total = 0.0
    for name, (dataset, db_symbol) in symbols.items():
        try:
            cost = client.metadata.get_cost(
                dataset=dataset,
                symbols=[db_symbol],
                schema=SCHEMA,
                start=START_DATE,
                end=END_DATE,
                stype_in="parent",
            )
            cost_usd = cost / 1e2  # cost is in cents
            total += cost_usd
            print(f"  {name:8s} ({db_symbol:8s}): ${cost_usd:>8.2f}")
        except Exception as e:
            print(f"  {name:8s} ({db_symbol:8s}): ERROR — {e}")
    print(f"  {'TOTAL':8s}              : ${total:>8.2f}")
    return total


def download_symbol(client, name: str, dataset: str, db_symbol: str, output_dir: Path):
    """Download OHLCV-1m data and save as CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{name}_ohlcv_1m.csv"

    print(f"\n  Downloading {name} ({db_symbol}) from {START_DATE} to {END_DATE}...")

    try:
        data = client.timeseries.get_range(
            dataset=dataset,
            symbols=[db_symbol],
            schema=SCHEMA,
            start=START_DATE,
            end=END_DATE,
            stype_in="parent",
        )
    except Exception as e:
        print(f"  ERROR downloading {name}: {e}")
        return False

    # Convert to DataFrame and save as CSV
    try:
        df = data.to_df()
    except Exception:
        # Fallback: iterate records manually
        import csv as csv_mod

        rows = []
        for rec in data:
            ts = rec.ts_event / 1e9 if hasattr(rec, "ts_event") else 0
            o, h, lo, c = float(rec.open), float(rec.high), float(rec.low), float(rec.close)
            # Handle fixed-point prices
            if o > 1e12:
                o, h, lo, c = o / 1e9, h / 1e9, lo / 1e9, c / 1e9
            rows.append({
                "datetime": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": float(rec.volume),
            })

        with open(csv_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=["datetime", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerows(rows)

        print(f"  Saved {len(rows):,} bars → {csv_path}")
        return True

    # DataFrame path
    if df.empty:
        print(f"  WARNING: No data returned for {name}")
        return False

    # Normalize column names
    df = df.reset_index()
    rename_map = {}
    for col in df.columns:
        col_lower = str(col).lower()
        if "ts_event" in col_lower or col_lower == "index":
            rename_map[col] = "datetime"

    if rename_map:
        df = df.rename(columns=rename_map)

    # Select only OHLCV columns
    keep_cols = []
    for target in ["datetime", "open", "high", "low", "close", "volume"]:
        for col in df.columns:
            if str(col).lower() == target:
                keep_cols.append(col)
                break

    if keep_cols:
        df = df[keep_cols]
        df.columns = ["datetime", "open", "high", "low", "close", "volume"][:len(keep_cols)]

    # Handle fixed-point prices
    if df["open"].iloc[0] > 1e12:
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] / 1e9

    df.to_csv(csv_path, index=False)
    print(f"  Saved {len(df):,} bars → {csv_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Download Databento OHLCV-1m data")
    parser.add_argument("--cost-only", action="store_true", help="Only show cost estimates")
    parser.add_argument("--symbols", nargs="*", help="Symbols to download (default: all)")
    parser.add_argument("--output-dir", type=str, default=str(DATA_DIR), help="Output directory")
    args = parser.parse_args()

    api_key = os.environ.get("DATABENTO_API_KEY", "")
    if not api_key:
        # Try loading from .env file
        env_path = BACKEND_DIR / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DATABENTO_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not api_key:
        print("ERROR: DATABENTO_API_KEY not set. Export it or add to backend/.env")
        sys.exit(1)

    # Filter symbols if requested
    symbols = SYMBOLS
    if args.symbols:
        symbols = {k: v for k, v in SYMBOLS.items() if k in args.symbols}
        if not symbols:
            print(f"ERROR: No matching symbols. Available: {list(SYMBOLS.keys())}")
            sys.exit(1)

    client = get_client(api_key)
    output_dir = Path(args.output_dir)

    print(f"Databento OHLCV-1m Download")
    print(f"  Period: {START_DATE} → {END_DATE} (5 years)")
    print(f"  Schema: {SCHEMA}")
    print(f"  Output: {output_dir}")
    print(f"  Symbols: {list(symbols.keys())}")
    print()

    # Cost check
    print("Cost estimate:")
    check_costs(client, symbols)

    if args.cost_only:
        return

    print("\nStarting downloads...")
    results = {}
    for name, (dataset, db_symbol) in symbols.items():
        ok = download_symbol(client, name, dataset, db_symbol, output_dir)
        results[name] = ok

    print("\n── Summary ──")
    for name, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"  {name:8s}: {status}")


if __name__ == "__main__":
    main()
