"""Selective, citeable PDF examination of genuine NSE attachments.

No generative summaries and no price-impact predictions. Every document-derived
score change must have a literal excerpt and page number from the source PDF.
"""
import argparse
import hashlib
import json
import re
import zlib
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import fitz  # PyMuPDF
import requests

from app import database
from app.classifier import evaluate, WHY
from app.nse_filings import valid_attachment

VERSION = "pdf_rules_v2_context"
MIN_STAGE1_SCORE = 40
MAX_PDF_BYTES = 12 * 1024 * 1024
MAX_PAGES = 150
MAX_TEXT_CHARS = 700_000
RETRY_AFTER_HOURS = 6
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Referer": "https://www.nseindia.com/",
}


class DocumentFailure(RuntimeError):
    """An explicit, source-related error; never convert it to a fake PDF result."""


class DocumentSkipped(DocumentFailure):
    """Permanent resource limit. Keep metadata priority, and do not auto-retry."""

    CODE = "PDF_LIMIT_EXCEEDED: "

    def __init__(self, reason: str):
        super().__init__(self.CODE + reason)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def trusted_pdf_url(url: str | None) -> str:
    normalized = valid_attachment(url)
    if normalized is None:
        raise DocumentFailure("Missing or untrusted NSE attachment URL")
    parsed = urlparse(normalized)
    try:
        port = parsed.port
    except ValueError as exc:
        raise DocumentFailure("Invalid HTTPS URL port") from exc
    if port not in (None, 443):
        raise DocumentFailure("Nonstandard HTTPS port not allowed")
    return normalized


def fetch_pdf(url: str, session=None) -> bytes:
    """Limit bytes, network time, domains, and redirects (SSRF protection)."""
    current = trusted_pdf_url(url)
    owns_session = session is None
    client = requests.Session() if owns_session else session
    try:
        if owns_session:
            client.headers.update(HEADERS)
        for _ in range(4):
            response = client.get(current, timeout=(7, 25), stream=True, allow_redirects=False)
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    from urllib.parse import urljoin
                    redirect = response.headers.get("Location")
                    if not redirect:
                        raise DocumentFailure("PDF redirect without Location")
                    current = trusted_pdf_url(urljoin(current, redirect))
                    continue
                if response.status_code in (401, 403, 429):
                    raise DocumentFailure(f"NSE PDF access denied (HTTP {response.status_code})")
                try:
                    response.raise_for_status()
                except requests.RequestException as exc:
                    raise DocumentFailure(f"NSE PDF HTTP error: {exc}") from exc
                declared = response.headers.get("Content-Length", "")
                if declared.isdecimal() and int(declared) > MAX_PDF_BYTES:
                    raise DocumentSkipped(f"Attachment exceeds maximum {MAX_PDF_BYTES // (1024 * 1024)} MiB download limit; no full-text review")
                pieces = []
                size = 0
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_PDF_BYTES:
                        raise DocumentSkipped(f"Attachment exceeds maximum {MAX_PDF_BYTES // (1024 * 1024)} MiB download limit; no full-text review")
                    pieces.append(chunk)
                data = b"".join(pieces)
                if not data.startswith(b"%PDF-"):
                    raise DocumentFailure("Response is not a PDF (could be HTML/anti-bot content)")
                return data
            finally:
                response.close()
        raise DocumentFailure("Too many redirects while fetching NSE PDF")
    except requests.RequestException as exc:
        raise DocumentFailure(f"PDF network error: {type(exc).__name__}: {exc}") from exc
    finally:
        if owns_session:
            client.close()


def extract_pages(raw_pdf: bytes) -> list[dict]:
    try:
        doc = fitz.open(stream=raw_pdf, filetype="pdf")
        with doc:
            if doc.needs_pass:
                raise DocumentFailure("Encrypted PDF requires password")
            if len(doc) > MAX_PAGES:
                raise DocumentSkipped(f"Attachment has {len(doc)} pages (limit {MAX_PAGES}); no partial review")
            pages = []
            chars = 0
            for index, page in enumerate(doc):
                text = page.get_text(sort=True)
                text = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
                chars += len(text)
                if chars > MAX_TEXT_CHARS:
                    raise DocumentSkipped(f"Extracted text exceeds {MAX_TEXT_CHARS:,} characters; no partial review")
                pages.append({"page": index + 1, "text": text})
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        raise DocumentFailure(f"Invalid or corrupt PDF: {exc}") from exc
    if sum(len(p["text"]) for p in pages) < 100:
        raise DocumentFailure("PDF has insufficient selectable text (possibly scanned); OCR not enabled")
    return pages


