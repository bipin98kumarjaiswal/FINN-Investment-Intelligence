"""SQLite persistence; additive schema upgrade from Phase 1, no data deletion."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone

from app.portfolio import PORTFOLIO

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "finn.sqlite3"


def db_path() -> Path:
    return Path(os.getenv("FINN_DB_PATH", str(DEFAULT_DB)))


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db(path: Path | None = None) -> None:
    with closing(connect(path)) as conn:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS companies (
                    symbol TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    sector TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daily_prices (
                    symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
                    open REAL NOT NULL, high REAL NOT NULL,
                    low REAL NOT NULL, close REAL NOT NULL,
                    volume INTEGER NOT NULL CHECK(volume >= 0),
                    provider TEXT NOT NULL, fetched_at_utc TEXT NOT NULL,
                    PRIMARY KEY (symbol, trade_date),
                    FOREIGN KEY(symbol) REFERENCES companies(symbol)
                );
                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL, attempted_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ok','error')),
                    rows_received INTEGER NOT NULL, message TEXT,
                    FOREIGN KEY(symbol) REFERENCES companies(symbol)
                );
                CREATE INDEX IF NOT EXISTS idx_prices_date ON daily_prices(trade_date);
                CREATE TABLE IF NOT EXISTS announcements (
                    filing_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL REFERENCES companies(symbol),
                    company_name TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    details TEXT NOT NULL,
                    published_at_utc TEXT NOT NULL,
                    source_url TEXT,
                    exchange TEXT NOT NULL CHECK(exchange='NSE'),
                    category TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    what_happened TEXT NOT NULL,
                    why_it_matters TEXT NOT NULL,
                    priority_reason TEXT NOT NULL,
                    evidence_scope TEXT NOT NULL,
                    ingested_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ann_date
                    ON announcements(published_at_utc);
                CREATE INDEX IF NOT EXISTS idx_ann_symbol
                    ON announcements(symbol, published_at_utc);
                CREATE TABLE IF NOT EXISTS filing_sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL REFERENCES companies(symbol),
                    attempted_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ok','error')),
                    rows_received INTEGER NOT NULL,
                    message TEXT
                );
                CREATE TABLE IF NOT EXISTS alert_preferences (
                    profile TEXT PRIMARY KEY,
                    price_change_pct REAL NOT NULL CHECK(price_change_pct>0),
                    volume_multiple REAL NOT NULL CHECK(volume_multiple>=1),
                    volume_lookback INTEGER NOT NULL CHECK(volume_lookback>=5),
                    categories_json TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL REFERENCES companies(symbol),
                    alert_type TEXT NOT NULL,
                    event_time_utc TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    source_url TEXT,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_alert_date ON alerts(event_time_utc);
                CREATE TABLE IF NOT EXISTS pdf_text_cache (
                    source_url TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    char_count INTEGER NOT NULL,
                    pages_zlib BLOB NOT NULL,
                    extracted_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS filing_pdf_analysis (
                    filing_id TEXT PRIMARY KEY REFERENCES announcements(filing_id),
                    analysis_version TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    stage1_score INTEGER NOT NULL,
                    subject_snapshot TEXT NOT NULL,
                    details_snapshot TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ok','error')),
                    sha256 TEXT,
                    score INTEGER,
                    priority TEXT,
                    breakdown_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    what_happened TEXT,
                    why_it_matters TEXT,
                    priority_reason TEXT,
                    evidence_scope TEXT,
                    error TEXT,
                    analysed_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pdf_analysis_status
                    ON filing_pdf_analysis(status,analysed_at_utc);

            """)
            conn.executemany("""
                INSERT INTO companies(symbol,name,sector)
                VALUES (:symbol,:name,:sector)
                ON CONFLICT(symbol) DO UPDATE
                SET name=excluded.name,sector=excluded.sector
            """, PORTFOLIO)
            conn.execute("""
                INSERT OR IGNORE INTO alert_preferences
                (profile,price_change_pct,volume_multiple,volume_lookback,categories_json,updated_at_utc)
                VALUES ('default',5.0,2.0,20,?,?)
            """, (json.dumps(["results", "M&A", "management_change", "litigation", "credit_rating", "pledging"]),
                  datetime.now(timezone.utc).isoformat()))


