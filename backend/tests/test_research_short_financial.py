"""Regression for 3 Phase-4.1 regressions: two short finance passages + error text.

Tests use generated PDF bytes only and never contact company / exchange servers.
"""
import importlib.util
from pathlib import Path
import fitz
import pytest

try:
    from app.research_quality import (
        extract_clean_pdf, classify_layout_noise,
        is_short_financial_statement, rerank_candidates,
    )
except ModuleNotFoundError:
    location = Path(__file__).resolve().parents[1] / 'app/research_quality.py'
    spec = importlib.util.spec_from_file_location('quality_under_test', location)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    extract_clean_pdf = mod.extract_clean_pdf
    classify_layout_noise = mod.classify_layout_noise
    is_short_financial_statement = mod.is_short_financial_statement
    rerank_candidates = mod.rerank_candidates


def pdf_with_statements(*statements):
    with fitz.open() as doc:
        page=doc.new_page(width=880, height=740)
        for i, sentence in enumerate(statements):
            page.insert_text((47, 90 + i*60), sentence, fontsize=10)
        return doc.tobytes()


@pytest.mark.parametrize('statement', [
    'Management guidance for FY2026 revenue growth was 12 percent.',
    'FY2026 guidance: consolidated revenue growth guidance is 12 percent.',
    'FY2026 consolidated revenue growth actual was 10 percent.',
    'Revenue growth was 12%.',
])
def test_short_complete_financial_sentence_is_kept_and_retrievable(statement):
    assert is_short_financial_statement(statement)
    assert not classify_layout_noise(statement)
    pages, snippets = extract_clean_pdf(pdf_with_statements(statement))
    assert pages == 1
    assert len(snippets) == 1
    assert snippets[0]['page'] == 1
    assert statement in snippets[0]['text']
    relevant = rerank_candidates([{'document_id': 1,'page': 1,
         'text': snippets[0]['text'], 'relevance': -4}],
         'What was FY2026 revenue growth guidance?', 5)
    assert relevant and relevant[0]['page'] == 1


def test_table_noise_filters_remain_strict():
    noisy = '''Revenue growth   FY2026 FY2025 FY2024
    12  10  7
    5  8  9
    Net Profit/Loss 2026 2025 2024
    100 200 300
    Assets 400 500 600'''
    assert classify_layout_noise(noisy)
    for line in ['Revenue 2026 2025 2024 15 13 12',
                 'Net Profit/Loss after tax 12 percent.',
                 'Cash 900 300 100',
                 'Profit 200 300 400']:
        assert classify_layout_noise(line), line
        assert not is_short_financial_statement(line), line
    # A valid sentence and a detached tabular cluster on one PDF page.
    with fitz.open() as doc:
        page=doc.new_page(width=900, height=740)
        page.insert_text((47, 90), 'Management guidance for FY2026 revenue growth was 12 percent.', fontsize=10)
        page.insert_textbox(fitz.Rect(47, 230, 700, 490),noisy,fontsize=10)
        raw=doc.tobytes()
    pages, chunks=extract_clean_pdf(raw)
    assert pages==1
    assert any('revenue growth was 12 percent' in x['text'] for x in chunks)
    assert all('Assets 400 500 600' not in x['text'] for x in chunks)


def test_original_error_wording_compatible_with_old_and_new_tests():
    with fitz.open() as doc:
        doc.new_page()
        raw=doc.tobytes()
    with pytest.raises(ValueError) as err:
        extract_clean_pdf(raw)
    assert 'No readable narrative' in str(err.value)
    assert 'selectable' in str(err.value)


def test_short_revenue_guidance_and_actual_on_separate_documents():
    texts = (
        'FY2026 guidance: consolidated revenue growth guidance is 12 percent.',
        'FY2026 consolidated revenue growth actual was 10 percent.',
    )
    results=[]
    for text in texts:
        count, chunks = extract_clean_pdf(pdf_with_statements(text))
        assert count == 1
        results.append(chunks[0]['text'])
    assert results[0] != results[1]
    assert all(classify_layout_noise(x) is False for x in results)