def cached_pages(url: str, path: Path | None = None):
    with closing(database.connect(path)) as conn:
        row = conn.execute("SELECT * FROM pdf_text_cache WHERE source_url=?", (url,)).fetchone()
    if row is None:
        return None
    try:
        pages = json.loads(zlib.decompress(row["pages_zlib"]).decode("utf-8"))
    except (zlib.error, UnicodeError, json.JSONDecodeError) as exc:
        raise DocumentFailure(f"Corrupt cached extraction; use --refresh-documents: {exc}") from exc
    return {"pages": pages, "sha256": row["sha256"], "page_count": row["page_count"],
            "char_count": row["char_count"], "cache_hit": True}


def read_document(url: str, path: Path | None = None, session=None,
                  refresh: bool = False) -> dict:
    url = trusted_pdf_url(url)
    if not refresh:
        existing = cached_pages(url, path)
        if existing is not None:
            return existing
    data = fetch_pdf(url, session)
    digest = hashlib.sha256(data).hexdigest()
    pages = extract_pages(data)
    char_count = sum(len(x["text"]) for x in pages)
    packed = zlib.compress(json.dumps(pages, ensure_ascii=False).encode("utf-8"), level=6)
    with closing(database.connect(path)) as conn:
        with conn:
            conn.execute("""
                INSERT INTO pdf_text_cache
                  (source_url,sha256,page_count,char_count,pages_zlib,extracted_at_utc)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(source_url) DO UPDATE SET
                  sha256=excluded.sha256,page_count=excluded.page_count,
                  char_count=excluded.char_count,pages_zlib=excluded.pages_zlib,
                  extracted_at_utc=excluded.extracted_at_utc
            """, (url,digest,len(pages),char_count,packed,now_utc()))
    return {"pages":pages, "sha256":digest,"page_count":len(pages),
            "char_count":char_count,"cache_hit":False}


# Category-sensitive, cautiously worded signals. Match within a small sentence/
# line window, never by searching for disjoint words on different pages.
# Every rule can fire at most once per announcement.
DOCUMENT_RULES = [
    ("management_change", r"\b(?:cfo|chief financial officer|ceo|chief executive officer|managing director|\bmd\b)\b[^.\n;:]{0,110}\b(?:resign(?:ed|ation|s)?|step(?:ped)? down|ceased to be)\b|\b(?:resign(?:ed|ation|s)?|step(?:ped)? down)\b[^.\n;:]{0,110}\b(?:cfo|chief financial officer|ceo|chief executive officer|managing director)\b", 18, "Executive departure described in filing"),
    ("credit_rating", r"\b(?:rating|rated facility|long.term rating)\b.{0,130}\b(?:downgrade|downgraded|revised downward|withdrawn)\b|\bdowngraded\b.{0,100}\brating\b", 22, "Rating downgrade or withdrawal stated"),
    ("credit_rating", r"\b(?:rating|rated facility)\b.{0,120}\b(?:reaffirmed|reaffirmation)\b", -12, "Rating reaffirmed rather than changed"),
    ("litigation", r"\b(?:penalty of|imposed a penalty|monetary penalty|show cause notice|insolvency proceedings|adjudication order)\b", 13, "Regulatory/legal exposure described"),
    ("M&A", r"\b(?:acquisition of|acquire|purchase of)\b.{0,130}\b(?:100\s*%|majority stake|controlling stake|entire shareholding)\b", 8, "Controlling acquisition indicated"),
    ("M&A", r"\b(?:transaction value|purchase consideration|aggregate consideration|acquisition consideration)\b.{0,90}(?:₹|rs\.?|inr)\s*[\d,.]+\s*(?:crores?|lakhs?|million|billion)\b", 9, "Transaction consideration stated (size needs company context)"),
    ("results", r"\b(?:revenue|net profit|pat|ebitda)\b.{0,95}\b(?:declined|decreased|fell|dropped)\b.{0,45}\b(?:[2-9]\d|100)\s*%", 13, "Double-digit deterioration stated in results"),
    ("capex", r"\b(?:capital expenditure|capex|plant investment|capacity expansion)\b.{0,110}(?:₹|rs\.?|inr)\s*[\d,.]+\s*(?:crores?|lakhs?|million|billion)\b", 7, "Quantified capital investment described"),
    ("fund_raise", r"\b(?:qualified institutional placement|rights issue|preferential issue|fund raise)\b.{0,110}(?:₹|rs\.?|inr)\s*[\d,.]+\s*(?:crores?|lakhs?|million|billion)\b", 8, "Quantified capital raise described"),
    ("pledging", r"\b(?:invocation of pledge|pledge has been invoked|pledged shares invoked)\b", 16, "Promoter pledge invocation confirmed"),
]


