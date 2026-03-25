"""
Download historical OHLCV data from Databento and save as CSV.

Downloads CME futures data at 1-second resolution, then aggregates to
multiple timeframes (M1, M5, M15, H1, H4) for ML training.

Usage:
    python scripts/download_databento.py
    python scripts/download_databento.py --symbols GC ES NQ --start 2015-01-01
    python scripts/download_databento.py --symbols GC --timeframes M1 M5 M15 H1 H4
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import databento as db
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Symbol mapping: Tradeforge name → Databento (dataset, symbol) ──
SYMBOL_MAP = {
    "GC":  ("GLBX.MDP3", "GC.FUT"),    # Gold → XAUUSD
    "ES":  ("GLBX.MDP3", "ES.FUT"),    # S&P 500
    "NQ":  ("GLBX.MDP3", "NQ.FUT"),    # Nasdaq 100 → NAS100
    "YM":  ("GLBX.MDP3", "YM.FUT"),    # Dow 30 → US30
    "BTC": ("GLBX.MDP3", "BTC.FUT"),   # Bitcoin
    "SI":  ("GLBX.MDP3", "SI.FUT"),    # Silver → XAGUSD
}

# Broker symbol aliases (for agent compatibility)
BROKER_ALIAS = {
    "GC": "XAUUSD",
    "ES": "ES",
    "NQ": "NAS100",
    "YM": "US30",
    "BTC": "BTCUSD",
    "SI": "XAGUSD",
}

# Timeframe aggregation rules
TIMEFRAME_MINUTES = {
    "M1":  1,
    "M5":  5,
    "M10": 10,
    "M15": 15,
    "M30": 30,
    "H1":  60,
    "H4":  240,
    "D1":  1440,
}

DATA_DIR = Path(__file__).parent.parent / "data" / "databento"


def download_ohlcv(
    api_key: str,
    symbol_key: str,
    start: str = "2015-01-01",
    end: str | None = None,
    schema: str = "ohlcv-1m",
) -> pd.DataFrame:
    """Download OHLCV data from Databento Historical API.

    Uses 1-minute bars as the base resolution (much smaller downloads than 1s,
    and sufficient for aggregating to M5/M15/H1/H4).

    Databento returns ALL contract months and calendar spreads for .FUT symbols.
    We build a continuous front-month series by selecting the highest-volume
    outright contract (no spreads) per each 1-minute bar.
    """
    dataset, db_symbol = SYMBOL_MAP[symbol_key]

    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    print(f"  Downloading {symbol_key} ({db_symbol}) from {start} to {end}...")
    print(f"  Dataset: {dataset}, Schema: {schema}")

    client = db.Historical(api_key)

    data = client.timeseries.get_range(
        dataset=dataset,
        symbols=[db_symbol],
        schema=schema,
        start=start,
        end=end,
        stype_in="parent",
    )

    df = data.to_df()

    if df.empty:
        print(f"  WARNING: No data returned for {symbol_key}")
        return df

    print(f"  Received {len(df):,} raw bars (all contracts)")

    # ── Build continuous front-month series ──
    # 1. Restore datetime from index
    if df.index.name == "ts_event":
        df = df.reset_index()
        df["datetime"] = pd.to_datetime(df["ts_event"], utc=True)
    elif "ts_event" in df.columns:
        df["datetime"] = pd.to_datetime(df["ts_event"], utc=True)
    else:
        df["datetime"] = df.index

    # 2. Filter out calendar spreads (symbol contains '-')
    if "symbol" in df.columns:
        spreads_mask = df["symbol"].str.contains("-", na=False)
        n_spreads = spreads_mask.sum()
        df = df[~spreads_mask].copy()
        if n_spreads > 0:
            print(f"  Filtered out {n_spreads:,} spread bars")

    # 3. Drop rows with negative/zero close (remaining spreads or bad data)
    df = df[df["close"] > 0].copy()

    # 4. For each timestamp, keep only the highest-volume contract (front month)
    if "symbol" in df.columns and df["symbol"].nunique() > 1:
        # Group by datetime, pick contract with max volume per bar
        df = df.sort_values(["datetime", "volume"], ascending=[True, False])
        df = df.drop_duplicates(subset=["datetime"], keep="first")
        contracts_used = df["symbol"].nunique()
        print(f"  Built continuous series using {contracts_used} contract rolls")

    # 5. Keep only OHLCV + datetime
    keep_cols = [c for c in ["datetime", "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep_cols].copy()

    # 6. Drop NaN prices
    df = df.dropna(subset=["open", "high", "low", "close"])

    # 7. Sort by time
    df = df.sort_values("datetime").reset_index(drop=True)

    print(f"  Final continuous series: {len(df):,} bars")

    return df


def aggregate_timeframe(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate 1-minute bars to a higher timeframe."""
    if minutes <= 1:
        return df.copy()

    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("datetime")

    rule = f"{minutes}min"

    agg = df.resample(rule).agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna(subset=["open", "high", "low", "close"])

    agg = agg.reset_index()
    agg = agg[agg["close"] > 0]

    return agg


