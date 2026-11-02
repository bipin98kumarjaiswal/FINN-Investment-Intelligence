"""Read-only test against the REAL Infosys PDFs already indexed in local SQLite."""
import argparse
import json
from app import research_store
from app.research_quality import retrieve_quality_evidence, classify_layout_noise, RISK_TERMS

QUESTION = 'What are the key business risks, including cybersecurity and risk management?'


def run(symbol='INFY', question=QUESTION, limit=7, path=None):
    docs = research_store.documents(symbol, path)
    if not docs:
        raise RuntimeError(f'No indexed primary PDFs for {symbol}. This is not a successful smoke test.')
    hits = retrieve_quality_evidence(symbol, question, path, limit)
    if not hits:
        raise RuntimeError('No readable relevant evidence found; review extraction and sources.')
    print(f'Indexed original primary PDFs: {len(docs)}')
    for doc in docs:
        print(f'  {doc["title"]} — {doc["page_count"]} pages; {doc["chunk_count"]} passages; {doc["source_url"]}')
    print('\nQUESTION:', question, '\n')
    print('New evidence ranking (real SQLite content):')
    for rank, hit in enumerate(hits, start=1):
        excerpt = hit['excerpt']
        terms = [t for t in RISK_TERMS if t in excerpt.lower()]
        print(f'\n{rank}. [{hit["id"]}] {hit["title"]} · p.{hit["page"]} · quality={hit["evidence_quality_score"]:.1f} · risk cues={terms[:4]}')
        print(excerpt[:480].replace('\n', ' '))
        print('Source:', hit['source_url'])
        if classify_layout_noise(excerpt):
            raise RuntimeError('A table-like passage survived the final ranking filter')
    return hits


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--symbol', default='INFY')
    p.add_argument('--question', default=QUESTION)
    p.add_argument('--limit', type=int, default=7)
    a = p.parse_args()
    run(a.symbol.upper(), a.question, a.limit)
