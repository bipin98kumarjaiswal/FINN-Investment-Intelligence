from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from app.main import app
from app.nse_filings import parse_nse_record
from app import database


def test_endpoints_and_routine_collapse(monkeypatch,tmp_path):
    path=tmp_path/"api.sqlite3"
    monkeypatch.setenv("FINN_DB_PATH",str(path))
    with TestClient(app) as client:
        assert client.get("/health").status_code==200
        assert client.get("/api/portfolio").json()["count"]==16
        assert client.get("/api/prices/INFY").json()["prices"]==[]
        assert client.get("/api/prices/INVALID").status_code==404
        assert client.get("/api/briefing").json()["counts"]["all"]==0
        assert client.get("/api/filings/status").json()["symbols_checked"]==0
        now=datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%b-%Y %H:%M:%S")
        records=[
            {"symbol":"INFY", "desc":"Change in Management", "attchmntText":"CFO resigned from the company", "an_dt":now, "seq_id":"test-1"},
            {"symbol":"INFY", "desc":"Trading Window Closure", "attchmntText":"Trading window closure", "an_dt":now, "seq_id":"test-2"},
        ]
        database.save_announcements([parse_nse_record(row,"INFY") for row in records],path)
        response=client.get("/api/briefing")
        assert response.status_code==200
        result=response.json()
        assert result["counts"]=={"all":2,"high":1,"review":0,"routine":1}
        assert len(result["important"])==1
        assert result["routine"]==[]
        expanded=client.get("/api/briefing?include_routine=true").json()
        assert len(expanded["routine"])==1
        doc_id=result["important"][0]["filing_id"]
        assert client.get(f"/api/announcements/{doc_id}").status_code==200
        assert client.get("/api/announcements/nope").status_code==404
        assert client.get("/api/briefing?hours=0").status_code==422
        assert client.get("/api/briefing?start=2026-10-01T00:00:00Z").status_code==422
        prefs=client.get("/api/preferences/alerts").json()
        assert prefs["volume_lookback"]==20
        response=client.put("/api/preferences/alerts",json={
            "price_change_pct":4,"volume_multiple":2.5,"volume_lookback":20,
            "categories":["management_change"]})
        assert response.status_code==200
        assert client.get("/api/alerts?hours=24").json()["count"]==1
        assert client.put("/api/preferences/alerts",json={
            "price_change_pct":-1,"volume_multiple":2,"volume_lookback":20,
            "categories":[]}).status_code==422
        assert client.put("/api/preferences/alerts",json={
            "price_change_pct":5,"volume_multiple":2,"volume_lookback":20,
            "categories":["not_category"]}).status_code==422
