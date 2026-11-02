"""Test that upgrading a real-shaped Phase 1 DB never erases price observations."""
import sqlite3
from app import database


def test_phase1_records_survive_phase2_init(tmp_path):
    path=tmp_path/"existing_phase1.sqlite3"
    conn=sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE companies(symbol TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL);
        CREATE TABLE daily_prices(
            symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
            open REAL NOT NULL,high REAL NOT NULL,low REAL NOT NULL,close REAL NOT NULL,
            volume INTEGER NOT NULL,provider TEXT NOT NULL,fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY(symbol,trade_date));
        CREATE TABLE sync_log(id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,attempted_at_utc TEXT NOT NULL,status TEXT NOT NULL,
            rows_received INTEGER NOT NULL,message TEXT);
        INSERT INTO companies VALUES ('INFY','Infosys','IT Services');
        INSERT INTO daily_prices VALUES
            ('INFY','2026-10-30',100,104,99,102,100000,'Yahoo Finance','2026-11-01T09:01:00+00:00');
    """)
    conn.commit()
    conn.close()
    database.init_db(path)
    rows=database.price_history("INFY",10,path)
    assert len(rows)==1 and rows[0]["close"]==102
    assert len(database.portfolio_latest(path))==16
    assert database.get_preferences(path)["volume_multiple"]==2.0
    database.init_db(path)
    assert len(database.price_history("INFY",10,path))==1
