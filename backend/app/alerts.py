"""Persistent rule-based alerts derived only from stored real filings and EOD bars."""
import json
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from contextlib import closing
from app import database

IST = ZoneInfo("Asia/Kolkata")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _eod_in_utc(trade_date: str) -> str:
    day = datetime.fromisoformat(trade_date).date()
    return datetime.combine(day, time(15, 30), IST).astimezone(timezone.utc).isoformat()


def sync_market_alerts(path: Path | None = None) -> dict:
    """Calculate alerts across 90 days of historic daily prices.

    Price changes use the preceding close; volume ratio uses precisely N
    *preceding* trading sessions. No alert if sufficient history is unavailable.
    """
    database.init_db(path)
    prefs = database.get_preferences(path)
    cutoff = (_now().astimezone(IST).date() - timedelta(days=90)).isoformat()
    count_before = 0
    generated = []
    with closing(database.connect(path)) as conn:
        companies = [r[0] for r in conn.execute("SELECT symbol FROM companies")]
        for symbol in companies:
            bars = [dict(r) for r in conn.execute("""
                SELECT trade_date,close,volume,fetched_at_utc FROM daily_prices
                WHERE symbol=? ORDER BY trade_date ASC
            """, (symbol,))]
            n = prefs["volume_lookback"]
            for i in range(1, len(bars)):
                bar = bars[i]
                if bar["trade_date"] < cutoff:
                    continue
                prev = bars[i-1]
                event_time = _eod_in_utc(bar["trade_date"])
                observed = bar["fetched_at_utc"]
                movement = (bar["close"] / prev["close"] - 1) * 100 if prev["close"] else None
                if movement is not None and abs(movement) >= prefs["price_change_pct"]:
                    generated.append({
                        "alert_id": f"price:{symbol}:{bar['trade_date']}","symbol":symbol,
                        "alert_type":"price","event_time_utc":event_time,
                        "observed_at_utc":observed,"source_url":None,
                        "headline":f"{symbol}: {movement:+.2f}% close-to-close move",
                        "explanation": ("Daily close changed beyond your configured threshold. "
                                        "This does not establish the cause; verify corporate actions and filings."),
                        "details_json":json.dumps({"trade_date":bar["trade_date"],
                            "close":bar["close"],"previous_close":prev["close"],
                            "price_change_pct":round(movement,4),"threshold_pct":prefs["price_change_pct"],
                            "time_basis":"NSE market session close (approx. 15:30 IST)"}),
                    })
                if i >= n:
                    average = sum(x["volume"] for x in bars[i-n:i]) / n
                    if average > 0 and bar["volume"] / average >= prefs["volume_multiple"]:
                        ratio = bar["volume"] / average
                        generated.append({
                            "alert_id":f"volume:{symbol}:{bar['trade_date']}","symbol":symbol,
                            "alert_type":"volume","event_time_utc":event_time,
                            "observed_at_utc":observed,"source_url":None,
                            "headline":f"{symbol}: {ratio:.2f}× normal trading volume",
                            "explanation": ("Volume exceeded your threshold relative to prior sessions. "
                                            "Volume alone does not explain the reason for trading activity."),
                            "details_json":json.dumps({"trade_date":bar["trade_date"],
                                "volume":bar["volume"],"average_prior_volume":round(average,2),
                                "volume_ratio":round(ratio,4),"lookback_sessions":n,
                                "threshold_multiple":prefs["volume_multiple"],
                                "time_basis":"NSE market session close (approx. 15:30 IST)"}),
                        })
    # Deduplication is enforced by alert_id primary key.
    with closing(database.connect(path)) as conn:
        before = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    database.save_alerts(generated, path)
    with closing(database.connect(path)) as conn:
        after = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    return {"new_alerts":after-before,"matching_signals":len(generated),
            "price_threshold_pct":prefs["price_change_pct"],
            "volume_threshold_multiple":prefs["volume_multiple"]}


def sync_filing_alerts(path: Path | None = None) -> dict:
    database.init_db(path)
    prefs = database.get_preferences(path)
    start = (_now() - timedelta(days=90)).isoformat()
    records = [r for r in database.get_filings(start, _now().isoformat(), path)
               if r["priority"] != "routine"]
    with closing(database.connect(path)) as conn:
        before = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    matched = [r for r in records if r["category"] in prefs["categories"]]
    generated = [{
        "alert_id": "filing:"+r["filing_id"],"symbol":r["symbol"],
        "alert_type":"filing","event_time_utc":r["published_at_utc"],
        "observed_at_utc":r["ingested_at_utc"],
        "headline":f'{r["symbol"]}: {r["subject"]}',
        "explanation":r["what_happened"] + " " + r["why_it_matters"],
        "source_url":r["source_url"],
        "details_json":json.dumps({"category":r["category"],"priority":r["priority"],
            "score":r["score"],"filing_id":r["filing_id"],
            "evidence_scope":r["evidence_scope"]}),
    } for r in matched]
    database.save_alerts(generated, path)
    with closing(database.connect(path)) as conn:
        after = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    return {"new_alerts":after-before,"matching_filings":len(matched)}


def rebuild_alerts(path: Path | None = None) -> dict:
    """When preferences change, discard derived alerts and rebuild from stored data.
    This is a one-user prototype; alerts are reproducible and have no read state.
    """
    database.init_db(path)
    with closing(database.connect(path)) as conn:
        with conn:
            conn.execute("DELETE FROM alerts")
    return {"market":sync_market_alerts(path),"filings":sync_filing_alerts(path)}
