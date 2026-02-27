import csv
import os
import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.datasource import DataSource
from app.schemas.datasource import DataSourceResponse, DataSourceList, CandleResponse, CandleData, BrokerFetchRequest

router = APIRouter(prefix="/api/data", tags=["data"])

# Common datetime formats to try when parsing
DATETIME_FORMATS = [
    "%Y.%m.%d %H:%M:%S",   # MT5 export: 2025.01.02 00:00:00
    "%Y-%m-%d %H:%M:%S",   # ISO-ish: 2025-01-02 00:00:00
    "%Y/%m/%d %H:%M:%S",   # Slash: 2025/01/02 00:00:00
    "%Y.%m.%d %H:%M",      # MT5 no seconds
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",   # ISO 8601
    "%Y-%m-%d",             # Date only
    "%m/%d/%Y %H:%M",      # US format
    "%d/%m/%Y %H:%M",      # EU format
]

# Column name aliases (lowercase)
DATETIME_ALIASES = {"time", "date", "datetime", "timestamp", "date_time", "<date>", "<time>"}
OPEN_ALIASES = {"open", "o", "<open>"}
HIGH_ALIASES = {"high", "h", "<high>"}
LOW_ALIASES = {"low", "l", "<low>"}
CLOSE_ALIASES = {"close", "c", "<close>"}
VOLUME_ALIASES = {"volume", "vol", "v", "<vol>", "<volume>", "tick_volume", "tickvol"}


def _detect_delimiter(sample: str) -> str:
    """Detect CSV delimiter from first few lines."""
    for delim in ["\t", ",", ";"]:
        if delim in sample:
            return delim
    return ","


def _match_column(header: str, aliases: set) -> bool:
    return header.strip().lower() in aliases


def _detect_columns(headers: list[str]) -> dict:
    """Map standard OHLCV columns from header names."""
    mapping = {}
    for i, h in enumerate(headers):
        hl = h.strip().lower()
        if _match_column(h, DATETIME_ALIASES):
            mapping["datetime"] = i
        elif _match_column(h, OPEN_ALIASES):
            mapping["open"] = i
        elif _match_column(h, HIGH_ALIASES):
            mapping["high"] = i
        elif _match_column(h, LOW_ALIASES):
            mapping["low"] = i
        elif _match_column(h, CLOSE_ALIASES):
            mapping["close"] = i
        elif _match_column(h, VOLUME_ALIASES):
            mapping["volume"] = i
    return mapping


def _parse_datetime(value: str) -> datetime | None:
    """Try multiple datetime formats."""
    value = value.strip()
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    # Try unix timestamp
    try:
        ts = float(value)
        return datetime.utcfromtimestamp(ts)
    except (ValueError, OSError):
        pass
    return None


