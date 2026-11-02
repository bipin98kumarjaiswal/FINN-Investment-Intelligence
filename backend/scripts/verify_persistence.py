"""Read-only release gate for FINN's populated SQLite database and research FTS.

Use BEFORE and AFTER restarting/redeploying a backend with its persistent disk:
  python -m scripts.verify_persistence --mode before --snapshot /var/data/finn-persistence.json
  python -m scripts.verify_persistence --mode after  --snapshot /var/data/finn-persistence.json

Does not send private data to stdout; compares source record counts and hashes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

# Only compare stable primary-source and market fields; no API keys or raw text
# are written to the summary. Text is INCLUDED in digests to prove passages survive.
TABLE_QUERIES = {
    'daily_prices': 'SELECT symbol,trade_date,open,high,low,close,volume FROM daily_prices ORDER BY symbol,trade_date',
    'announcements': 'SELECT filing_id,symbol,published_at_utc,subject,details,source_url FROM announcements ORDER BY filing_id',
    'research_documents': 'SELECT id,symbol,title,kind,source_url,file_hash,page_count,chunk_count FROM research_documents ORDER BY id',
    'research_chunks': 'SELECT rowid,symbol,doc_id,page,text FROM research_chunks ORDER BY rowid',
    'research_companies': 'SELECT symbol,name,source FROM research_companies ORDER BY symbol',
}


def _read_digest(conn, query):
    h = hashlib.sha256()
    count = 0
    for row in conn.execute(query):
        data = json.dumps(tuple(row), ensure_ascii=False, separators=(',', ':'), default=str)
        h.update(data.encode('utf-8'))
        h.update(b'\n')
        count += 1
    return {'rows': count, 'sha256': h.hexdigest()}


def audit(db: Path):
    db = Path(db).expanduser().resolve()
    if not db.is_file():
        raise RuntimeError(f'SQLite DB not found: {db} (FINN_DB_PATH must point to the persistent disk)')
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=15) as conn:
        conn.execute('BEGIN')  # consistent read snapshot, even if application has other connections
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError(f'SQLite integrity check failed: {integrity}')
        counts = {table: _read_digest(conn, query) for table, query in TABLE_QUERIES.items()}
        # Ensure this is NOT a newly created/empty database that coincidentally passes integrity.
        if not counts['daily_prices']['rows'] or not counts['research_documents']['rows'] or not counts['research_chunks']['rows']:
            raise RuntimeError('Database missing price rows or indexed research documents/passages; check disk mount or upload')
        if not counts['announcements']['rows']:
            raise RuntimeError('Database has no actual exchange announcements; check the deployed snapshot')
        docs = conn.execute('SELECT COUNT(DISTINCT doc_id) FROM research_chunks').fetchone()[0]
        if docs < 1:
            raise RuntimeError('No searchable research documents in SQLite FTS')
        # Prove a concrete INFY source is present, not only other tickers.
        infy = conn.execute("SELECT COUNT(*) FROM research_documents WHERE symbol='INFY'").fetchone()[0]
        if infy < 1:
            raise RuntimeError('Infosys indexed documents missing in deployed SQLite')
        return {'database_path': str(db), 'tables': counts, 'infosys_indexed_docs': infy,
                'indexed_doc_ids_with_passages': docs}


def check(before, after):
    issues = []
    for key, earlier in before['tables'].items():
        current = after['tables'].get(key, {})
        if earlier['rows'] != current.get('rows'):
            issues.append(f'{key}: count changed from {earlier["rows"]} to {current.get("rows")}')
        if earlier['sha256'] != current.get('sha256'):
            issues.append(f'{key}: content fingerprint changed across restart')
    if before['infosys_indexed_docs'] != after['infosys_indexed_docs']:
        issues.append('Infosys indexed document count changed')
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description='Audit FINN SQLite data across a deployed backend restart')
    parser.add_argument('--mode', choices=('before', 'after'), required=True)
    parser.add_argument('--db', type=Path, default=Path(os.getenv('FINN_DB_PATH', '/var/data/finn.sqlite3')))
    parser.add_argument('--snapshot', type=Path, default=Path('/var/data/finn-persistence-baseline.json'))
    args = parser.parse_args(argv)
    result = audit(args.db)
    summary = ', '.join(f'{name}={x["rows"]}' for name, x in result['tables'].items())
    print('SQLite integrity: ok')
    print('Source counts:', summary)
    print('Indexed Infosys docs:', result['infosys_indexed_docs'])
    if args.mode == 'before':
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        if args.snapshot.exists():
            raise RuntimeError(f'Existing snapshot: {args.snapshot}. Use a new snapshot path for each restart test.')
        args.snapshot.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('Baseline saved to', args.snapshot)
        print('Now restart/redeploy the Render service WITHOUT syncing or reindexing in between.')
        return 0
    if not args.snapshot.is_file():
        raise RuntimeError(f'Before-restart snapshot not found: {args.snapshot}')
    previous = json.loads(args.snapshot.read_text(encoding='utf-8'))
    if previous['database_path'] != result['database_path']:
        raise RuntimeError('DB path changed across restart; likely using a different disk/mount')
    problems = check(previous, result)
    if problems:
        print('Persistence verification FAILED:')
        for reason in problems:
            print(' -', reason)
        print('If data was intentionally updated, take a new baseline and repeat without background jobs.')
        return 1
    print('PERSISTENCE VERIFIED: prices, filings, research document metadata and ALL indexed passage content match baseline.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, sqlite3.DatabaseError, OSError, ValueError) as exc:
        raise SystemExit(f'Persistence verification FAILED: {exc}')