def save_prices(symbol: str, records: list[dict], timestamp: str,
                path: Path | None = None) -> int:
    with closing(connect(path)) as conn:
        with conn:
            conn.executemany("""
                INSERT INTO daily_prices
                (symbol,trade_date,open,high,low,close,volume,provider,fetched_at_utc)
                VALUES (:symbol,:trade_date,:open,:high,:low,:close,:volume,:provider,:fetched_at_utc)
                ON CONFLICT(symbol,trade_date) DO UPDATE SET
                    open=excluded.open, high=excluded.high,low=excluded.low,
                    close=excluded.close,volume=excluded.volume,
                    provider=excluded.provider,fetched_at_utc=excluded.fetched_at_utc
            """, [dict(row,symbol=symbol,provider="Yahoo Finance",fetched_at_utc=timestamp)
                  for row in records])
    return len(records)


def save_sync_status(symbol: str, timestamp: str, status: str, count: int,
                     message: str | None = None, path: Path | None = None) -> None:
    with closing(connect(path)) as conn:
        with conn:
            conn.execute("""
                INSERT INTO sync_log(symbol,attempted_at_utc,status,rows_received,message)
                VALUES (?,?,?,?,?)
            """, (symbol,timestamp,status,count,message))


def portfolio_latest(path: Path | None = None) -> list[dict]:
    with closing(connect(path)) as conn:
        records = conn.execute("""
            SELECT c.symbol,c.name,c.sector,p.trade_date,p.close,p.volume,
                   p.provider,p.fetched_at_utc
            FROM companies c LEFT JOIN daily_prices p ON p.symbol=c.symbol
                AND p.trade_date=(SELECT MAX(d.trade_date) FROM daily_prices d
                                  WHERE d.symbol=c.symbol)
            ORDER BY c.symbol
        """).fetchall()
        return [dict(r) for r in records]


def price_history(symbol: str, limit: int = 30,
                  path: Path | None = None) -> list[dict]:
    with closing(connect(path)) as conn:
        return [dict(r) for r in conn.execute("""
            SELECT trade_date,open,high,low,close,volume,provider,fetched_at_utc
            FROM daily_prices WHERE symbol=? ORDER BY trade_date DESC LIMIT ?
        """, (symbol,limit)).fetchall()]


def last_syncs(path: Path | None = None) -> list[dict]:
    with closing(connect(path)) as conn:
        return [dict(r) for r in conn.execute("""
            SELECT s.symbol,s.attempted_at_utc,s.status,s.rows_received,s.message
            FROM sync_log s WHERE s.id=(SELECT MAX(s2.id) FROM sync_log s2 WHERE s2.symbol=s.symbol)
            ORDER BY s.symbol
        """).fetchall()]


def save_announcements(items: list[dict], path: Path | None = None) -> int:
    with closing(connect(path)) as conn:
        with conn:
            conn.executemany("""
                INSERT INTO announcements
                (filing_id,symbol,company_name,subject,details,published_at_utc,
                 source_url,exchange,category,priority,score,what_happened,
                 why_it_matters,priority_reason,evidence_scope,ingested_at_utc)
                VALUES (:filing_id,:symbol,:company_name,:subject,:details,
                        :published_at_utc,:source_url,:exchange,:category,:priority,
                        :score,:what_happened,:why_it_matters,:priority_reason,
                        :evidence_scope,:ingested_at_utc)
                ON CONFLICT(filing_id) DO UPDATE SET
                    details=excluded.details,source_url=excluded.source_url,
                    category=excluded.category,priority=excluded.priority,
                    score=excluded.score,what_happened=excluded.what_happened,
                    why_it_matters=excluded.why_it_matters,
                    priority_reason=excluded.priority_reason,
                    evidence_scope=excluded.evidence_scope,
                    ingested_at_utc=excluded.ingested_at_utc
            """, items)
    return len(items)