def _windows(page_text: str):
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        # Short adjoining segments support typical PDF wrapped sentences.
        if len(line) > 350:
            yield line[:350]
        else:
            yield " ".join(lines[i:i+2])[:350]


# Financial statement headings often use "Net Profit/Loss after tax" even
# when PAT is positive. A PDF table heading is NEVER sufficient to infer a loss.
# A loss signal needs an explicit, numeric statement in ordinary prose.
LOSS_STATEMENT = re.compile(
    r"\b(?:the\s+)?(?:company|group|business|entity|we|it)\s+"
    r"(?:has\s+)?(?:reported|incurred|posted|recorded|registered)\s+"
    r"(?:a\s+)?(?:consolidated\s+|standalone\s+)?"
    r"(?:net\s+loss|loss\s+after\s+tax)\s+"
    r"(?:of|amounting\s+to)\s+(?:₹|rs\.?|inr)\s*"
    r"(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?)\s*"
    r"(?:crores?|lakhs?|lacs?|million|billion)\b",
    re.I,
)
CURRENT_PERIOD_WORDING = re.compile(
    r"\b(?:(?:this|current)\s+(?:quarter|period|financial\s+year|year)|"
    r"(?:quarter|period|year)\s+under\s+review)\b", re.I,
)
LOSS_NOISE = re.compile(
    r"\b(?:net\s+profit\s*[/|]\s*\(?loss\)?|"
    r"net\s+profit\s+or\s+loss|profit\s*\(loss\)|"
    r"previous\s+(?:year|quarter|period)|prior\s+(?:year|quarter|period)|"
    r"corresponding\s+(?:quarter|period)|year\s+ago|"
    r"not\s+reported|did\s+not\s+report|has\s+not\s+reported)\b",
    re.I,
)


def confirmed_loss_signal(pages: list[dict]) -> dict | None:
    """Only a quantified, affirmative, current-period narrative loss statement.

    This intentionally misses table-only losses and some real statements rather
    than inventing a loss from a financial-statement heading or a prior-year figure.
    """
    for page in pages:
        for line in page["text"].splitlines():
            line = " ".join(line.split())
            if len(line) > 500 or not line:
                continue
            for match in LOSS_STATEMENT.finditer(line):
                amount = float(match.group("amount").replace(",", ""))
                if amount <= 0:
                    continue
                # Ignore headings and narrative explicitly about a prior period.
                neighbourhood = line[max(0, match.start()-90):min(len(line), match.end()+80)]
                if LOSS_NOISE.search(neighbourhood):
                    continue
                # A bare quantified loss may describe a historical comparative period.
                # Without explicit current-period wording, do not add points.
                if not CURRENT_PERIOD_WORDING.search(line):
                    continue
                # Prevent "no ... company reported" negations adjacent to assertion.
                preceding = line[max(0,match.start()-45):match.start()].lower()
                if re.search(r"\b(?:no|not|never|without|neither)\b", preceding):
                    continue
                return {"page": page["page"], "excerpt": line[:300],
                        "signal": "Explicit current-period net loss reported with an amount",
                        "points": 10}
    return None


def document_signals(category: str, pages: list[dict]) -> list[dict]:
    signals = []
    for applicable, regex, points, label in DOCUMENT_RULES:
        if applicable != category:
            continue
        pattern = re.compile(regex, re.I)
        found = None
        for page in pages:
            for text in _windows(page["text"]):
                match = pattern.search(text)
                if match:
                    lo = max(0, match.start()-60)
                    hi = min(len(text), match.end()+100)
                    found = {"page":page["page"], "excerpt":text[lo:hi].strip(),
                             "signal":label, "points":points}
                    break
            if found:
                break
        if found:
            signals.append(found)
    if category == "results":
        confirmed_loss = confirmed_loss_signal(pages)
        if confirmed_loss:
            signals.append(confirmed_loss)
    return signals


