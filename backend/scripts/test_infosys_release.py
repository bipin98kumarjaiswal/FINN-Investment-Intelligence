"""Live acceptance tests against your EXISTING indexed Infosys primary PDFs.

1. Actual Gemini call for risks and risk-controls questions.
2. A deliberately forced quotation-verification failure, using ACTUAL retrieved
   Infosys source passages (no Gemini call for this forced-case test).
3. Unsupported financial question must not produce fabricated profit.

Does not ingest, reindex, or modify the user's SQLite database.
"""
from app import research_ai, research_store, research_service
from unittest.mock import patch

QUESTIONS = [
    ('Business risks', 'What business risks and cybersecurity exposures does Infosys describe?'),
    ('Risk controls', 'What risk management and information security controls are described?'),
]
UNKNOWN = 'What was Infosys profit from the Neptune spacecraft project in FY2042?'


def verify_pages(result):
    found = result.get('sources', [])
    if not found:
        raise AssertionError('No relevant source excerpts to display')
    for source in found:
        if (not source.get('id') or not source.get('source_url') or
                not source.get('title') or not isinstance(source.get('page'), int)
                or source['page'] < 1 or not source.get('excerpt')):
            raise AssertionError('A retrieved source lacks its title, link, page or original text')
    return found


def run():
    docs = research_store.documents('INFY')
    if not docs:
        raise RuntimeError('No Infosys PDFs indexed in the active FINN_DB_PATH SQLite database')
    print('Indexed genuine Infosys documents:', len(docs))
    if not research_ai.configured():
        raise RuntimeError('GEMINI_API_KEY not set in this backend terminal')
    for label, question in QUESTIONS:
        result = research_service.answer('INFY', question)
        print('\nCASE:',label,'=>',result['status'])
        print('ANSWER:',result.get('answer','')[:800])
        if result['status'] not in ('answered','evidence_only'):
            raise AssertionError(f'{label}: expected a verified answer or evidence-only fallback')
        sources = verify_pages(result)
        if result['status'] == 'answered':
            valid = {s['id'] for s in sources}
            ids = result.get('verified_citations') or []
            if not ids or any(x not in valid for x in ids):
                raise AssertionError('Verified answer has no valid source citations')
            print('[PASS] Verified model quotations with source page references')
        else:
            if result.get('verified_citations'):
                raise AssertionError('Evidence-only result was incorrectly labelled as AI-verified')
            print('[PASS] Source-only fallback with original source pages; not a verified AI answer')
        print('TOP SOURCE:',sources[0]['title'],'PDF page',sources[0]['page'],sources[0]['source_url'])

    # Guaranteed failure injection exercises the fallback with real retrieval output.
    with patch.object(research_service, 'synthesise', side_effect=research_ai.ModelUnavailable(
        'Gemini quotation was not found verbatim in the cited PDF excerpt')):
        forced = research_service.answer('INFY', QUESTIONS[1][1])
    assert forced['status'] == 'evidence_only', 'Unverified quote was not safely rejected'
    assert forced['fallback_reason'] == 'ai_verification_failed'
    assert not forced['verified_citations']
    verify_pages(forced)
    print('\n[PASS] FORCED quote mismatch displays real indexed Infosys source excerpts and page links')

    missing = research_service.answer('INFY', UNKNOWN)
    print('\nCASE: Unsupported profit =>',missing['status'])
    if missing['status'] != 'insufficient_evidence':
        raise AssertionError('An unsupported financial question did not abstain safely')
    print('[PASS] No unsupported financial result generated')
    print('\nLIVE ACCEPTANCE: completed. Review actual PDF links before submission.')


if __name__=='__main__':
    run()
