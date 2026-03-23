"""
Demo data bundle — seeds a new user with sample data and strategies
so they can immediately explore the platform.

Called after user registration to pre-populate:
  - 1 synthetic XAUUSD H1 datasource (1000 bars ≈ ~6 weeks)
  - 2 strategies from built-in templates (SMA Crossover + MACD+RSI)

Also provides seed_databento_sources() to register pre-downloaded
Databento CSV files as public datasources available to all users.
"""

import csv
import logging
import math
import os
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.datasource import DataSource
from app.models.strategy import Strategy

logger = logging.getLogger(__name__)


def _generate_xauusd_h1(num_bars: int = 1000) -> list[dict]:
    """Generate realistic synthetic XAUUSD H1 OHLCV data."""
    random.seed(42)  # reproducible demo data
    bars = []
    price = 2340.0  # starting price
    dt = datetime(2025, 1, 2, 0, 0, 0)

    for _ in range(num_bars):
        # Skip weekends
        while dt.weekday() >= 5:
            dt += timedelta(hours=1)

        # Random walk with slight upward drift
        change = random.gauss(0.02, 2.5)
        o = round(price, 2)
        h = round(o + abs(random.gauss(0, 3.0)), 2)
        l = round(o - abs(random.gauss(0, 3.0)), 2)
        c = round(o + change, 2)

        # Ensure OHLC consistency
        h = max(h, o, c)
        l = min(l, o, c)

        vol = random.randint(800, 5000)
        bars.append({
            "time": dt.strftime("%Y.%m.%d %H:%M:%S"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": vol,
        })
        price = c
        dt += timedelta(hours=1)

    return bars


def setup_demo_data(user_id: int, db: Session) -> None:
    """Create demo datasource + strategies for a newly registered user."""
    try:
        _create_demo_datasource(user_id, db)
        _create_demo_strategies(user_id, db)
        logger.info("Demo data setup complete for user %d", user_id)
    except Exception as e:
        logger.error("Demo data setup failed for user %d: %s", user_id, e)
        # Non-fatal — don't block registration


def _create_demo_datasource(user_id: int, db: Session) -> None:
    """Generate a synthetic XAUUSD H1 CSV and create a DataSource record."""
    # Check if user already has datasources
    existing = db.query(DataSource).filter(
        DataSource.creator_id == user_id,
    ).count()
    if existing > 0:
        return

    bars = _generate_xauusd_h1(1000)
    filename = "XAUUSD_H1_demo.csv"
    filepath = os.path.join(settings.UPLOAD_DIR, filename)

    # Write CSV
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(bars)

    file_size = os.path.getsize(filepath) / (1024 * 1024)

    ds = DataSource(
        filename=filename,
        filepath=filepath,
        symbol="XAUUSD",
        timeframe="H1",
        data_type="ohlcv",
        row_count=len(bars),
        date_from=bars[0]["time"],
        date_to=bars[-1]["time"],
        columns="time,open,high,low,close,volume",
        file_size_mb=round(file_size, 3),
        source_type="demo",
        # XAUUSD instrument profile
        pip_value=10.0,
        point_value=1.0,
        lot_size=100.0,
        default_spread=0.3,
        commission_model="per_lot",
        default_commission=7.0,
        creator_id=user_id,
        is_public=False,
    )
    db.add(ds)
    db.commit()
    logger.info("Created demo datasource '%s' for user %d", filename, user_id)


def _create_demo_strategies(user_id: int, db: Session) -> None:
    """Create 2 strategies from built-in templates for the user."""
    import copy
    from app.api.strategy import STRATEGY_TEMPLATES

    # Check if user already has strategies
    existing = db.query(Strategy).filter(
        Strategy.creator_id == user_id,
        Strategy.is_system == False,
    ).count()
    if existing > 0:
        return

    # Create SMA Crossover and MACD+RSI from templates
    template_ids = ["sma_crossover", "macd_rsi_confirm"]

    for tid in template_ids:
        template = next((t for t in STRATEGY_TEMPLATES if t["id"] == tid), None)
        if not template:
            continue

        strat = Strategy(
            name=f"{template['name']} (Demo)",
            description=template["description"],
            indicators=copy.deepcopy(template["indicators"]),
            entry_rules=copy.deepcopy(template["entry_rules"]),
            exit_rules=copy.deepcopy(template["exit_rules"]),
            risk_params=copy.deepcopy(template["risk_params"]),
            filters=copy.deepcopy(template.get("filters", {})),
            strategy_type="builder",
            is_system=False,
            creator_id=user_id,
        )
        db.add(strat)

    db.commit()
    logger.info("Created 2 demo strategies for user %d", user_id)


# ── Instrument profiles for Databento symbols ──────────────────────
_INSTRUMENT_PROFILES = {
    "XAUUSD": {"pip_value": 10.0, "point_value": 1.0, "lot_size": 100.0, "default_spread": 0.3, "default_commission": 7.0},
    "ES":     {"pip_value": 12.5, "point_value": 50.0, "lot_size": 1.0, "default_spread": 0.25, "default_commission": 4.0},
    "NAS100": {"pip_value": 5.0, "point_value": 20.0, "lot_size": 1.0, "default_spread": 0.75, "default_commission": 4.0},
    "US30":   {"pip_value": 5.0, "point_value": 5.0, "lot_size": 1.0, "default_spread": 1.0, "default_commission": 4.0},
    "BTCUSD": {"pip_value": 1.0, "point_value": 1.0, "lot_size": 1.0, "default_spread": 5.0, "default_commission": 0.0},
}

# Pre-computed metadata for each Databento CSV (rows, date_from, date_to, file_size_bytes)
_DATABENTO_FILES = {
    "BTCUSD_H1":  (48800,   "2017-12-17 23:00:00+00:00", "2026-03-18 23:00:00+00:00", 2974889),
    "BTCUSD_H4":  (13193,   "2017-12-17 20:00:00+00:00", "2026-03-18 20:00:00+00:00", 812402),
    "BTCUSD_M1":  (1858470, "2017-12-17 23:00:00+00:00", "2026-03-18 23:58:00+00:00", 110964186),
    "BTCUSD_M15": (193265,  "2017-12-17 23:00:00+00:00", "2026-03-18 23:45:00+00:00", 11659009),
    "BTCUSD_M5":  (541213,  "2017-12-17 23:00:00+00:00", "2026-03-18 23:55:00+00:00", 32434891),
    "ES_H1":      (66470,   "2015-01-01 23:00:00+00:00", "2026-03-20 20:00:00+00:00", 4112240),
    "ES_H4":      (17942,   "2015-01-01 20:00:00+00:00", "2026-03-20 20:00:00+00:00", 1119308),
    "ES_M1":      (3938566, "2015-01-01 23:00:00+00:00", "2026-03-20 20:59:00+00:00", 236167483),
    "ES_M15":     (263479,  "2015-01-01 23:00:00+00:00", "2026-03-20 20:45:00+00:00", 16124712),
    "ES_M5":      (790066,  "2015-01-01 23:00:00+00:00", "2026-03-20 20:55:00+00:00", 47966416),
    "NAS100_H1":  (66430,   "2015-01-01 23:00:00+00:00", "2026-03-20 20:00:00+00:00", 4206574),
    "NAS100_H4":  (17942,   "2015-01-01 20:00:00+00:00", "2026-03-20 20:00:00+00:00", 1149144),
    "NAS100_M1":  (3903192, "2015-01-01 23:00:00+00:00", "2026-03-20 20:59:00+00:00", 240255535),
    "NAS100_M15": (263412,  "2015-01-01 23:00:00+00:00", "2026-03-20 20:45:00+00:00", 16532901),
    "NAS100_M5":  (789746,  "2015-01-01 23:00:00+00:00", "2026-03-20 20:55:00+00:00", 49158839),
    "US30_H1":    (66408,   "2015-01-01 23:00:00+00:00", "2026-03-20 20:00:00+00:00", 4186479),
    "US30_H4":    (17938,   "2015-01-01 20:00:00+00:00", "2026-03-20 20:00:00+00:00", 1140305),
    "US30_M1":    (3884193, "2015-01-01 23:00:00+00:00", "2026-03-20 20:59:00+00:00", 237542061),
    "US30_M15":   (263321,  "2015-01-01 23:00:00+00:00", "2026-03-20 20:45:00+00:00", 16426303),
    "US30_M5":    (789437,  "2015-01-01 23:00:00+00:00", "2026-03-20 20:55:00+00:00", 48851712),
    "XAUUSD_H1":  (66442,   "2015-01-01 23:00:00+00:00", "2026-03-20 20:00:00+00:00", 3935305),
    "XAUUSD_H4":  (17928,   "2015-01-01 20:00:00+00:00", "2026-03-20 20:00:00+00:00", 1072706),
    "XAUUSD_M1":  (3959279, "2015-01-01 23:00:00+00:00", "2026-03-20 20:59:00+00:00", 227029327),
    "XAUUSD_M15": (265044,  "2015-01-01 23:00:00+00:00", "2026-03-20 20:45:00+00:00", 15535266),
    "XAUUSD_M5":  (795050,  "2015-01-01 23:00:00+00:00", "2026-03-20 20:55:00+00:00", 46193081),
}


def seed_databento_sources(db: Session) -> None:
    """Register pre-downloaded Databento CSV files as public datasources.

    Idempotent — skips files that already have a matching DataSource record.
    Runs once at startup from main.py.
    """
    databento_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "databento")
    if not os.path.isdir(databento_dir):
        logger.info("Databento data dir not found (%s), skipping seed", databento_dir)
        return

    # Get existing databento source filenames to skip duplicates
    existing = {
        row[0] for row in
        db.query(DataSource.filename)
        .filter(DataSource.source_type == "databento", DataSource.deleted_at.is_(None))
        .all()
    }

    added = 0
    for key, (row_count, date_from, date_to, file_bytes) in _DATABENTO_FILES.items():
        filename = f"{key}.csv"
        filepath = os.path.join(databento_dir, filename)

        if filename in existing:
            continue
        if not os.path.isfile(filepath):
            logger.warning("Databento file missing: %s", filepath)
            continue

        # Parse symbol and timeframe from key (e.g. "XAUUSD_H1" → "XAUUSD", "H1")
        parts = key.rsplit("_", 1)
        symbol, timeframe = parts[0], parts[1]
        profile = _INSTRUMENT_PROFILES.get(symbol, {})

        ds = DataSource(
            filename=filename,
            filepath=filepath,
            symbol=symbol,
            timeframe=timeframe,
            data_type="ohlcv",
            row_count=row_count,
            date_from=date_from,
            date_to=date_to,
            columns="datetime,open,high,low,close,volume",
            file_size_mb=round(file_bytes / (1024 * 1024), 3),
            source_type="databento",
            broker_name="",
            pip_value=profile.get("pip_value", 10.0),
            point_value=profile.get("point_value", 1.0),
            lot_size=profile.get("lot_size", 1.0),
            default_spread=profile.get("default_spread", 0.3),
            commission_model="per_lot",
            default_commission=profile.get("default_commission", 4.0),
            creator_id=1,  # admin user
            is_public=True,
        )
        db.add(ds)
        added += 1

    if added:
        db.commit()
        logger.info("Seeded %d Databento datasources", added)
    else:
        logger.info("All Databento datasources already registered")