def score_document(filing: dict, document: dict) -> dict:
    metadata = evaluate(filing["subject"], filing["details"])
    stage1 = metadata["score"]
    signals = document_signals(metadata["category"], document["pages"])
    raw_adjustment = sum(x["points"] for x in signals)
    # Limit document adjustments: rules are indicators, not estimated stock impact.
    adjustment = max(-20, min(30, raw_adjustment))
    score = max(0, min(100, stage1 + adjustment))
    applied = score - stage1
    components = metadata["score_components"] + [
        {"source":"PDF", "reason":x["signal"], "points":x["points"],
         "page":x["page"], "excerpt":x["excerpt"]} for x in signals
    ]
    if raw_adjustment != applied:
        components.append({"source":"scoring", "reason":"PDF delta limited and score bounded to 0–100",
                           "points": applied-raw_adjustment})
    priority = "high" if score >= 70 else ("review" if score >= 40 else "routine")
    why = WHY[metadata["category"]]
    if signals:
        why += " Document signals: " + "; ".join(x["signal"] for x in signals) + "."
    else:
        why += " No additional high-confidence materiality signal was found by PDF rules."
    what = metadata["what_happened"]
    if signals:
        selected = signals[0]
        what += f" [PDF p.{selected['page']}: {selected['excerpt'][:170]}]"
    return {
        "status":"ok", "source_url":filing["source_url"], "sha256":document["sha256"],
        "stage1_score": stage1, "score":score, "priority":priority,
        "breakdown":components, "evidence":signals,
        "what_happened":what[:650], "why_it_matters":why,
        "reason":(f"Metadata {stage1} + PDF adjustment {applied:+d} = {score}. "
                  f"Thresholds: High >=70; Review >=40; Routine <40."),
        "evidence_scope":(f"NSE exchange description plus inspected {document['page_count']}-page PDF; "
                          "rules-based evidence, not independent valuation analysis"),
        "error":None,
    }


def save_analysis(filing: dict, result: dict, path: Path | None = None):
    with closing(database.connect(path)) as conn:
        with conn:
            conn.execute("""
                INSERT INTO filing_pdf_analysis
                 (filing_id,analysis_version,source_url,stage1_score,subject_snapshot,
                  details_snapshot,status,sha256,score,priority,breakdown_json,evidence_json,what_happened,
                  why_it_matters,priority_reason,evidence_scope,error,analysed_at_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(filing_id) DO UPDATE SET
                  analysis_version=excluded.analysis_version,source_url=excluded.source_url,
                  stage1_score=excluded.stage1_score,
                  subject_snapshot=excluded.subject_snapshot,
                  details_snapshot=excluded.details_snapshot,status=excluded.status,
                  sha256=excluded.sha256,score=excluded.score,priority=excluded.priority,
                  breakdown_json=excluded.breakdown_json,evidence_json=excluded.evidence_json,
                  what_happened=excluded.what_happened,why_it_matters=excluded.why_it_matters,
                  priority_reason=excluded.priority_reason,evidence_scope=excluded.evidence_scope,
                  error=excluded.error,analysed_at_utc=excluded.analysed_at_utc
            """, (
                filing["filing_id"],VERSION,filing["source_url"],result["stage1_score"],
                filing["subject"],filing["details"],result["status"],result.get("sha256"),result.get("score"),result.get("priority"),
                json.dumps(result.get("breakdown",[]),ensure_ascii=False),
                json.dumps(result.get("evidence",[]),ensure_ascii=False),
                result.get("what_happened"),result.get("why_it_matters"),
                result.get("reason"),result.get("evidence_scope"),result.get("error"),now_utc(),
            ))


