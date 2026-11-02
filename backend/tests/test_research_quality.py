"""Regression tests for Infosys-like multi-column risk pages and FTS5 ranking.

All PDF and source text in this test is synthetic; real Infosys validation is a
separate read-only command using the user's indexed genuine primary documents.
"""
import importlib.util
from pathlib import Path
import sys
import fitz
import pytest

# Works both inside installed FINN backend and when testing the standalone patch.
try:
    from app import research_quality as QUALITY
    from app.research_quality import (
        extract_clean_pdf, classify_layout_noise, rerank_candidates, question_terms,
    )
except ModuleNotFoundError:
    path = Path(__file__).resolve().parents[1] / 'app/research_quality.py'
    spec = importlib.util.spec_from_file_location('quality_under_test', path)
    QUALITY = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(QUALITY)
    extract_clean_pdf = QUALITY.extract_clean_pdf
    classify_layout_noise = QUALITY.classify_layout_noise
    rerank_candidates = QUALITY.rerank_candidates
    question_terms = QUALITY.question_terms


def paragraph(seed, times=5):
    return ' '.join([seed] * times)


def sample_pdf():
    doc = fitz.open()
    page = doc.new_page(width=650, height=800)
    left = paragraph('Our risk management framework identifies strategic and operational exposure. Cybersecurity and data privacy risks are monitored continuously.', 4)
    right = paragraph('Information security threats are addressed through employee awareness and business continuity planning. Principal risks receive oversight.', 4)
    page.insert_textbox(fitz.Rect(55, 105, 300, 510), left, fontsize=10, fontname='helv')
    page.insert_textbox(fitz.Rect(350, 105, 600, 510), right, fontsize=10, fontname='helv')
    # A noisy financial table block near the bottom; must not win a risk question.
    page.insert_textbox(fitz.Rect(55, 540, 580, 720),
        'Profit 2026 2025 2024\nRisk 120 300 450\nAssets 400 200 900\nCash 900 300 100\nIncome 120 350 780\nTotal 700 600 350',
        fontsize=10, fontname='helv')
    raw = doc.tobytes()
    doc.close()
    return raw


def test_two_columns_do_not_merge_or_promote_table_fragments():
    pages, chunks = extract_clean_pdf(sample_pdf())
    assert pages == 1
    assert len(chunks) >= 2
    assert all(x['page'] == 1 for x in chunks)
    assert any('cybersecurity' in x['text'].lower() for x in chunks)
    assert any('information security' in x['text'].lower() for x in chunks)
    assert all(not classify_layout_noise(x['text']) for x in chunks)
    assert all('Assets 400 200 900' not in x['text'] for x in chunks)
    assert all(len(x['text']) <= 1350 for x in chunks)


def test_risk_passages_outrank_generic_table_remnants():
    candidates = [
        {'document_id': 1, 'page': 1, 'text': 'Risk 20 30 40\nProfit 200 300 400\nAssets 500 600 700\nGrowth 2 3 4\nRevenue 100 200 300\nTotal 400 500 600', 'relevance': -12},
        {'document_id': 1, 'page': 2, 'text': paragraph('The company provides financial resources to support the business and investment plans.', 7), 'relevance': -5},
        {'document_id': 1, 'page': 32, 'text': paragraph('Our principal risks include cybersecurity vulnerabilities, information security threats and data privacy issues addressed through risk management controls.', 3), 'relevance': -4},
        {'document_id': 1, 'page': 56, 'text': paragraph('The risk management framework monitors operational risk, business continuity and regulatory risk with oversight by the risk committee.', 3), 'relevance': -3},
    ]
    ranked = rerank_candidates(candidates, 'What are the main business risks, especially cybersecurity and risk management?', 4)
    assert len(ranked) >= 2
    assert ranked[0]['page'] in (32, 56)
    assert {x['page'] for x in ranked[:2]} == {32, 56}
    assert all(x['page'] != 1 for x in ranked)
    assert all(x['evidence_quality_score'] > 0 for x in ranked)


def test_deduplication_and_page_diversity():
    row={'document_id':1,'page':3,'text':paragraph('Cybersecurity risks require information security controls and documented risk management.', 3),'relevance':-3}
    ranked=rerank_candidates([row,row, {**row,'page':4}], 'What are the cybersecurity risks?',3)
    assert len(ranked)==1  # exact paragraph repeated in multiple locations


def test_unclear_questions_do_not_force_evidence():
    assert question_terms('What are the risks?')[1]
    assert not rerank_candidates([{'document_id':1,'page':2,'text':'Revenue 10 20 30'}], 'What are the risks?')


def test_invalid_and_scanned_pdfs_rejected_explicitly():
    with pytest.raises(ValueError, match='Not a PDF'):
        extract_clean_pdf(b'<html>blocked</html>')
    with fitz.open() as doc:
        doc.new_page()
        with pytest.raises(ValueError, match='No readable narrative'):
            extract_clean_pdf(doc.tobytes())


def test_diversified_fts_calls_find_cybersecurity_deep_in_document(monkeypatch):
    """FTS 'risk' alone would miss a strong cybersecurity paragraph on a later page."""
    import types
    import sys
    import importlib.util
    quality = QUALITY
    calls=[]
    generic=[{'document_id':1,'page':n,'title':'Annual report','source_url':'https://www.infosys.com/report.pdf',
              'kind':'annual_report','relevance':-3,
              'text':paragraph('Investors should consider the risk of unfavorable currency changes in business operations.',4)} for n in range(1,25)]
    cyber={'document_id':1,'page':210,'title':'Annual report','source_url':'https://www.infosys.com/report.pdf',
           'kind':'annual_report','relevance':-3,
           'text':paragraph('Cybersecurity and information security risks are assessed with a comprehensive risk management framework and data privacy controls.',3)}
    def fake_search(symbol, tokens, limit, path):
        calls.append(tokens)
        if 'cybersecurity' in tokens or 'privacy' in tokens:
            return [cyber]
        return generic[:min(limit,20)]
    fake_app=types.ModuleType('app')
    fake_app.research_store=types.SimpleNamespace(search_chunks=fake_search)
    monkeypatch.setitem(sys.modules,'app',fake_app)
    ranked=quality.retrieve_quality_evidence('INFY','What are the key business risks including cybersecurity?',None,limit=5)
    assert len(calls)>=4
    assert ranked[0]['page']==210
    assert ranked[0]['id']=='S1' and ranked[0]['excerpt'].startswith('Cybersecurity')
