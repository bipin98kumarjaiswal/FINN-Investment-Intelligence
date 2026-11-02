"""Yahoo Finance EOD price and volume ingestion (kept from Phase 1)."""
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
import pandas as pd
from app import database
from app.portfolio import PORTFOLIO

PERIODS = ("1mo", "3mo", "6mo", "1y")
REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def rows_from_frame(frame: pd.DataFrame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    if not all(col in frame.columns for col in REQUIRED_COLUMNS):
        raise ValueError(f"Missing OHLCV columns: {list(frame.columns)}")
    result = []
    for day, row in frame.iterrows():
        values = [row[col] for col in REQUIRED_COLUMNS]
        if any(pd.isna(v) for v in values):
            continue
        try:
            o, h, l, c = [float(v) for v in values[:4]]
            volume = float(values[4])
            if not all(isfinite(v) for v in [o, h, l, c, volume]):
                continue
            if min(o, h, l, c) <= 0 or volume < 0 or volume != int(volume):
                continue
            date = pd.Timestamp(day).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            continue
        result.append({"trade_date": date,"open": o,"high": h,"low": l,
                       "close": c,"volume": int(volume)})
    return result


def frame_for_ticker(raw: pd.DataFrame, ticker: str, total: int) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        if ticker in raw.columns.get_level_values(0):
            return raw[ticker]
        if ticker in raw.columns.get_level_values(1):
            return raw.xs(ticker, axis=1, level=1)
        return pd.DataFrame()
    return raw if total == 1 else pd.DataFrame()


def sync_prices(period: str = "3mo", path: Path | None = None,
                downloader=None, companies: list[dict] | None = None) -> dict:
    if period not in PERIODS:
        raise ValueError(f"period must be one of {PERIODS}")
    chosen = PORTFOLIO if companies is None else companies
    database.init_db(path)
    tickers = [f'{row["symbol"]}.NS' for row in chosen]
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        if downloader is None:
            import yfinance as yf
            downloader = yf.download
        raw = downloader(tickers=tickers, period=period, interval="1d", group_by="ticker",
                         auto_adjust=False, multi_level_index=True, threads=True,
                         progress=False, timeout=15)
    except Exception as exc:
        msg = f"Market download failed: {type(exc).__name__}: {exc}"
        output = []
        for company in chosen:
            symbol = company["symbol"]
            database.save_sync_status(symbol, timestamp, "error", 0, msg, path)
            output.append({"symbol": symbol,"status": "error","rows": 0,"message": msg})
        return {"period": period,"source": "Yahoo Finance","ok": 0,
                "failed": len(chosen),"rows_saved": 0,"results": output}
    output = []
    total_rows = 0
    for company in chosen:
        symbol = company["symbol"]
        try:
            records = rows_from_frame(frame_for_ticker(raw, f"{symbol}.NS", len(tickers)))
            if not records:
                raise ValueError("No valid price rows returned by Yahoo")
            count = database.save_prices(symbol, records, timestamp, path)
            database.save_sync_status(symbol, timestamp, "ok", count, path=path)
            total_rows += count
            output.append({"symbol": symbol,"status": "ok","rows": count})
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            database.save_sync_status(symbol, timestamp, "error", 0, msg, path)
            output.append({"symbol": symbol,"status": "error","rows": 0,"message": msg})
    ok = sum(r["status"] == "ok" for r in output)
    return {"period": period,"source": "Yahoo Finance","ok": ok,
            "failed": len(chosen) - ok,"rows_saved": total_rows,"results": output}
