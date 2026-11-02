"""Regression tests for RELIANCE false loss and SUNPHARMA size-limit handling.

All observations in this test file are synthetic and remain in temp databases.
"""
import pytest

from app import database
from app.nse_filings import parse_nse_record
from app.pdf_priority import (
    VERSION, candidates, enrich_filings, score_document, MAX_PDF_BYTES,
)


class PDFResponse:
    def __init__(self, content: bytes, headers: dict[str, str]):
        self.content = content
        self.headers = headers
        self.status_code = 200

    def iter_content(self, chunk_size=65536):
        for pos in range(0, len(self.content), chunk_size):
            yield self.content[pos:pos + chunk_size]

    def raise_for_status(self):
        pass

    def close(self):
        pass


class PDFSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        assert url.startswith("https://nsearchives.nseindia.com/")
        assert kwargs["stream"] is True
        return self.response


def filing(symbol="RELIANCE", id_="reliance-regression"):
    return parse_nse_record({
        "symbol": symbol, "seq_id": id_, "sm_name": symbol,
        "desc": "Financial Results", "attchmntText": "Quarterly financial results announced",
        "an_dt": "30-Oct-2026 18:15:25",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/REAL_NSE_TEST_PATH.pdf",
    }, symbol)


def document(*lines):
    return {"sha256": "test-digest", "page_count": 1,
            "pages": [{"page": 1, "text": "\n".join(lines)}]}


@pytest.mark.parametrize("text", [
    "Net Profit/Loss after tax (PAT) Rs. 350 crore",
    "Net Profit/(Loss) after tax 350.00 342.00 314.00",
    "Profit (Loss) for the period 350 342",
    "The company reported a net profit of Rs. 350 crore during the quarter.",
    "The company did not report a net loss of Rs. 350 crore during the quarter.",
    "The company reported a net loss of Rs. 100 crore in the previous quarter.",
    "The company reported a net loss of Rs. 100 crore.",
    "The company reported a net loss of Rs. 0 crore during the quarter.",
])
def test_loss_false_positives_do_not_add_points(text):
    event=filing()
    original=event["score"]
    analysed=score_document(event,document("Financial statements 2026",text))
    assert analysed["score"]==original, text
    assert not any("loss" in s["signal"].lower() for s in analysed["evidence"])
    assert "net loss" not in analysed["what_happened"].lower()
    assert sum(v["points"] for v in analysed["breakdown"])==analysed["score"]


def test_explicit_quantified_current_quarter_loss_can_add_points():
    event=filing()
    analysed=score_document(event,document(
        "Quarterly financial results for 2026",
        "The company reported a net loss of Rs. 123 crore in the current quarter."))
    assert analysed["score"]==event["score"]+10
    assert analysed["evidence"][0]["page"]==1
    assert "Rs. 123 crore" in analysed["evidence"][0]["excerpt"]


def test_large_pdf_skipped_without_false_success_or_repeated_retries(tmp_path):
    path=tmp_path/"overlimit.sqlite3"
    database.init_db(path)
    event=filing("SUNPHARMA","sunpharma-large-doc")
    database.save_announcements([event],path)

    session=PDFSession(PDFResponse(b"%PDF-",headers={
        "Content-Type":"application/pdf", "Content-Length":str(MAX_PDF_BYTES+1),
    }))
    result=enrich_filings(path=path,session=session,max_files=2)
    assert result["ok"]==0
    assert result["failed"]==0
    assert result["skipped"]==1
    assert result["results"][0]["status"]=="skipped_too_large"
    assert session.calls==1
    stored=database.get_filing(event["filing_id"],path)
    assert stored["pdf_analysis_status"]=="skipped_too_large"
    assert stored["score"]==event["score"]
    assert stored["pdf_error"].startswith("DocumentSkipped: PDF_LIMIT_EXCEEDED:")
    assert database.pdf_cache_stats(path)["analyses"]["skipped_too_large"]==1
    assert candidates(path,max_files=2)==[]
    assert candidates(path,max_files=2,retry_failed=True)==[]
    assert len(candidates(path,max_files=2,force=True))==1


def test_version_invalidates_v1_and_reuses_existing_cache(tmp_path):
    from app.pdf_priority import save_analysis
    from contextlib import closing
    import json, zlib
    path=tmp_path/"version.sqlite3"
    database.init_db(path)
    event=filing()
    database.save_announcements([event],path)
    # Simulate previously cached text from a genuine NSE attachment; no re-download
    pages=document("Net Profit/Loss after tax Rs. 350 crore", "No quarterly loss was reported.")["pages"]
    with closing(database.connect(path)) as conn:
        with conn:
            conn.execute("""INSERT INTO pdf_text_cache
              (source_url,sha256,page_count,char_count,pages_zlib,extracted_at_utc)
              VALUES (?,?,?,?,?,?)""",
              (event["source_url"],"existing-digest",1,125,
               zlib.compress(json.dumps(pages).encode()),"2026-11-01T00:00:00+00:00"))
    # Previous version got a false bonus; new API must not serve its stale result.
    fake=score_document(event,document("The company reported a net loss of Rs. 50 crore."))
    save_analysis(event,fake,path)
    with closing(database.connect(path)) as conn:
        with conn:
            conn.execute("UPDATE filing_pdf_analysis SET analysis_version='pdf_rules_v1',score=? WHERE filing_id=?",
                         (event["score"]+10,event["filing_id"]))
    assert database.get_filing(event["filing_id"],path)["score"]==event["score"]
    assert len(candidates(path,max_files=2))==1
    result=enrich_filings(path=path,max_files=2)
    assert result["ok"]==1
    assert result["results"][0]["cache_hit"] is True
    after=database.get_filing(event["filing_id"],path)
    assert after["pdf_analysis_status"]=="ok"
    assert after["score"]==event["score"]
    with closing(database.connect(path)) as conn:
        current=conn.execute("SELECT analysis_version FROM filing_pdf_analysis").fetchone()[0]
    assert current==VERSION
