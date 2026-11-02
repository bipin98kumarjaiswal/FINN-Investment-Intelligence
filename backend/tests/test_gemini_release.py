"""Offline release gates: never makes a real Gemini request or writes market data."""
import re

import pytest
from app import research_ai

SOURCES = [
    {'id':'S1','title':'Infosys annual report','page':42,'kind':'annual_report',
     'source_url':'https://www.infosys.com/annual-report.pdf',
     'excerpt':'The company identifies cybersecurity risk from malicious attacks and unauthorized data access. '
               'Its risk management approach includes monitoring cyber threats and security controls.'},
    {'id':'S2','title':'Infosys financial results','page':9,'kind':'results',
     'source_url':'https://www.infosys.com/results.pdf',
     'excerpt':'For FY2026, consolidated revenue growth was 9.5 percent compared with the prior year.'},
]


def simulate(payload):
    return lambda prompt, call=None: payload


def test_quotes_are_copied_verbatim_and_source_marked(monkeypatch):
    monkeypatch.setattr(research_ai,'generate_json', simulate({
      'insufficient_evidence':False, 'quotes':[{
        'source_id':'S1', 'quote':'The company identifies cybersecurity risk from malicious attacks and unauthorized data access.'}]}))
    result=research_ai.synthesise('What cybersecurity risks are described?',SOURCES)
    assert result['status']=='answered'
    assert result['verified_citations']==['S1']
    assert '[S1]' in result['answer']
    assert 'cybersecurity risk' in result['answer']


def test_hallucinated_number_is_rejected(monkeypatch):
    monkeypatch.setattr(research_ai,'generate_json', simulate({
      'insufficient_evidence':False,'quotes':[{'source_id':'S2',
        'quote':'For FY2026, consolidated revenue growth was 99.5 percent compared with the prior year.'}]}))
    with pytest.raises(research_ai.ModelUnavailable,match='not found verbatim'):
        research_ai.synthesise('How much did revenue grow in FY2026?',SOURCES)


def test_wrong_source_id_is_rejected(monkeypatch):
    monkeypatch.setattr(research_ai,'generate_json', simulate({
      'insufficient_evidence':False,'quotes':[{'source_id':'S99','quote':SOURCES[0]['excerpt'][:92]}]}))
    with pytest.raises(research_ai.ModelUnavailable,match='invalid source citations'):
        research_ai.synthesise('What cybersecurity risks are described?',SOURCES)


def test_missing_source_evidence_abstains(monkeypatch):
    monkeypatch.setattr(research_ai,'generate_json', simulate({'insufficient_evidence':True,'quotes':[]}))
    result=research_ai.synthesise('How much profit did Infosys earn from its Neptune base?',SOURCES)
    assert result['status']=='insufficient_evidence'
    assert not result['verified_citations']


def test_off_topic_quote_abstains(monkeypatch):
    monkeypatch.setattr(research_ai,'generate_json', simulate({
      'insufficient_evidence':False,'quotes':[{'source_id':'S2','quote':SOURCES[1]['excerpt']}]}))
    result=research_ai.synthesise('What was the Neptune spacecraft design?',SOURCES)
    assert result['status']=='insufficient_evidence'


def test_backwards_compat_invalid_citation(monkeypatch):
    monkeypatch.setattr(research_ai,'generate_json', simulate({'answer':'Invented [S99].', 'citation_ids':['S99'], 'insufficient_evidence':False}))
    with pytest.raises(research_ai.ModelUnavailable,match='invalid source citations'):
        research_ai.synthesise('What cybersecurity risks are described?',SOURCES)


def test_missing_key_does_not_contact_provider(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    assert not research_ai.configured()
    with pytest.raises(research_ai.ModelUnavailable,match='GEMINI_API_KEY'):
        research_ai.generate_json('Hello',lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network called')))


def test_key_only_in_header_never_url_or_prompt(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','secret-for-test')
    monkeypatch.setenv('FINN_GEMINI_MAX_CALLS_PER_PROCESS','999')
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {'candidates':[{'content':{'parts':[{'text':'{"ok":true}'}]}}]}
    def post(url,**kwargs):
        assert 'secret-for-test' not in url
        assert kwargs['headers']['x-goog-api-key']=='secret-for-test'
        assert 'secret-for-test' not in str(kwargs['json'])
        assert 'responseMimeType' in kwargs['json']['generationConfig']
        return FakeResponse()
    assert research_ai.generate_json('Test',post)=={'ok':True}


def test_realistic_infosys_risk_question_does_not_false_abstain(monkeypatch):
    monkeypatch.setattr(research_ai,'generate_json', simulate({
      'insufficient_evidence':False,'quotes':[{'source_id':'S1',
       'quote':'The company identifies cybersecurity risk from malicious attacks and unauthorized data access.'}]}))
    result=research_ai.synthesise('What business risks and cybersecurity exposures does Infosys describe?',SOURCES)
    assert result['status']=='answered'
