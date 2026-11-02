"""Restore a SHA-256-pinned SQLite demo snapshot from private GitHub Contents API.

Deployment-only code: never writes to GitHub and never modifies Push/Pull/Gemini.
All SQLite writes by the existing API use an ephemeral working copy.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests

MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024  # GitHub Contents API max file size
MIN_PRICED_COMPANIES = 16
MIN_PRICE_ROWS = 100
SQLITE_MAGIC = b'SQLite format 3\0'
API_HOST = 'api.github.com'
REDIRECT_HOSTS = {'raw.githubusercontent.com', 'objects.githubusercontent.com'}
API_VERSION = '2022-11-28'


class SnapshotError(RuntimeError):
    """Safe error text: no authorization tokens or signed redirect URLs."""


def audit_database(path: str | Path) -> dict:
    """Read-only integrity + live FINN source-data validation."""
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size < 4096:
        raise SnapshotError('SQLite snapshot missing or implausibly small')
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=20)) as conn:
            conn.execute('PRAGMA query_only=ON')
            integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
            if integrity != 'ok':
                raise SnapshotError('SQLite integrity check failed')
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            required={'companies','daily_prices','announcements','research_documents','research_chunks'}
            if required-tables:
                raise SnapshotError('Snapshot missing required FINN tables')
            prices=conn.execute('SELECT COUNT(*) FROM daily_prices').fetchone()[0]
            companies=conn.execute('SELECT COUNT(DISTINCT symbol) FROM daily_prices').fetchone()[0]
            filings=conn.execute('SELECT COUNT(*) FROM announcements').fetchone()[0]
            documents=conn.execute('SELECT COUNT(*) FROM research_documents').fetchone()[0]
            passages=conn.execute('SELECT COUNT(*) FROM research_chunks').fetchone()[0]
            infy_docs=conn.execute("SELECT COUNT(*) FROM research_documents WHERE symbol='INFY'").fetchone()[0]
            infy_passages=conn.execute("SELECT COUNT(*) FROM research_chunks WHERE symbol='INFY'").fetchone()[0]
            # Prove FTS5 can actually execute a keyword query, not merely count rows.
            conn.execute("SELECT rowid FROM research_chunks WHERE research_chunks MATCH 'risk' LIMIT 1").fetchall()
            if companies < MIN_PRICED_COMPANIES or prices < MIN_PRICE_ROWS:
                raise SnapshotError('Snapshot missing 16-company market-price history')
            if filings < 1:
                raise SnapshotError('Snapshot contains no NSE announcements')
            if not all((documents,passages,infy_docs,infy_passages)):
                raise SnapshotError('Snapshot missing indexed Infosys documents or source passages')
            return {'price_rows':prices,'priced_companies':companies,'announcements':filings,
                    'research_documents':documents,'research_passages':passages,
                    'infosys_documents':infy_docs,'infosys_passages':infy_passages}
    except (sqlite3.Error, OSError) as exc:
        raise SnapshotError(f'SQLite validation failed ({type(exc).__name__})') from exc


def sha256_file(path: str | Path) -> str:
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):
            h.update(part)
    return h.hexdigest()


def get_settings(env: dict) -> dict:
    names=('FINN_GITHUB_OWNER','FINN_GITHUB_REPO','FINN_GITHUB_PATH',
           'FINN_GITHUB_TOKEN','FINN_SNAPSHOT_SHA256')
    missing=[name for name in names if not env.get(name)]
    if missing:
        raise SnapshotError('Missing GitHub snapshot config: '+', '.join(missing))
    owner=env['FINN_GITHUB_OWNER'].strip()
    repo=env['FINN_GITHUB_REPO'].strip()
    path=env['FINN_GITHUB_PATH'].strip().strip('/')
    ref=env.get('FINN_GITHUB_REF','main').strip()
    digest=env['FINN_SNAPSHOT_SHA256'].strip().lower()
    token=env['FINN_GITHUB_TOKEN'].strip()
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37})',owner):
        raise SnapshotError('Invalid GitHub owner')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',repo) or repo.startswith('.') or repo.endswith('.git'):
        raise SnapshotError('Invalid GitHub repository name')
    segments=path.split('/')
    if not segments or len(path)>600 or any(not re.fullmatch(r'[A-Za-z0-9_. -]{1,180}',part) or part in ('.','..') for part in segments):
        raise SnapshotError('Invalid GitHub snapshot file path')
    if not ref or len(ref)>180 or not re.fullmatch(r'[A-Za-z0-9_./-]+',ref) or '..' in ref:
        raise SnapshotError('Invalid GitHub ref')
    if not re.fullmatch(r'[0-9a-f]{64}',digest):
        raise SnapshotError('FINN_SNAPSHOT_SHA256 must contain exactly 64 hex characters')
    if not token or len(token)>1024 or any(x in token for x in ('\r','\n')):
        raise SnapshotError('Invalid GitHub token format')
    return {'owner':owner,'repo':repo,'path':path,'ref':ref,'token':token,'sha256':digest}


def contents_url(settings: dict) -> str:
    owner=quote(settings['owner'],safe='')
    repo=quote(settings['repo'],safe='')
    path='/'.join(quote(segment,safe='') for segment in settings['path'].split('/'))
    return f'https://{API_HOST}/repos/{owner}/{repo}/contents/{path}'


def _safe_redirect(base: str, location: str) -> str:
    if not location:
        raise SnapshotError('GitHub API redirect missing location')
    dest=urljoin(base,location)
    parsed=urlparse(dest)
    try:
        port=parsed.port
    except ValueError as exc:
        raise SnapshotError('Invalid GitHub download redirect') from exc
    if (parsed.scheme!='https' or parsed.username or parsed.password or
        port not in (None,443) or parsed.hostname not in REDIRECT_HOSTS):
        raise SnapshotError('GitHub download redirected outside approved hosts')
    return dest


def _http_error(status: int):
    if status==401: return 'GitHub token rejected (401)'
    if status==403: return 'GitHub access denied or rate-limited (403)'
    if status==404: return 'Private GitHub repository, file, or ref not found (404)'
    if status==429: return 'GitHub API rate limit exceeded (429)'
    return f'GitHub download returned HTTP {status}'


def download_snapshot(output, settings, request_get=None) -> str:
    """Contents API raw GET, bounded streaming and restricted unauthenticated redirects.

    GitHub documents raw media type as necessary for files above 1MB.
    This function accepts a get callback for offline tests; production uses requests.get.
    """
    getter=request_get or requests.get
    url=contents_url(settings)
    headers={
        'Accept':'application/vnd.github.raw+json',
        'Authorization':f'Bearer {settings["token"]}',
        'X-GitHub-Api-Version':API_VERSION,
        'User-Agent':'FINN-private-snapshot-demo/1.0',
    }
    params={'ref':settings['ref']}
    redirects=0
    while True:
        try:
            response=getter(url,headers=headers,params=params,stream=True,
                            allow_redirects=False,timeout=(10,45))
        except requests.RequestException as exc:
            raise SnapshotError(f'GitHub request failed ({type(exc).__name__})') from exc
        try:
            if response.status_code in (301,302,303,307,308):
                if redirects>=3:
                    raise SnapshotError('Too many GitHub download redirects')
                url=_safe_redirect(url,response.headers.get('Location',''))
                # Never forward the private GitHub token to a redirect host.
                headers={'Accept':'application/octet-stream', 'User-Agent':'FINN-private-snapshot-demo/1.0'}
                params=None
                redirects+=1
                continue
            if response.status_code!=200:
                raise SnapshotError(_http_error(response.status_code))
            announced=response.headers.get('Content-Length')
            if announced is not None:
                try:
                    if int(announced)>MAX_SNAPSHOT_BYTES:
                        raise SnapshotError('GitHub snapshot exceeds 100 MiB limit')
                except ValueError as exc:
                    raise SnapshotError('Invalid GitHub download content length') from exc
            # A Contents API JSON metadata response for >1 MB is not the binary file.
            # We must fail loudly instead of saving JSON as SQLite.
            digest=hashlib.sha256()
            size=0
            first=bytearray()
            for block in response.iter_content(chunk_size=256*1024):
                if not block: continue
                if len(first)<len(SQLITE_MAGIC):
                    missing=len(SQLITE_MAGIC)-len(first)
                    first.extend(block[:missing])
                    if len(first)==len(SQLITE_MAGIC) and bytes(first)!=SQLITE_MAGIC:
                        raise SnapshotError('GitHub did not return raw SQLite bytes; check Contents API raw media type')
                size+=len(block)
                if size>MAX_SNAPSHOT_BYTES:
                    raise SnapshotError('GitHub snapshot exceeds 100 MiB streaming limit')
                digest.update(block)
                output.write(block)
            if size<4096:
                raise SnapshotError('GitHub snapshot file is unexpectedly small')
            if bytes(first)!=SQLITE_MAGIC:
                raise SnapshotError('GitHub snapshot is not a valid raw SQLite file')
            return digest.hexdigest()
        except requests.RequestException as exc:
            raise SnapshotError(f'GitHub download failed ({type(exc).__name__})') from exc
        finally:
            response.close()


def restore_snapshot(runtime_path: str | Path | None=None, env=None, request_get=None):
    """Re-download each process startup, verify digest, audit DB, atomically swap.

    On any failure the API is not started and the previous runtime file is not
    replaced. Uses only ephemeral /tmp data in Render.
    """
    env=os.environ if env is None else env
    settings=get_settings(env)
    destination=Path(runtime_path or env.get('FINN_DB_PATH') or '/tmp/finn-demo/finn.sqlite3').resolve()
    destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    temp_path=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.finn-github-',suffix='.sqlite3',
                                         dir=destination.parent,delete=False) as target:
            temp_path=Path(target.name)
            os.chmod(temp_path,0o600)
            downloaded_sha=download_snapshot(target,settings,request_get=request_get)
            target.flush()
            os.fsync(target.fileno())
        if downloaded_sha!=settings['sha256']:
            raise SnapshotError('Downloaded GitHub SQLite SHA-256 mismatch: refusing startup')
        stats=audit_database(temp_path)
        # SQLite sidecar files are not included in the snapshot. A fresh Render
        # instance has no old WAL; stop local SQLite writers before manual restore.
        os.replace(temp_path,destination)
        temp_path=None
        print('[FINN] Verified private GitHub snapshot SHA-256 '
              f'{downloaded_sha[:16]}... counts={stats}',flush=True)
        return {'sha256':downloaded_sha,'runtime_path':str(destination),'stats':stats}
    except SnapshotError:
        raise
    except Exception as exc:
        # Hide credentials and private download URLs in exception chains and logs.
        raise SnapshotError(f'Private GitHub snapshot restore failed ({type(exc).__name__})') from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
