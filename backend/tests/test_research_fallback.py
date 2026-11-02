"""Gemini fallback: use already-retrieved evidence, never unverified model wording.

Run: python -m pytest -q tests/test_research_fallback.py
Uses mocked retrieval/AI; does NOT consume Gemini quota or write SQLite data.
"""
from app import research_service
from app.research_ai import ModelUnavailable

SOURCES = [
    {'id': 'S1', 'title': 'Infosys annual report', 'page': 32,
     'kind': 'annual_report', 'source_url': 'https://www.infosys.com/official.pdf',
     'excerpt': 'The company assesses cyber security and operational risk through its enterprise risk management framework.'},
    {'id': 'S2', 'title': 'Infosys annual report', 'page': 33,
     'kind': 'annual_report', 'source_url': 'https://www.infosys.com/official.pdf',
     'excerpt': 'Risk management activities include review of security controls and monitoring of emerging threats.'},
]


def prepare(monkeypatch):
    monkeypatch.setattr(research_service, 'citations_for', lambda *a, **k: SOURCES)
    monkeypatch.setattr(research_service, 'configured', lambda: True)


def test_unverifiable_quote_shows_original_excerpts(monkeypatch):
    prepare(monkeypatch)
    def invalid_model(*args, **kwargs):
        raise ModelUnavailable('Gemini quotation was not found verbatim in its cited PDF excerpt')
    monkeypatch.setattr(research_service, 'synthesise', invalid_model)
    result = research_service.answer('INFY', 'What information security controls does management describe?')
    assert result['status'] == 'evidence_only'
    assert result['method'] == 'extractive_retrieval'
    assert result['fallback_reason'] == 'ai_verification_failed'
    assert result['verified_citations'] == []
    assert result['sources'] == SOURCES
    assert result['sources'][0]['page'] == 32
    assert result['sources'][1]['source_url'].startswith('https://www.infosys.com/')
    assert 'unverified Gemini' not in result['answer']
    assert 'original document excerpts' in result['answer'].lower()
    assert 'quotation was not found' not in result['answer']


def test_provider_unavailable_same_safe_fallback(monkeypatch):
    prepare(monkeypatch)
    def unavailable(*args, **kwargs):
        raise ModelUnavailable('Gemini service returned HTTP 429')
    monkeypatch.setattr(research_service, 'synthesise', unavailable)
    result = research_service.answer('INFY', 'What business risks are mentioned in the annual report?')
    assert result['status'] == 'evidence_only'
    assert result['sources'] == SOURCES
    assert '429' not in result['answer']


def test_valid_verified_answer_unchanged(monkeypatch):
    prepare(monkeypatch)
    monkeypatch.setattr(research_service, 'synthesise', lambda *args, **kwargs: {
        'status': 'answered', 'answer': '“Risk management activities include review of security controls.” [S2]',
        'method': 'gemini_verified_extracts', 'verified_citations': ['S2'],
    })
    result = research_service.answer('INFY', 'What information security controls does management describe?')
    assert result['status'] == 'answered'
    assert result['verified_citations'] == ['S2']
    assert result['sources'] == SOURCES


def test_model_abstention_remains_abstention(monkeypatch):
    prepare(monkeypatch)
    monkeypatch.setattr(research_service, 'synthesise', lambda *args, **kwargs: {
        'status': 'insufficient_evidence', 'answer': 'Insufficient primary-source evidence.',
        'method': 'gemini_verified_extracts', 'verified_citations': [],
    })
    result = research_service.answer('INFY', 'What was profit on the Neptune spacecraft project in FY2042?')
    assert result['status'] == 'insufficient_evidence'
    assert 'fallback_reason' not in result


def test_existing_no_key_behavior(monkeypatch):
    monkeypatch.setattr(research_service, 'citations_for', lambda *a, **k: SOURCES)
    monkeypatch.setattr(research_service, 'configured', lambda: False)
    monkeypatch.setattr(research_service, 'synthesise', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Model must not be called')))
    result = research_service.answer('INFY', 'What cybersecurity risks are discussed in the annual report?')
    assert result['status'] == 'evidence_only'
    assert result['sources'] == SOURCES
