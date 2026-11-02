"""Independent additive research tables. Does not alter Push portfolio tables."""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from app import database
from app.portfolio import PORTFOLIO


def now():
    return datetime.now(timezone.utc).isoformat()


def init(path: Path | None = None):
    database.init_db(path)
    with closing(database.connect(path)) as con:
        with con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS research_companies (
                symbol TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL REFERENCES research_companies(symbol),
                title TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('annual_report','transcript','results','presentation')),
                source_url TEXT NOT NULL,
                published_on TEXT,
                period TEXT,
                file_hash TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                indexed_at_utc TEXT NOT NULL,
                UNIQUE(symbol, source_url)
            );
            CREATE INDEX IF NOT EXISTS idx_research_documents_symbol ON research_documents(symbol);
            CREATE VIRTUAL TABLE IF NOT EXISTS research_chunks USING fts5(
                text, symbol UNINDEXED, doc_id UNINDEXED, page UNINDEXED,
                tokenize='porter unicode61'
            );
            ''')
            con.executemany('''INSERT OR IGNORE INTO research_companies(symbol,name,source,updated_at_utc)
                VALUES (:symbol,:name,'demo_portfolio',:at)''',
                [dict(item,at=now()) for item in PORTFOLIO])


def save_catalog(entries: list[dict], path: Path | None = None) -> int:
    init(path)
    with closing(database.connect(path)) as con:
        with con:
            con.executemany('''INSERT INTO research_companies(symbol,name,source,updated_at_utc)
            VALUES (:symbol,:name,'NSE equity list',:updated_at_utc)
            ON CONFLICT(symbol) DO UPDATE SET name=excluded.name,source=excluded.source,
            updated_at_utc=excluded.updated_at_utc''',
            [dict(x,updated_at_utc=now()) for x in entries])
    return len(entries)


def companies(q: str, path: Path | None = None, limit=15):
    init(path)
    with closing(database.connect(path)) as con:
        return [dict(x) for x in con.execute('''SELECT symbol,name,source FROM research_companies
             WHERE symbol LIKE ? OR name LIKE ?
             ORDER BY CASE WHEN symbol=? THEN 0 WHEN symbol LIKE ? THEN 1 ELSE 2 END,name
             LIMIT ?''', (f'%{q.upper()}%',f'%{q}%',q.upper(),f'{q.upper()}%',limit)).fetchall()]


def known_company(symbol: str, path: Path | None = None):
    init(path)
    with closing(database.connect(path)) as con:
        row=con.execute('SELECT symbol,name,source FROM research_companies WHERE symbol=?',(symbol,)).fetchone()
        return dict(row) if row else None


def documents(symbol: str, path: Path | None = None):
    init(path)
    with closing(database.connect(path)) as con:
        return [dict(x) for x in con.execute('''SELECT * FROM research_documents WHERE symbol=?
            ORDER BY COALESCE(published_on,'') DESC,id DESC''',(symbol,)).fetchall()]


def get_document(symbol: str, url: str, path: Path | None = None):
    init(path)
    with closing(database.connect(path)) as con:
        row=con.execute('SELECT * FROM research_documents WHERE symbol=? AND source_url=?',(symbol,url)).fetchone()
        return dict(row) if row else None


def store_document(symbol: str, title: str, kind: str, url: str, published_on: str|None,
                   period: str|None, file_hash: str, page_count: int,
                   chunks: list[dict], path: Path|None = None):
    init(path)
    with closing(database.connect(path)) as con:
        with con:
            con.execute('''INSERT INTO research_documents(symbol,title,kind,source_url,published_on,
                period,file_hash,page_count,chunk_count,indexed_at_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,source_url) DO UPDATE SET
                title=excluded.title,kind=excluded.kind,published_on=excluded.published_on,
                period=excluded.period,file_hash=excluded.file_hash,page_count=excluded.page_count,
                chunk_count=excluded.chunk_count,indexed_at_utc=excluded.indexed_at_utc''',
                (symbol,title,kind,url,published_on,period,file_hash,page_count,len(chunks),now()))
            doc_id=con.execute('SELECT id FROM research_documents WHERE symbol=? AND source_url=?',(symbol,url)).fetchone()['id']
            con.execute('DELETE FROM research_chunks WHERE doc_id=?',(str(doc_id),))
            con.executemany('INSERT INTO research_chunks(text,symbol,doc_id,page) VALUES (?,?,?,?)',
                            [(c['text'],symbol,str(doc_id),str(c['page'])) for c in chunks])
    return get_document(symbol,url,path)


def search_chunks(symbol: str, terms: list[str], limit: int=8, path: Path|None=None):
    init(path)
    if not terms:
        return []
    query=' OR '.join('"'+term.replace('"','')+'"' for term in terms)
    with closing(database.connect(path)) as con:
        rows=con.execute('''SELECT c.text,CAST(c.page AS INTEGER) AS page,
          CAST(c.doc_id AS INTEGER) AS document_id,d.title,d.kind,d.source_url,d.period,d.published_on,
          bm25(research_chunks) AS relevance FROM research_chunks c
          JOIN research_documents d ON d.id=CAST(c.doc_id AS INTEGER)
          WHERE research_chunks MATCH ? AND c.symbol=? ORDER BY relevance LIMIT ?''',
          (query,symbol,limit)).fetchall()
        return [dict(r) for r in rows]
