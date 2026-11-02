"""Offline PDF bytes, shaped like NSE responses, isolated temporary DB only.

Live verification is separately available in scripts/live_pdf_smoke.py.
"""
from datetime import date
from io import BytesIO

import fitz
import requests

from app import database
from app.nse_filings import parse_nse_record, sync_filings
from app.pdf_priority import (
    DocumentFailure, candidates, enrich_filings, extract_pages, fetch_pdf,
    read_document, score_document, trusted_pdf_url,
)


class PDFResponse:
    def __init__(self, data, status=200, headers=None):
        self.data=data
        self.status_code=status
        self.headers=headers or {"Content-Type":"application/pdf"}
        self.closed=False
    def iter_content(self, chunk_size=65536):
        for i in range(0,len(self.data),chunk_size):
            yield self.data[i:i+chunk_size]
    def raise_for_status(self):
        if self.status_code>=400:
            raise requests.HTTPError(self.status_code)
    def close(self):
        self.closed=True


class PDFSession:
    def __init__(self, response):
        self.response=response
        self.calls=0
    def get(self, url, **kwargs):
        self.calls+=1
        assert url.startswith("https://nsearchives.nseindia.com/")
        assert kwargs["stream"] is True
        assert kwargs["allow_redirects"] is False
        return self.response


def pdf_bytes(text):
    with fitz.open() as doc:
        page=doc.new_page()
        y=70
        for line in text.split("\n"):
            page.insert_text((70,y),line,fontname="helv",fontsize=11)
            y+=20
        return doc.tobytes()


def record(seq, subject, details, source="https://nsearchives.nseindia.com/corporate/TEST_SOURCE.pdf"):
    return parse_nse_record({
        "symbol":"INFY","seq_id":seq,"sm_name":"Infosys Limited",
        "desc":subject,"attchmntText":details,"an_dt":"30-Oct-2026 18:15:25",
        "attchmntFile":source,
    }, "INFY")


def test_only_material_candidates_selected_and_cache_reused(tmp_path):
    path=tmp_path/"data.sqlite3"
    database.init_db(path)
    important=record("A","Change in Management","Company announces change in senior management")
    second=record("B","Change in Management","Company announces change in senior management")
    routine=record("C","Trading Window Closure","Trading window closed")
    database.save_announcements([important,second,routine],path)
    assert {x["filing_id"] for x in candidates(path,max_files=10)}=={
        important["filing_id"],second["filing_id"]}

    content=pdf_bytes("Company Disclosure to National Stock Exchange of India Limited\n"
                      "Chief Financial Officer has resigned with effect from 31 October 2026.\n"
                      "This attachment reports a change in key managerial personnel.\n"
                      "The company has made this submission in compliance with listing rules.\n")
    session=PDFSession(PDFResponse(content))
    outcome=enrich_filings(path=path,max_files=10,session=session)
    assert outcome["ok"]==2 and outcome["failed"]==0
    assert session.calls==1, "The second filing should reuse the first filing's cached PDF text"
    assert sorted(x["cache_hit"] for x in outcome["results"])==[False,True]
    assert database.pdf_cache_stats(path)["cached_documents"]==1
    assert candidates(path,max_files=10)==[]

    stored=database.get_filing(important["filing_id"],path)
    assert stored["metadata_score"]==61
    assert stored["score"]==79
    assert stored["priority"]=="high"
    assert stored["pdf_analysis_status"]=="ok"
    assert stored["pdf_evidence"][0]["page"]==1
    assert "resigned" in stored["pdf_evidence"][0]["excerpt"].lower()
    breakdown=stored["score_breakdown"]
    assert sum(x["points"] for x in breakdown["components"])==stored["score"]
    assert breakdown["pdf_adjustment"]==18

    # Re-ingesting the same announcement never discards the cached analysis.
    database.save_announcements([important],path)
    assert database.get_filing(important["filing_id"],path)["score"]==79
    # Changing metadata must invalidate stale PDF score until recomputed.
    changed=dict(important,details="Change in directors; independent director appointed")
    changed.update({k:v for k,v in __import__("app.classifier",fromlist=["evaluate"]).evaluate(
        changed["subject"],changed["details"]).items()})
    database.save_announcements([changed],path)
    fresh=database.get_filing(important["filing_id"],path)
    assert fresh["pdf_analysis_status"]=="pending"
    assert fresh["score"]==changed["score"]


def test_failed_download_keeps_metadata_score_and_reports_source_failure(tmp_path):
    path=tmp_path/"data.sqlite3"
    database.init_db(path)
    event=record("A","Credit Rating","Rating upgraded to AA from A")
    database.save_announcements([event],path)
    fake=PDFSession(PDFResponse(b"<html>blocked</html>"))
    outcome=enrich_filings(path=path,max_files=3,session=fake)
    assert outcome["failed"]==1
    stored=database.get_filing(event["filing_id"],path)
    assert stored["score"]==event["score"]
    assert stored["pdf_analysis_status"]=="error"
    assert "not a PDF" in stored["pdf_error"]
    assert "failed" in stored["evidence_scope"].lower()
    assert candidates(path,max_files=3)==[], "Short failure backoff prevents immediate hammering"
    assert len(candidates(path,max_files=3,retry_failed=True))==1