def _guess_symbol_timeframe(filename: str) -> tuple[str, str]:
    """Try to extract symbol and timeframe from filename like XAUUSD_M10_...csv"""
    name = Path(filename).stem.upper()
    parts = name.split("_")
    symbol = parts[0] if parts else ""
    timeframe = ""
    for p in parts[1:]:
        if p in ("M1", "M5", "M10", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"):
            timeframe = p
            break
    return symbol, timeframe


@router.post("/upload", response_model=DataSourceResponse)
async def upload_csv(
    file: UploadFile = File(...),
    symbol: str = Query("", description="Override symbol name"),
    timeframe: str = Query("", description="Override timeframe"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    content = await file.read()
    size_mb = len(content) // (1024 * 1024)

    if size_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise HTTPException(status_code=400, detail=f"File too large (max {settings.MAX_UPLOAD_SIZE_MB}MB)")

    text = content.decode("utf-8", errors="replace")
    delimiter = _detect_delimiter(text[:2000])

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)

    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="CSV must have at least a header and one data row")

    headers = rows[0]
    col_map = _detect_columns(headers)

    required = {"datetime", "open", "high", "low", "close"}
    missing = required - set(col_map.keys())
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Could not detect columns: {', '.join(missing)}. "
                   f"Found headers: {headers}",
        )

    # Parse first and last datetime for range
    first_row = rows[1]
    last_row = rows[-1]
    dt_first = _parse_datetime(first_row[col_map["datetime"]])
    dt_last = _parse_datetime(last_row[col_map["datetime"]])

    if not dt_first or not dt_last:
        raise HTTPException(status_code=400, detail="Could not parse datetime values")

    # Guess symbol/timeframe from filename if not provided
    auto_symbol, auto_tf = _guess_symbol_timeframe(file.filename)
    final_symbol = symbol or auto_symbol
    final_timeframe = timeframe or auto_tf

    # Save file to disk
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{int(datetime.now().timestamp())}_{file.filename}"
    filepath = upload_dir / safe_name
    filepath.write_bytes(content)

    # Save metadata to DB
    ds = DataSource(
        filename=file.filename,
        filepath=str(filepath),
        symbol=final_symbol,
        timeframe=final_timeframe,
        data_type="ohlcv",
        row_count=len(rows) - 1,
        date_from=dt_first.strftime("%Y-%m-%d %H:%M"),
        date_to=dt_last.strftime("%Y-%m-%d %H:%M"),
        columns=",".join(headers),
        file_size_mb=size_mb,
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


@router.get("/sources", response_model=DataSourceList)
def list_sources(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sources = db.query(DataSource).order_by(DataSource.created_at.desc()).all()
    return DataSourceList(items=sources, total=len(sources))


@router.get("/sources/{source_id}/candles", response_model=CandleResponse)
def get_candles(
    source_id: int,
    limit: int = Query(500, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ds = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    if not os.path.exists(ds.filepath):
        raise HTTPException(status_code=404, detail="Data file missing from disk")

    with open(ds.filepath, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    delimiter = _detect_delimiter(text[:2000])
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    headers = rows[0]
    col_map = _detect_columns(headers)

    data_rows = rows[1:]  # skip header
    # Apply offset and limit
    sliced = data_rows[offset: offset + limit]

    candles = []
    for row in sliced:
        try:
            dt = _parse_datetime(row[col_map["datetime"]])
            if not dt:
                continue
            candle = CandleData(
                time=dt.timestamp(),
                open=float(row[col_map["open"]]),
                high=float(row[col_map["high"]]),
                low=float(row[col_map["low"]]),
                close=float(row[col_map["close"]]),
                volume=float(row[col_map["volume"]]) if "volume" in col_map else 0.0,
            )
            candles.append(candle)
        except (ValueError, IndexError):
            continue

    return CandleResponse(
        symbol=ds.symbol,
        timeframe=ds.timeframe,
        candles=candles,
        total=len(data_rows),
    )


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ds = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    # Delete file from disk
    try:
        if os.path.exists(ds.filepath):
            os.remove(ds.filepath)
    except OSError:
        pass

    db.delete(ds)
    db.commit()
    return {"status": "deleted", "id": source_id}


@router.post("/fetch-broker", response_model=DataSourceResponse)
async def fetch_from_broker(
    req: BrokerFetchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download historical candles from a broker and save as a data source."""
    import asyncio
    import logging
    logger = logging.getLogger(__name__)

    if req.broker == "mt5":
        try:
            import MetaTrader5 as mt5
            from app.services.broker.mt5_bridge import _TF_MAP
            from concurrent.futures import ThreadPoolExecutor

            tf = _TF_MAP.get(req.timeframe)
            if tf is None:
                raise HTTPException(400, f"Unsupported timeframe: {req.timeframe}")

            loop = asyncio.get_event_loop()
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fetch-mt5")

            def _fetch():
                if not mt5.initialize():
                    raise RuntimeError("MT5 not initialized")
                mt5.symbol_select(req.symbol, True)
                rates = mt5.copy_rates_from_pos(req.symbol, tf, 0, req.bars)
                return rates

            raw = await loop.run_in_executor(pool, _fetch)
            if raw is None or len(raw) == 0:
                raise HTTPException(400, f"No data returned from MT5 for {req.symbol} {req.timeframe}")

            # Build CSV content
            lines = ["time,open,high,low,close,volume"]
            first_dt = None
            last_dt = None
            for r in raw:
                dt = datetime.utcfromtimestamp(int(r['time']))
                if first_dt is None:
                    first_dt = dt
                last_dt = dt
                lines.append(
                    f"{dt.strftime('%Y.%m.%d %H:%M:%S')},"
                    f"{r['open']},{r['high']},{r['low']},{r['close']},{r['tick_volume']}"
                )

            csv_content = "\n".join(lines)
            filename = f"{req.symbol}_{req.timeframe}_{len(raw)}bars.csv"

            # Save to disk
            upload_dir = Path(settings.UPLOAD_DIR)
            upload_dir.mkdir(parents=True, exist_ok=True)
            safe_name = f"{int(datetime.now().timestamp())}_{filename}"
            filepath = upload_dir / safe_name
            filepath.write_text(csv_content, encoding="utf-8")

            # Save metadata
            ds = DataSource(
                filename=filename,
                filepath=str(filepath),
                symbol=req.symbol,
                timeframe=req.timeframe,
                data_type="ohlcv",
                row_count=len(raw),
                date_from=first_dt.strftime("%Y-%m-%d %H:%M") if first_dt else "",
                date_to=last_dt.strftime("%Y-%m-%d %H:%M") if last_dt else "",
                columns="time,open,high,low,close,volume",
                file_size_mb=len(csv_content) // (1024 * 1024),
                source_type="broker",
                broker_name="mt5",
            )
            db.add(ds)
            db.commit()
            db.refresh(ds)

            logger.info("Fetched %d bars for %s %s from MT5", len(raw), req.symbol, req.timeframe)
            return ds

        except ImportError:
            raise HTTPException(400, "MetaTrader5 package not available")
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    else:
        # Future: support other brokers via broker_manager
        from app.services.broker.manager import broker_manager
        adapter = broker_manager.get_adapter(req.broker)
        if not adapter:
            raise HTTPException(400, f"Broker '{req.broker}' not connected")

        try:
            bars = await adapter.get_initial_bars(req.symbol, req.timeframe, req.bars)
            if not bars:
                raise HTTPException(400, f"No data returned from {req.broker}")

            lines = ["time,open,high,low,close,volume"]
            first_dt = None
            last_dt = None
            for b in bars:
                dt = datetime.utcfromtimestamp(int(b['time']))
                if first_dt is None:
                    first_dt = dt
                last_dt = dt
                lines.append(
                    f"{dt.strftime('%Y.%m.%d %H:%M:%S')},"
                    f"{b['open']},{b['high']},{b['low']},{b['close']},{b.get('volume', 0)}"
                )

            csv_content = "\n".join(lines)
            filename = f"{req.symbol}_{req.timeframe}_{len(bars)}bars.csv"

            upload_dir = Path(settings.UPLOAD_DIR)
            upload_dir.mkdir(parents=True, exist_ok=True)
            safe_name = f"{int(datetime.now().timestamp())}_{filename}"
            filepath = upload_dir / safe_name
            filepath.write_text(csv_content, encoding="utf-8")

            ds = DataSource(
                filename=filename,
                filepath=str(filepath),
                symbol=req.symbol,
                timeframe=req.timeframe,
                data_type="ohlcv",
                row_count=len(bars),
                date_from=first_dt.strftime("%Y-%m-%d %H:%M") if first_dt else "",
                date_to=last_dt.strftime("%Y-%m-%d %H:%M") if last_dt else "",
                columns="time,open,high,low,close,volume",
                file_size_mb=len(csv_content) // (1024 * 1024),
                source_type="broker",
                broker_name=req.broker,
            )
            db.add(ds)
            db.commit()
            db.refresh(ds)
            return ds

        except Exception as e:
            raise HTTPException(400, f"Fetch failed: {str(e)[:200]}")