def record_filing_sync(symbol: str, status: str, count: int,
                      message: str | None = None, path: Path | None = None) -> None:
    with closing(connect(path)) as conn:
        with conn:
            conn.execute("""
                INSERT INTO filing_sync_log(symbol,attempted_at_utc,status,rows_received,message)
                VALUES (?,?,?,?,?)
            """, (symbol,datetime.now(timezone.utc).isoformat(),status,count,message))


def filing_status(path: Path | None = None) -> list[dict]:
    with closing(connect(path)) as conn:
        return [dict(r) for r in conn.execute("""
            SELECT f.symbol,f.attempted_at_utc,f.status,f.rows_received,f.message
            FROM filing_sync_log f
            WHERE f.id=(SELECT MAX(f2.id) FROM filing_sync_log f2 WHERE f2.symbol=f.symbol)
            ORDER BY f.symbol
        """).fetchall()]


def _effective_filing(row: sqlite3.Row) -> dict:
    """Resolve cached PDF score only when it matches current NSE metadata/source/version."""
    from app.classifier import evaluate
    from app.pdf_priority import VERSION
    item = dict(row)
    base = evaluate(item["subject"],item["details"])
    item["metadata_score"] = item["score"]
    item["metadata_priority"] = item["priority"]
    item["score_breakdown"] = {
        "stage1_score":item["score"], "pdf_adjustment":0,
        "final_score":item["score"],
        "thresholds":{"high":70,"review":40},
        "components":base["score_components"],
    }
    status = item.pop("pdf_status")
    item["pdf_analysis_status"] = status or (
        "not_selected" if item["metadata_score"] < 40 else (
            "no_attachment" if not item["source_url"] else "pending"))
    item["pdf_error"] = item.pop("pdf_error")
    item["pdf_sha256"] = item.pop("pdf_sha256")
    item["pdf_analysed_at_utc"] = item.pop("pdf_analysed_at")
    pdf_score = item.pop("pdf_score")
    pdf_priority = item.pop("pdf_priority")
    pdf_components = item.pop("pdf_breakdown_json")
    pdf_evidence = item.pop("pdf_evidence_json")
    pdf_what = item.pop("pdf_what")
    pdf_why = item.pop("pdf_why")
    pdf_reason = item.pop("pdf_reason")
    pdf_scope = item.pop("pdf_scope")
    item["pdf_evidence"] = []
    if status == "ok" and pdf_score is not None:
        item["score"] = pdf_score
        item["priority"] = pdf_priority
        item["what_happened"] = pdf_what
        item["why_it_matters"] = pdf_why
        item["priority_reason"] = pdf_reason
        item["evidence_scope"] = pdf_scope
        item["score_breakdown"] = {
            "stage1_score":item["metadata_score"],
            "pdf_adjustment":pdf_score-item["metadata_score"],
            "final_score":pdf_score,
            "thresholds":{"high":70,"review":40},
            "components":json.loads(pdf_components),
        }
        item["pdf_evidence"] = json.loads(pdf_evidence)
    elif status == "error":
        if (item["pdf_error"] or "").find("PDF_LIMIT_EXCEEDED:") >= 0:
            item["pdf_analysis_status"] = "skipped_too_large"
            item["evidence_scope"] += "; PDF deliberately skipped due to resource limit; metadata priority retained"
        else:
            item["evidence_scope"] += "; PDF attempt failed; metadata priority retained"
    return item


