from datetime import date
from pathlib import Path
import requests
from app import database
from app.classifier import evaluate
from app.nse_filings import parse_exchange_date, parse_nse_record, sync_filings


# Structured like real NSE records, but synthetic and used ONLY in a test DB.
RAW_CFO = {
    "symbol":"INFY", "sm_name":"Infosys Limited", "desc":"Change in Management",
    "attchmntText":"Company informed the Exchange about resignation of CFO from the company.",
    "an_dt":"30-Oct-2026 18:15:25", "seq_id": "test-10001",
    "attchmntFile":"https://nsearchives.nseindia.com/corporate/TEST_CFO.pdf",
}
RAW_ROUTINE = {
    "symbol":"INFY","sm_name":"Infosys Limited",
    "desc":"Closure of Trading Window",
    "attchmntText":"Company informed the Exchange about closure of trading window.",
    "an_dt":"30-Oct-2026 17:11:25", "seq_id": "test-10002",
    "attchmntFile":"https://nsearchives.nseindia.com/corporate/TEST_WINDOW.pdf",
}


class FakeResponse:
    def __init__(self, data, status=200, content_type="application/json"):
        self.data=data
        self.status_code=status
        self.headers={"Content-Type":content_type}
    def raise_for_status(self):
        if self.status_code>=400:
            raise requests.HTTPError(f"HTTP {self.status_code}")
    def json(self):
        return self.data

class FakeSession:
    def __init__(self, response):
        self.response=response
        self.params=[]
    def get(self, url, params=None,timeout=15):
        self.params.append(params)
        return self.response


def test_parse_real_nse_shape_and_utc():
    assert parse_exchange_date("30-Oct-2026 18:15:25")=="2026-10-30T12:45:25+00:00"
    item=parse_nse_record(RAW_CFO,"INFY")
    assert item["exchange"]=="NSE"
    assert item["priority"]=="high"
    assert item["source_url"].endswith("TEST_CFO.pdf")
    assert "attachment not analysed" in item["evidence_scope"]
    assert parse_nse_record(RAW_CFO,"INFY")["filing_id"]==item["filing_id"]


def test_metadata_must_be_truthful():
    invalid=dict(RAW_CFO, attchmntFile="https://example.com/fake.pdf", seq_id="test-2")
    assert parse_nse_record(invalid,"INFY")["source_url"] is None
    assert evaluate("Compliance certificate", "Certificate under regulation 74(5)")["priority"]=="routine"
    assert evaluate("Credit rating", "Rating downgraded from AA to A")["priority"]=="high"
    assert evaluate("Credit rating", "Rating reaffirmed at AA")["priority"]!="high"
    assert evaluate("Board Meeting Intimation", "Board meeting scheduled for next week")["priority"]=="routine"
    assert evaluate("Financial Results", "Unaudited financial results for the quarter ended September 2026")["priority"]=="high"
    assert evaluate("Change in Management", "The CFO has resigned from the company")["priority"]=="high"


def test_filing_sync_deduplicates_and_saves_actual_shape(tmp_path):
    path=tmp_path/"test.sqlite3"
    fake=FakeSession(FakeResponse([RAW_CFO, RAW_ROUTINE]))
    r=sync_filings(days=7,symbols=["INFY"],path=path,session=fake,today=date(2026,11,1))
    assert r["ok"]==1 and r["rows_saved"]==2
    assert fake.params[0]["symbol"]=="INFY"
    assert fake.params[0]["from_date"]=="25-10-2026"
    assert fake.params[0]["to_date"]=="01-11-2026"
    assert len(database.get_filings("2026-10-29T00:00:00+00:00","2026-11-01T00:00:00+00:00",path))==2
    r=sync_filings(days=7,symbols=["INFY"],path=path,session=fake,today=date(2026,11,1))
    assert r["ok"]==1
    with database.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]==2


def test_blocked_nse_is_explicit_and_no_fake_filings(tmp_path):
    path=tmp_path/"test.sqlite3"
    fake=FakeSession(FakeResponse({"error":"Forbidden"},403))
    r=sync_filings(7,["INFY","RELIANCE"],path,fake,today=date(2026,11,1))
    assert r["failed"]==2 and r["ok"]==0
    assert "denied" in r["results"][0]["message"]
    assert "Skipped" in r["results"][1]["message"]
    assert database.get_filings("2026-10-01T00:00:00+00:00","2026-11-02T00:00:00+00:00",path)==[]
    assert all(r["status"]=="error" for r in database.filing_status(path))


def test_unexpected_schema_is_not_marked_ok(tmp_path):
    path=tmp_path/"test.sqlite3"
    r=sync_filings(7,["INFY"],path,FakeSession(FakeResponse({"unrelated":[]})),today=date(2026,11,1))
    assert r["failed"]==1
    assert database.get_filings("2026-10-01T00:00:00+00:00","2026-11-02T00:00:00+00:00",path)==[]
