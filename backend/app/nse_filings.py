"""Genuine NSE equity announcement ingestion.

Uses the exchange's public, undocumented website endpoint; access may be
rate-limited. If it fails, logs an error and does NOT manufacture events.
"""
from datetime import datetime, date, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import time
import requests

from app import database
from app.classifier import evaluate
from app.portfolio import PORTFOLIO, BY_SYMBOL

IST = ZoneInfo("Asia/Kolkata")
BASE = "https://www.nseindia.com"
LANDING = f"{BASE}/companies-listing/corporate-filings-announcements"
ENDPOINT = f"{BASE}/api/corporate-announcements"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": LANDING,
}


class FilingSourceError(RuntimeError):
    pass


def valid_attachment(url: object) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    value = url.strip()
    if value.startswith("/") and not value.startswith("//"):
        value = BASE + value
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or
        parsed.hostname not in {"nsearchives.nseindia.com", "www.nseindia.com", "nseindia.com"}):
        return None
    return value


def parse_exchange_date(value: object) -> str:
    """NSE broadcast times are in India Standard Time; store as ISO UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing NSE announcement timestamp")
    value = value.strip()
    dt = None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%m-%Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        raise ValueError(f"Unexpected NSE date format: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc).isoformat()


def parse_nse_record(raw: dict, symbol: str,
                     fetched_at_utc: str | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("NSE record must be an object")
    if str(raw.get("symbol") or "").strip().upper() != symbol:
        raise ValueError("NSE record symbol does not match requested symbol")
    when = parse_exchange_date(raw.get("an_dt") or raw.get("sort_date"))
    subject = str(raw.get("desc") or "").strip()
    details = str(raw.get("attchmntText") or "").strip()
    if not subject and not details:
        raise ValueError("NSE announcement has no subject or description")
    source_url = valid_attachment(raw.get("attchmntFile"))
    seq = str(raw.get("seq_id") or "").strip()
    fingerprint = (f"NSE|{symbol}|id:{seq}" if seq else
                   f"NSE|{symbol}|{when}|{subject}|{details}|{source_url or ''}")
    filing_id = sha256(fingerprint.encode("utf-8")).hexdigest()[:32]
    result = evaluate(subject, details)
    return {
        "filing_id": filing_id, "symbol": symbol,
        "company_name": str(raw.get("sm_name") or BY_SYMBOL[symbol]["name"]),
        "subject": subject or "NSE exchange announcement", "details": details,
        "published_at_utc": when, "source_url": source_url, "exchange": "NSE",
        "ingested_at_utc": fetched_at_utc or datetime.now(timezone.utc).isoformat(),
        **result,
    }


def response_records(response: requests.Response) -> list[dict]:
    if response.status_code in (401, 403, 429):
        raise FilingSourceError(f"NSE denied access (HTTP {response.status_code}). Try a later refresh or inspect the official NSE page.")
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FilingSourceError(f"NSE HTTP failure: {exc}") from exc
    if "html" in response.headers.get("Content-Type", "").lower():
        raise FilingSourceError("NSE returned HTML instead of filing JSON (possibly an anti-bot page)")
    try:
        payload = response.json()
    except ValueError as exc:
        raise FilingSourceError("NSE response is not valid JSON") from exc
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        payload = payload["data"]
    if not isinstance(payload, list):
        raise FilingSourceError("Unexpected NSE response schema; expected a list of announcements")
    return payload


def sync_filings(days: int = 7, symbols: list[str] | None = None,
                 path: Path | None = None, session=None,
                 sleep_seconds: float = 0.35, today: date | None = None) -> dict:
    """Fetch separately per NSE ticker to avoid hiding missing companies.

    One date-window per symbol; NSE date range inclusive and in IST.
    `session` allows fake transport in tests ONLY, never synthetic production data.
    """
    if not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")
    symbols = list(BY_SYMBOL) if symbols is None else [s.strip().upper() for s in symbols]
    if not symbols or any(s not in BY_SYMBOL for s in symbols):
        raise ValueError("Specify at least one valid portfolio NSE symbol")
    symbols = list(dict.fromkeys(symbols))
    database.init_db(path)
    end = today or datetime.now(IST).date()
    start = end - timedelta(days=days)
    created_session = session is None
    client = requests.Session() if created_session else session
    output = []
    total = 0
    try:
        if created_session:
            client.headers.update(HEADERS)
            try:
                landing_response = client.get(LANDING, timeout=15)
                landing_response.raise_for_status()
            except requests.RequestException as exc:
                reason = f"NSE session initialization failed: {type(exc).__name__}: {exc}"
                for symbol in symbols:
                    database.record_filing_sync(symbol, "error", 0, reason, path)
                    output.append({"symbol":symbol,"status":"error","saved":0,"message":reason})
                return {"source":"NSE","from_date":str(start),"to_date":str(end),
                        "ok":0,"failed":len(symbols),"rows_saved":0,"results":output}
        for pos, symbol in enumerate(symbols):
            try:
                if pos and created_session and sleep_seconds:
                    time.sleep(sleep_seconds)
                response = client.get(ENDPOINT, params={
                    "index":"equities", "symbol":symbol,
                    "from_date":start.strftime("%d-%m-%Y"),
                    "to_date":end.strftime("%d-%m-%Y"),
                }, timeout=15)
                payload = response_records(response)
                parsed = []
                skipped = 0
                for raw in payload:
                    try:
                        parsed.append(parse_nse_record(raw, symbol))
                    except (ValueError, TypeError, KeyError):
                        skipped += 1
                # Never treat a nonempty but wholly invalid result as a clean empty feed.
                if payload and not parsed:
                    raise FilingSourceError("All returned NSE items failed validation; schema may have changed")
                if parsed:
                    database.save_announcements(parsed, path)
                count = len(parsed)
                total += count
                warning = (f"Skipped {skipped} invalid/mismatched records" if skipped else None)
                database.record_filing_sync(symbol, "ok", count, warning, path)
                output.append({"symbol":symbol,"status":"ok","saved":count,
                               "skipped":skipped,"message":warning})
            except (requests.RequestException, FilingSourceError, ValueError) as exc:
                reason = f"{type(exc).__name__}: {exc}"
                database.record_filing_sync(symbol, "error", 0, reason, path)
                output.append({"symbol":symbol,"status":"error","saved":0,"message":reason})
                # On access denial avoid hammering the source for remaining symbols.
                if isinstance(exc, FilingSourceError) and "denied access" in str(exc):
                    for rest in symbols[pos+1:]:
                        msg = "Skipped after NSE access denial; not fetched"
                        database.record_filing_sync(rest, "error", 0, msg, path)
                        output.append({"symbol":rest,"status":"error","saved":0,"message":msg})
                    break
    finally:
        if created_session:
            client.close()
    ok = sum(row["status"] == "ok" for row in output)
    return {"source":"NSE","from_date":str(start),"to_date":str(end),
            "ok":ok,"failed":len(symbols)-ok,"rows_saved":total,"results":output}
