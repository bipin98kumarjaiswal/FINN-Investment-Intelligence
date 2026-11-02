"""Rebuild research text for previously indexed primary documents (old FTS chunks).

The previous app caches indexed text, NOT original PDF binary. A fresh source
PDF download is required once after changing the extraction algorithm.
An existing document remains untouched if download/extraction fails.
"""
import argparse
from hashlib import sha256

from app import research_store
from app.research_pdf import fetch_pdf, extract_pdf, DocumentError


def reindex(symbol: str, limit: int = 10, apply: bool = False, download=fetch_pdf, path=None):
    symbol = symbol.strip().upper()
    research_store.init(path)
    if not research_store.known_company(symbol, path):
        raise ValueError('NSE symbol is not in the cached catalog')
    records = research_store.documents(symbol, path)[:limit]
    outcomes = []
    for record in records:
        if not apply:
            outcomes.append({'title': record['title'], 'status': 'dry_run',
                             'old_chunks': record['chunk_count'], 'url': record['source_url']})
            continue
        try:
            data = download(record['source_url'])
            page_count, chunks = extract_pdf(data)
            if not chunks:
                raise DocumentError('No readable passages; original index retained')
            # The existing store_document implementation updates text and metadata
            # transactionally. No delete is performed before PDF parsing succeeds.
            updated = research_store.store_document(
                symbol, record['title'], record['kind'], record['source_url'],
                record['published_on'], record['period'], sha256(data).hexdigest(),
                page_count, chunks, path,
            )
            outcomes.append({'title': updated['title'], 'status': 'reindexed',
                             'old_chunks': record['chunk_count'],
                             'new_chunks': updated['chunk_count'],
                             'pages': updated['page_count'], 'url': updated['source_url']})
        except Exception as exc:
            outcomes.append({'title': record['title'], 'status': 'error',
                             'error': f'{type(exc).__name__}: {exc}',
                             'old_chunks_retained': True, 'url': record['source_url']})
    return outcomes


def main():
    parser = argparse.ArgumentParser(description='Reindex real stored research PDFs with layout-aware extraction')
    parser.add_argument('--symbol', default='INFY', help='NSE ticker (default: INFY)')
    parser.add_argument('--max-documents', type=int, default=10)
    parser.add_argument('--apply', action='store_true', help='Actually redownload and replace old text; omit to preview')
    args = parser.parse_args()
    if args.max_documents < 1 or args.max_documents > 50:
        parser.error('--max-documents must be between 1 and 50')
    output = reindex(args.symbol, args.max_documents, args.apply)
    if not output:
        print('No indexed documents found. Index an actual annual report first.')
        raise SystemExit(2)
    for row in output:
        print(row)
    if not args.apply:
        print('DRY RUN: no records changed. Add --apply after checking the PDF source URLs.')
    if any(x['status'] == 'error' for x in output):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
