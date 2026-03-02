from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean

from app.core.database import Base


class DataSource(Base):
    __tablename__ = "datasources"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    filepath = Column(String(500), nullable=False)
    symbol = Column(String(20), default="")
    timeframe = Column(String(10), default="")
    data_type = Column(String(20), default="ohlcv")  # ohlcv, tick
    row_count = Column(Integer, default=0)
    date_from = Column(String(30), default="")
    date_to = Column(String(30), default="")
    columns = Column(String(500), default="")         # Comma-separated column names
    file_size_mb = Column(Integer, default=0)
    source_type = Column(String(20), default="upload")  # upload, broker
    broker_name = Column(String(20), default="")        # mt5, oanda, coinbase, tradovate
    # Instrument profile
    pip_value = Column(Float, default=10.0)             # $ per pip per standard lot
    is_jpy_pair = Column(Boolean, default=False)        # JPY pairs have different pip scale
    point_value = Column(Float, default=1.0)            # $ value per 1-point move per lot
    lot_size = Column(Float, default=100000.0)          # contract size (100000 for forex)
    default_spread = Column(Float, default=0.3)         # spread in points
    commission_model = Column(String(20), default="per_lot")  # per_lot, per_trade, pct
    default_commission = Column(Float, default=7.0)    # default $ commission per lot
    # Ownership / visibility
    creator_id = Column(Integer, default=1)              # FK to users.id
    is_public = Column(Boolean, default=True)             # visible to all users
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