def save_csv(df: pd.DataFrame, symbol_key: str, timeframe: str):
    """Save DataFrame as CSV for training."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    broker_sym = BROKER_ALIAS.get(symbol_key, symbol_key)
    filename = f"{broker_sym}_{timeframe}.csv"
    filepath = DATA_DIR / filename

    df.to_csv(filepath, index=False)
    print(f"  Saved {filepath} ({len(df):,} bars, {filepath.stat().st_size / 1024:.0f} KB)")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Download Databento historical data for ML training")
    parser.add_argument(
        "--symbols", nargs="+", default=["GC", "ES", "NQ", "YM", "BTC"],
        help="Symbols to download (default: GC ES NQ YM BTC)",
    )
    parser.add_argument(
        "--timeframes", nargs="+", default=["M1", "M5", "M15", "H1", "H4"],
        help="Timeframes to aggregate (default: M1 M5 M15 H1 H4)",
    )
    parser.add_argument("--start", default="2015-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD), default=today")
    parser.add_argument("--api-key", default=None, help="Databento API key (or set DATABENTO_API_KEY env var)")
    args = parser.parse_args()

    # Get API key
    api_key = args.api_key or os.getenv("DATABENTO_API_KEY", "")
    if not api_key:
        print("ERROR: Set DATABENTO_API_KEY environment variable or pass --api-key")
        sys.exit(1)

    print("=" * 60)
    print("Databento Historical Data Download")
    print("=" * 60)
    print(f"Symbols:    {args.symbols}")
    print(f"Timeframes: {args.timeframes}")
    print(f"Range:      {args.start} → {args.end or 'today'}")
    print(f"Output:     {DATA_DIR}")
    print()

    all_files = []

    for symbol in args.symbols:
        if symbol not in SYMBOL_MAP:
            print(f"WARNING: Unknown symbol {symbol}, skipping. Available: {list(SYMBOL_MAP.keys())}")
            continue

        print(f"\n{'─' * 40}")
        print(f"Processing {symbol} ({BROKER_ALIAS.get(symbol, symbol)})")
        print(f"{'─' * 40}")

        # Download 1-minute base data
        try:
            df_base = download_ohlcv(api_key, symbol, start=args.start, end=args.end, schema="ohlcv-1m")
        except Exception as e:
            print(f"  ERROR downloading {symbol}: {e}")
            continue

        if df_base.empty:
            continue

        # Aggregate to each timeframe and save
        for tf in args.timeframes:
            minutes = TIMEFRAME_MINUTES.get(tf)
            if minutes is None:
                print(f"  WARNING: Unknown timeframe {tf}, skipping")
                continue

            print(f"\n  Aggregating to {tf} ({minutes} min)...")
            df_tf = aggregate_timeframe(df_base, minutes)

            if len(df_tf) < 500:
                print(f"  WARNING: Only {len(df_tf)} bars for {symbol} {tf}, may be insufficient for training")

            filepath = save_csv(df_tf, symbol, tf)
            all_files.append(str(filepath))

    print(f"\n{'=' * 60}")
    print(f"Download complete! {len(all_files)} files saved to {DATA_DIR}")
    print(f"{'=' * 60}")

    for f in all_files:
        print(f"  {f}")

    return all_files


if __name__ == "__main__":
    main()
