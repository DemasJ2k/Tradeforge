"""
Demo data bundle — seeds a new user with sample data and strategies
so they can immediately explore the platform.

Called after user registration to pre-populate:
  - 1 synthetic XAUUSD H1 datasource (1000 bars ≈ ~6 weeks)
  - 2 strategies from built-in templates (SMA Crossover + MACD+RSI)
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