def candidates(path: Path | None = None, symbols: list[str] | None = None,
               max_files: int = 10, retry_failed: bool = False,
               force: bool = False) -> list[dict]:
    if max_files < 1 or max_files > 100:
        raise ValueError("max_files must be between 1 and 100")
    with closing(database.connect(path)) as conn:
        filings = [dict(x) for x in conn.execute("""
            SELECT a.*,p.status AS pdf_status,p.stage1_score AS analysed_base,
                   p.source_url AS analysed_url,p.analysis_version AS analysed_version,
                   p.subject_snapshot AS analysed_subject,p.details_snapshot AS analysed_details,
                   p.analysed_at_utc AS previous_attempt,p.error AS previous_error
            FROM announcements a
            LEFT JOIN filing_pdf_analysis p ON p.filing_id=a.filing_id
            WHERE a.score>=? AND a.source_url IS NOT NULL AND a.exchange='NSE'
            ORDER BY a.score DESC, a.published_at_utc DESC
        """,(MIN_STAGE1_SCORE,))]
    if symbols:
        allowed={s.strip().upper() for s in symbols}
        filings=[f for f in filings if f["symbol"] in allowed]
    selected=[]
    limit_dt = datetime.now(timezone.utc)-timedelta(hours=RETRY_AFTER_HOURS)
    for f in filings:
        try:
            trusted_pdf_url(f["source_url"])
        except DocumentFailure:
            continue
        same = (f["analysed_base"]==f["score"] and f["analysed_url"]==f["source_url"]
                and f["analysed_version"]==VERSION and f["analysed_subject"]==f["subject"]
                and f["analysed_details"]==f["details"])
        if same and f["pdf_status"]=="ok" and not force:
            continue
        if (same and f["pdf_status"] == "error" and
                DocumentSkipped.CODE in (f["previous_error"] or "")
                and not force):
            # A known resource limit will not disappear after the retry backoff.
            continue
        if same and f["pdf_status"]=="error" and not (retry_failed or force):
            attempt=datetime.fromisoformat(f["previous_attempt"])
            if attempt.tzinfo is None:
                attempt=attempt.replace(tzinfo=timezone.utc)
            if attempt>limit_dt:
                continue
        selected.append(f)
        if len(selected)>=max_files:
            break
    return selected


def enrich_filings(path: Path | None = None, symbols: list[str] | None = None,
                   max_files: int = 10, retry_failed: bool = False,
                   force: bool = False, refresh_documents: bool = False,
                   session=None) -> dict:
    database.init_db(path)
    chosen=candidates(path,symbols,max_files,retry_failed,force)
    results=[]
    for filing in chosen:
        fid=filing["filing_id"]
        try:
            doc=read_document(filing["source_url"],path,session,refresh_documents)
            computed=score_document(filing,doc)
            save_analysis(filing,computed,path)
            results.append({"filing_id":fid,"symbol":filing["symbol"],"status":"ok",
                           "priority":computed["priority"],"score":computed["score"],
                           "metadata_score":filing["score"],"pdf_adjustment":computed["score"]-filing["score"],
                           "cache_hit":doc["cache_hit"],"pages":doc["page_count"],
                           "document_sha256":doc["sha256"],"source_url":filing["source_url"],
                           "evidence":computed["evidence"]})
        except (DocumentFailure, ValueError, RuntimeError) as exc:
            # Preserve stage-one classification without misrepresenting a failed PDF read.
            message=f"{type(exc).__name__}: {exc}"
            save_analysis(filing,{"stage1_score":filing["score"],"status":"error","error":message},path)
            skipped = isinstance(exc, DocumentSkipped)
            results.append({"filing_id":fid,"symbol":filing["symbol"],
                            "status":"skipped_too_large" if skipped else "error",
                            "metadata_score":filing["score"],"source_url":filing["source_url"],
                            "error":message})
    return {"selected":len(chosen),"ok":sum(x["status"]=="ok" for x in results),
            "skipped":sum(x["status"]=="skipped_too_large" for x in results),
            "failed":sum(x["status"]=="error" for x in results),"results":results,
            "note":"Only >=40 metadata-score filings with trusted original NSE attachments were considered."}


def main():
    parser=argparse.ArgumentParser(description="Selectively enrich stored genuine NSE filings with PDF evidence")
    parser.add_argument("--symbols",help="Comma-separated NSE portfolio symbols")
    parser.add_argument("--max-files",type=int,default=10)
    parser.add_argument("--retry-failed",action="store_true")
    parser.add_argument("--force",action="store_true",help="Recompute stored analyses using cached content")
    parser.add_argument("--refresh-documents",action="store_true",help="Download PDFs again even if text cached")
    args=parser.parse_args()
    symbols=args.symbols.split(",") if args.symbols else None
    result=enrich_filings(symbols=symbols,max_files=args.max_files,
                          retry_failed=args.retry_failed,force=args.force,
                          refresh_documents=args.refresh_documents)
    # Refresh derived filing alerts with the effective (PDF-informed) priority.
    from app.alerts import rebuild_alerts
    result["alerts_rebuilt"]=rebuild_alerts()
    print(json.dumps(result,indent=2,ensure_ascii=False))
    if result["failed"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
