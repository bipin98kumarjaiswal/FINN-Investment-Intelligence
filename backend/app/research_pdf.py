"""Fetch / parse only genuine primary-source PDFs, with bounded resource use."""
from hashlib import sha256
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse
import requests
import fitz
from app import research_store

MAX_BYTES = 28 * 1024 * 1024
MAX_PAGES = 450

class DocumentError(ValueError):
    pass


def validate_url(url: str):
    try:
        parsed=urlparse(url)
        port=parsed.port
    except ValueError as exc:
        raise DocumentError('Malformed document URL or port') from exc
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
        or port not in (None,443) or len(url)>1600):
        raise DocumentError('Only direct HTTPS public document URLs are supported.')
    hostname=parsed.hostname.lower()
    if not re.fullmatch(r'[a-z0-9.-]+',hostname) or hostname in ('localhost','localhost.localdomain'):
        raise DocumentError('Invalid or private document host')
    if hostname.endswith(('.local','.internal','.localhost')):
        raise DocumentError('Private document host not allowed')
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise DocumentError('IP-address hosts are not allowed')
    # Server-side URL fetching is restricted to primary-source domains, never arbitrary user hosts.
    # NSE/BSE filings and published corporate investor-relations websites are acceptable.
    # DNS checks also prevent simple private-address rebinding. Redirects are rejected.
    extra_hosts={x.strip().lower() for x in os.getenv('FINN_TRUSTED_IR_HOSTS','').split(',') if x.strip()}
    if not (hostname in {'nsearchives.nseindia.com','www.nseindia.com','nseindia.com',
                          'www.bseindia.com','bseindia.com'} or
            hostname.endswith('.infosys.com') or hostname=='infosys.com' or
            hostname in extra_hosts):
        # Other IR hosts can be added by a developer after reviewing domain ownership.
        raise DocumentError('Host not on primary-source allowlist. Verify ownership and set FINN_TRUSTED_IR_HOSTS on the server.')
    try:
        addrs=socket.getaddrinfo(hostname,None,type=socket.SOCK_STREAM)
        if not addrs or any(not ipaddress.ip_address(item[4][0]).is_global for item in addrs):
            raise DocumentError('Document host does not resolve to public IP addresses')
    except socket.gaierror as exc:
        raise DocumentError(f'Cannot resolve document host: {exc}') from exc
    return url


def fetch_pdf(url: str, get=None):
    validate_url(url)
    get=get or requests.get
    try:
        r=get(url,stream=True,timeout=(8,35),allow_redirects=False,
              headers={'User-Agent':'Mozilla/5.0 FINN-source-research/0.1','Accept':'application/pdf,*/*'})
        if 300 <= r.status_code < 400:
            raise DocumentError('PDF URL redirected. Use the final verified primary-source URL.')
        r.raise_for_status()
        length=int(r.headers.get('Content-Length') or 0)
        if length>MAX_BYTES:
            raise DocumentError(f'PDF exceeds {MAX_BYTES//(1024*1024)} MiB processing limit')
        result=bytearray()
        for block in r.iter_content(128*1024):
            result.extend(block)
            if len(result)>MAX_BYTES:
                raise DocumentError('PDF exceeds maximum size while downloading')
        if not result.startswith(b'%PDF-'):
            raise DocumentError('Source returned a non-PDF document')
        return bytes(result)
    except requests.RequestException as exc:
        raise DocumentError(f'Primary document download failed: {exc}') from exc
    finally:
        if 'r' in locals(): r.close()


def split_page(text: str):
    text=re.sub(r'[ \t]+',' ',text).strip()
    text=re.sub(r'\n{3,}','\n\n',text)
    result=[]
    pos=0
    while pos<len(text):
        end=min(len(text),pos+1400)
        if end<len(text):
            cut=text.rfind(' ',pos+950,end)
            if cut>pos: end=cut
        piece=text[pos:end].strip()
        if len(piece)>40:
            result.append(piece)
        if end>=len(text): break
        pos=max(pos+1,end-170)
    return result


def extract_pdf(raw: bytes):
    # The new extractor keeps paragraphs and columns separate and drops unreliable table fragments.
    from app.research_quality import extract_clean_pdf
    return extract_clean_pdf(raw, error_type=DocumentError, max_pages=MAX_PAGES)

def ingest(symbol: str, url: str, title: str, kind: str, published_on=None,
           period=None, path=None, download=None):
    symbol=symbol.strip().upper()
    if not research_store.known_company(symbol,path):
        raise DocumentError('Unknown NSE symbol; refresh NSE company catalog first')
    if kind not in {'annual_report','transcript','results','presentation'}:
        raise DocumentError('Unsupported document kind')
    if not title.strip(): raise DocumentError('Document title required')
    cached=research_store.get_document(symbol,url,path)
    if cached: return dict(cached,cached=True)
    data=(download or fetch_pdf)(url)
    page_count,chunks=extract_pdf(data)
    record=research_store.store_document(symbol,title.strip()[:180],kind,url,published_on,
                                         period,sha256(data).hexdigest(),page_count,chunks,path)
    return dict(record,cached=False)