def test_invalid_attachment_redirect_size_and_scanned_pdf(tmp_path):
    for bad_url in ("http://nsearchives.nseindia.com/file.pdf",
                    "https://evil.example.com/fake.pdf",
                    "https://nsearchives.nseindia.com.evil.com/pdf",
                    "https://nsearchives.nseindia.com:8443/filing.pdf"):
        try:
            trusted_pdf_url(bad_url)
        except DocumentFailure:
            pass
        else:
            raise AssertionError("Untrusted attachment accepted")
    url="https://nsearchives.nseindia.com/corporate/filing.pdf"
    try:
        fetch_pdf(url,PDFSession(PDFResponse(b"",status=302,headers={"Location":"https://evil.example.com/pdf"})))
    except DocumentFailure as exc:
        assert "untrusted" in str(exc).lower()
    else:
        raise AssertionError("Untrusted redirect accepted")
    scanned=pdf_bytes("Scanned")
    try:
        extract_pages(scanned)
    except DocumentFailure as exc:
        assert "selectable text" in str(exc)
    else:
        raise AssertionError("Too little selectable text accepted")
    try:
        fetch_pdf(url,PDFSession(PDFResponse(b"%PDF-",headers={"Content-Length":str(100_000_000)})))
    except DocumentFailure as exc:
        assert "maximum" in str(exc).lower()
    else:
        raise AssertionError("Oversized document accepted")


def test_document_rule_requires_source_excerpt_not_keyword_across_pages():
    event=record("A","Change in Management","Company announces change in senior management")
    no_evidence={"sha256":"test","page_count":1,"pages":[{"page":1,"text":
        "The CFO has extensive experience. A resignation was reported elsewhere. "*4}]}
    result=score_document(event,no_evidence)
    assert result["score"]==event["score"]
    assert result["evidence"]==[]
    assert sum(x["points"] for x in result["breakdown"])==result["score"]


def test_existing_price_data_survives_new_tables(tmp_path):
    path=tmp_path/"data.sqlite3"
    database.init_db(path)
    database.save_prices("INFY",[dict(trade_date="2026-10-30",open=100,high=103,
        low=99,close=101,volume=100000)],"2026-11-01T00:00:00+00:00",path)
    database.init_db(path)
    assert database.price_history("INFY",30,path)[0]["close"]==101


def test_same_category_different_pdf_materiality():
    # Stage-1 metadata is identical; the actual documents drive the difference.
    base=record("X","Credit Rating","Information about credit rating")
    assert base["score"]==63
    optimistic={"sha256":"good","page_count":1,"pages":[{"page":1,"text":
        "Credit rating agency has downgraded its rating on long term borrowing facilities. "*2}]}
    routine={"sha256":"routine","page_count":1,"pages":[{"page":1,"text":
        "The credit rating of the facilities has been reaffirmed by the rating agency. "*2}]}
    one=score_document(base,optimistic)
    two=score_document(base,routine)
    assert one["priority"]=="high" and one["score"]==85
    assert two["priority"]=="review" and two["score"]==51
    assert one["evidence"][0]["page"] == two["evidence"][0]["page"] == 1
    assert sum(x["points"] for x in one["breakdown"])==one["score"]
    assert sum(x["points"] for x in two["breakdown"])==two["score"]


def test_briefing_and_alerts_use_pdf_informed_score(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.alerts import sync_filing_alerts
    from datetime import datetime, timezone
    path=tmp_path/"api.sqlite3"
    monkeypatch.setenv("FINN_DB_PATH",str(path))
    database.init_db(path)
    item=record("X","Change in Management","Company announces change in senior management")
    # Use a current event time so it appears in the default 24h briefing.
    item["published_at_utc"]=datetime.now(timezone.utc).isoformat()
    database.save_announcements([item],path)
    doc={"sha256":"verified-pdf-digest","page_count":1,"pages":[{"page":1,"text":
        "The Chief Financial Officer has resigned with effect from today. "*2}]}
    from app.pdf_priority import save_analysis
    save_analysis(item,score_document(item,doc),path)
    with TestClient(app) as client:
        briefing=client.get("/api/briefing").json()
        assert briefing["counts"]["high"]==1
        assert briefing["important"][0]["score_breakdown"]["pdf_adjustment"]==18
        assert briefing["important"][0]["pdf_analysis_status"]=="ok"
        assert briefing["important"][0]["pdf_evidence"][0]["page"]==1
        detail=client.get("/api/announcements/"+item["filing_id"]).json()
        assert detail["source_url"]==item["source_url"]
        assert detail["score"]==79
        assert client.get("/api/pdf-analysis/status").status_code==200
        results=sync_filing_alerts(path)
        assert results["matching_filings"]==1
        alerts=client.get("/api/alerts").json()["alerts"]
        assert alerts[0]["details"]["score"]==79
