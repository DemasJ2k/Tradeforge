from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
