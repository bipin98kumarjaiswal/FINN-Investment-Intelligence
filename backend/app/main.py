"""FINN Push API: briefing, individual evidence, market alerts, user thresholds."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from app import database
from app.alerts import rebuild_alerts
from app.classifier import CATEGORIES
from app.portfolio import BY_SYMBOL
from app import research_store
from app.research_api import router as research_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    research_store.init()
    yield

app = FastAPI(title="FINN Investment Attention API", version="0.4.0", lifespan=lifespan)


app.include_router(research_router)


class AlertSettings(BaseModel):
    price_change_pct: float = Field(gt=0,le=50)
    volume_multiple: float = Field(ge=1.1,le=20)
    volume_lookback: int = Field(ge=5,le=60)
    categories: list[str]

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, values: list[str]):
        if len(values) != len(set(values)) or any(v not in CATEGORIES for v in values):
            raise ValueError(f"Each category must be unique and one of: {CATEGORIES}")
        return values


def window(hours: int, start: datetime | None, end: datetime | None) -> tuple[str,str]:
    if (start is None) != (end is None):
        raise HTTPException(422,"start and end must both be provided in ISO-8601 with timezone")
    now = datetime.now(timezone.utc)
    if start is None:
        return (now-timedelta(hours=hours)).isoformat(), now.isoformat()
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422,"start and end must include a timezone, e.g. +05:30 or Z")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if start > end or end > now + timedelta(minutes=5) or end-start>timedelta(days=90):
        raise HTTPException(422,"Invalid range (must be chronological and at most 90 days)")
    return start.isoformat(), end.isoformat()


@app.get("/health")
def health():
    return {"status":"ok","phase":"push","data_sources":["Yahoo Finance","NSE"],
            "note":"Process health only; see /api/filings/status for data-source freshness"}


@app.get("/api/portfolio")
def portfolio():
    items = database.portfolio_latest()
    return {"count":len(items),"companies":items}


@app.get("/api/prices/{symbol}")
def prices(symbol: str, limit: Annotated[int, Query(ge=1,le=500)] = 30):
    symbol = symbol.upper()
    if symbol not in BY_SYMBOL:
        raise HTTPException(404,"Symbol not in demo portfolio")
    items = database.price_history(symbol,limit)
    return {"symbol":symbol,"count":len(items),"prices":items,
            "message":None if items else "No prices stored for this symbol yet"}


@app.get("/api/sync-status")
def sync_status():
    return {"stocks":database.last_syncs()}


@app.get("/api/filings/status")
def filings_status():
    items = database.filing_status()
    return {"source":"NSE","symbols_checked":len(items),
            "symbols_failed":sum(x["status"]=="error" for x in items),"stocks":items,
            "official_source":"https://www.nseindia.com/companies-listing/corporate-filings-announcements"}


@app.get("/api/briefing")
def briefing(hours: Annotated[int,Query(ge=1,le=2160)] = 24,
             include_routine: bool = False,
             start: datetime | None = None, end: datetime | None = None):
    since,until = window(hours,start,end)
    records = database.get_filings(since,until)
    important = [r for r in records if r["priority"]!="routine"]
    routine = [r for r in records if r["priority"]=="routine"]
    return {"window":{"start_utc":since,"end_utc":until},
            "source":"NSE","filing_source_status":database.filing_status(),
            "counts":{"all":len(records),"high":sum(x["priority"]=="high" for x in records),
                      "review":sum(x["priority"]=="review" for x in records),
                      "routine":len(routine)},
            "important":important,
            "routine_collapsed":not include_routine,
            "routine":routine if include_routine else [],
            "note":("Results are stored observations, not a guarantee of a complete live exchange feed. "
                    "If the latest filing sync failed, existing filings remain available with their original timestamps.")}


@app.get("/api/announcements/{filing_id}")
def announcement(filing_id: str):
    row=database.get_filing(filing_id)
    if row is None:
        raise HTTPException(404,"Filing not found")
    return row


@app.get("/api/pdf-analysis/status")
def pdf_analysis_status():
    return database.pdf_cache_stats()


@app.get("/api/preferences/alerts")
def get_alert_preferences():
    return database.get_preferences()


@app.put("/api/preferences/alerts")
def put_alert_preferences(prefs: AlertSettings):
    saved = database.update_preferences(prefs.model_dump())
    rebuilt = rebuild_alerts()
    return {"settings":saved,"alerts_recomputed":rebuilt,
            "note":"Derived alerts re-evaluated from stored primary records using new settings"}


@app.get("/api/alerts")
def alerts(hours: Annotated[int,Query(ge=1,le=2160)] = 24,
           start: datetime | None = None, end: datetime | None = None):
    since,until = window(hours,start,end)
    items = database.list_alerts(since,until)
    return {"window":{"start_utc":since,"end_utc":until},"count":len(items),
            "alerts":items,"note":"Market signals refer to EOD trading sessions, not intraday real-time quotes."}
