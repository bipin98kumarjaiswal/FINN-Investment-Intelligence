"""LIVE acceptance test using the user's own indexed real Infosys PDFs + API key.

Does not import fake fixtures, update SQLite, download filings, or print secrets.
Run: python -m scripts.test_infosys_gemini
"""
import re
from app import research_ai, research_store, research_service

CASES = [
    ('Business risks', 'What business risks and cybersecurity exposures does Infosys describe?', True),
    ('Risk controls', 'What risk management and information security controls are described?', True),
    ('Unavailable information', 'What was Infosys profit from the Neptune spacecraft project in FY2042?', False),
]


def run():
    if not research_ai.configured():
        raise RuntimeError('GEMINI_API_KEY is not configured in the backend process')
    indexed=research_store.documents('INFY')
    if not indexed:
        raise RuntimeError('No real Infosys primary-source documents indexed. Do not call this a passing test.')
    print('Indexed Infosys source documents:',len(indexed))
    total_ok=0
    for label,question,expect_answer in CASES:
        result=research_service.answer('INFY',question)
        status=result['status']
        sources={s['id']:s for s in result.get('sources',[])}
        citations=result.get('verified_citations',[])
        print('\nCASE:',label,'|',status)
        print('QUESTION:',question)
        print('RESPONSE:',result.get('answer','')[:1800])
        for cited in citations:
            src=sources.get(cited)
            if not src:
                raise AssertionError(f'Citation {cited} does not exist in retrieved evidence')
            print('VERIFIED SOURCE:',cited,src['title'],'page',src['page'],src['source_url'])
        if expect_answer:
            if status=='answered' and citations:
                print('[PASS] Source-only quoted answer with verified citations')
                total_ok+=1
            else:
                print('[REVIEW] No supported answer. Not a fabricated success.')
        else:
            if status!='insufficient_evidence':
                raise AssertionError('Unsupported Neptune-profit question was not refused')
            print('[PASS] Correctly abstained on unsupported financial information')
            total_ok+=1
    print('\nConfirmed passing cases:',total_ok,'of',len(CASES))
    if total_ok < len(CASES):
        raise RuntimeError('Some evidence-backed questions were not answered. Review the retrieval or model output; do not claim live tests passed.')


if __name__=='__main__': run()