_EFFECTIVE_JOIN = """
    SELECT a.*,p.status AS pdf_status,p.score AS pdf_score,
           p.priority AS pdf_priority,p.breakdown_json AS pdf_breakdown_json,
           p.evidence_json AS pdf_evidence_json,p.what_happened AS pdf_what,
           p.why_it_matters AS pdf_why,p.priority_reason AS pdf_reason,
           p.evidence_scope AS pdf_scope,p.error AS pdf_error,
           p.sha256 AS pdf_sha256,p.analysed_at_utc AS pdf_analysed_at
    FROM announcements a LEFT JOIN filing_pdf_analysis p ON
         p.filing_id=a.filing_id AND p.source_url=a.source_url
         AND p.stage1_score=a.score AND p.subject_snapshot=a.subject
         AND p.details_snapshot=a.details AND p.analysis_version='pdf_rules_v2_context'
"""


def get_filings(start_utc: str, end_utc: str,
                path: Path | None = None) -> list[dict]:
    with closing(connect(path)) as conn:
        rows=conn.execute(_EFFECTIVE_JOIN+"""
            WHERE a.published_at_utc>=? AND a.published_at_utc<=?
            ORDER BY COALESCE(CASE WHEN p.status='ok' THEN p.score END,a.score) DESC,
                     a.published_at_utc DESC
        """,(start_utc,end_utc)).fetchall()
    return [_effective_filing(r) for r in rows]


def get_filing(filing_id: str, path: Path | None = None) -> dict | None:
    with closing(connect(path)) as conn:
        row=conn.execute(_EFFECTIVE_JOIN+" WHERE a.filing_id=?",(filing_id,)).fetchone()
    return _effective_filing(row) if row is not None else None


def pdf_cache_stats(path: Path | None = None) -> dict:
    with closing(connect(path)) as conn:
        cache=conn.execute("SELECT COUNT(*),COALESCE(SUM(char_count),0) FROM pdf_text_cache").fetchone()
        done=conn.execute("""SELECT CASE WHEN status='error' AND error LIKE '%PDF_LIMIT_EXCEEDED:%'
                            THEN 'skipped_too_large' ELSE status END AS effective_status,
                            COUNT(*) FROM filing_pdf_analysis GROUP BY effective_status""").fetchall()
    return {"cached_documents":cache[0],"extracted_characters":cache[1],
            "analyses":{r[0]:r[1] for r in done}}


def get_preferences(path: Path | None = None) -> dict:
    with closing(connect(path)) as conn:
        row = conn.execute("SELECT * FROM alert_preferences WHERE profile='default'").fetchone()
    if row is None:
        raise RuntimeError("Run init_db first")
    value = dict(row)
    value["categories"] = json.loads(value.pop("categories_json"))
    return value


def update_preferences(value: dict, path: Path | None = None) -> dict:
    with closing(connect(path)) as conn:
        with conn:
            conn.execute("""
                UPDATE alert_preferences
                SET price_change_pct=?,volume_multiple=?,volume_lookback=?,
                    categories_json=?,updated_at_utc=? WHERE profile='default'
            """, (value["price_change_pct"],value["volume_multiple"],
                  value["volume_lookback"],json.dumps(value["categories"]),
                  datetime.now(timezone.utc).isoformat()))
    return get_preferences(path)


def save_alerts(alerts: list[dict], path: Path | None = None) -> int:
    with closing(connect(path)) as conn:
        before = conn.total_changes
        with conn:
            conn.executemany("""
                INSERT OR IGNORE INTO alerts
                (alert_id,symbol,alert_type,event_time_utc,observed_at_utc,
                 headline,explanation,source_url,details_json)
                VALUES (:alert_id,:symbol,:alert_type,:event_time_utc,:observed_at_utc,
                        :headline,:explanation,:source_url,:details_json)
            """, alerts)
        return conn.total_changes - before


def list_alerts(start_utc: str, end_utc: str,
                path: Path | None = None) -> list[dict]:
    with closing(connect(path)) as conn:
        rows = conn.execute("""
            SELECT * FROM alerts WHERE event_time_utc>=? AND event_time_utc<=?
            ORDER BY event_time_utc DESC
        """, (start_utc,end_utc)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json"))
        result.append(item)
    return result
