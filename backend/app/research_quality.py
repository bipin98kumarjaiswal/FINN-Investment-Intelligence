"""FINN Phase 4.1: layout-aware PDF passages + transparent lexical reranking.

No LLM/embedding service. Page citations and primary-source URLs remain unchanged.
Old rows are NOT silently upgraded: run `python -m scripts.reindex_research --symbol INFY`.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict

import fitz

MAX_CHARS = 1350
MIN_NARRATIVE_CHARS = 65
EXTRA_STOP = {
    'what', 'which', 'where', 'when', 'does', 'about', 'from', 'this', 'that',
    'were', 'have', 'will', 'should', 'would', 'could', 'tell', 'explain',
    'please', 'company', 'companies', 'there', 'their', 'with', 'your',
    'some', 'them', 'into', 'these', 'than', 'then', 'the', 'and', 'for',
    'are', 'was', 'has', 'how', 'did', 'its', 'any', 'report', 'annual',
}
RISK_TERMS = (
    'risk', 'risks', 'risk management', 'risk factors', 'principal risks',
    'cybersecurity', 'cyber security', 'information security', 'data protection',
    'data privacy', 'operational risk', 'financial risk', 'compliance risk',
    'regulatory risk', 'business continuity', 'geopolitical',
)


def normalized(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').replace('\u00ad', '')).strip()


# A short *complete* financial assertion is meaningful evidence, unlike a
# compact row of financial-statement table figures. Keep this exception narrow:
# it must identify a financial metric, contain a verb/predicate, and attach a
# numerical value to a unit. Do NOT accept headings such as "Net Profit/Loss".
_FINANCIAL_METRIC = re.compile(
    r'\b(?:revenue|sales|profit|loss|pat|ebitda?|operating\s+margin|margins?|'
    r'capex|capital\s+expenditure|cash\s+flow|growth|guidance|outlook|earnings)\b', re.I
)
_FINANCIAL_PREDICATE = re.compile(
    r'\b(?:was|were|is|are|grew|rose|fell|declined|decreased|increased|'
    r'reported|achieved|reached|expects?|expected|forecast|forecasts|'
    r'guided|guides|stood|stands|projects?|delivered|recorded)\b', re.I
)
_FINANCIAL_QUANTITY = re.compile(
    r'(?:[+-]?\d[\d,]*(?:\.\d+)?\s*(?:%|per\s*cent|percent|'
    r'crores?|lakhs?|lacs?|million|billion)'
    r'|(?:₹|\bINR\b|\bRs\.?)\s*\d[\d,]*(?:\.\d+)?)', re.I
)
_NUMERIC_TOKEN = re.compile(r'(?<!\w)[+-]?\d[\d,]*(?:\.\d+)?')
_TABLE_NUMERIC_RUN = re.compile(
    r'(?<!\w)\d[\d,]*(?:\.\d+)?\s+'
    r'\d[\d,]*(?:\.\d+)?\s+'
    r'\d[\d,]*(?:\.\d+)?\b'
)


def is_short_financial_statement(text: str) -> bool:
    """Keep concise metric/value statements, never unstructured numeric rows.

    Only compensates for the old length/word-count gates. All numeric-density,
    multi-row-table and broken-column checks in classify_layout_noise remain.
    """
    lines = [normalized(x) for x in (text or '').splitlines() if normalized(x)]
    if not 1 <= len(lines) <= 2:
        return False
    prose = ' '.join(lines)
    if not 20 <= len(prose) <= 330:
        return False
    if len(re.findall(r'[A-Za-z]{2,}', prose)) < 3:
        return False
    if not (_FINANCIAL_METRIC.search(prose) and _FINANCIAL_PREDICATE.search(prose)
            and _FINANCIAL_QUANTITY.search(prose)):
        return False
    values = _NUMERIC_TOKEN.findall(prose)
    if len(values) > 3 or _TABLE_NUMERIC_RUN.search(prose):
        return False
    # These are table headers, not assertions of net losses or profitability.
    if re.search(r'\b(?:profit\s*[/|]\s*\(?loss\)?|profit\s*\(loss\))\b', prose, re.I):
        return False
    return True


def classify_layout_noise(text: str) -> bool:
    """Prefer prose. These heuristics avoid ranking extracted numeric tables as narrative.

    This is intentionally conservative; financial tables are NOT reliably parsed into
    metric/period pairs here and must not become unsupported prose answers.
    """
    lines = [normalized(x) for x in (text or '').splitlines() if normalized(x)]
    if not lines:
        return True
    words = re.findall(r'[A-Za-z]{2,}', text)
    digits = re.findall(r'(?<!\w)[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?%?', text)
    if (len(text) < 65 or len(words) < 10) and not is_short_financial_statement(text):
        return True
    if len(digits) > 12 and len(digits) > len(words) * .32:
        return True
    tiny = sum(len(line) <= 25 for line in lines)
    if len(lines) >= 6 and tiny / len(lines) > .70:
        return True
    if len(lines) >= 4 and sum(bool(re.search(r'\d\s+\d\s+\d', line)) for line in lines) >= 3:
        return True
    # A column of separate amount rows is unreliable as a narrative passage.
    if len(lines) >= 5 and sum(bool(re.fullmatch(r'[\d.,()%+\-₹$ ]+', line)) for line in lines) >= 3:
        return True
    return False


def _block_text(block: dict) -> str:
    """Reconstruct lines from spans, keeping a paragraph inside ONE PDF block."""
    lines = []
    for line in block.get('lines', []):
        spans = line.get('spans', [])
        text = ''.join(span.get('text', '') for span in spans)
        text = normalized(text)
        if text:
            lines.append(text)
    return '\n'.join(lines)


def _column(block: dict, page_width: float) -> str:
    x0, _, x1, _ = block['bbox']
    if (x1 - x0) > page_width * .67:
        return 'wide'
    return 'left' if (x0 + x1) / 2 < page_width / 2 else 'right'


def _fragments(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split on sentence boundaries; never glue unrelated columns together."""
    paragraphs = [normalized(p) for p in text.split('\n') if normalized(p)]
    if not paragraphs:
        return []
    text = ' '.join(paragraphs)
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z(“\"\d])', text)
    fragments, current = [], ''
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                fragments.append(current)
                current = ''
            words = sentence.split()
            chunk = ''
            for word in words:
                if len(chunk) + len(word) + 1 > max_chars and chunk:
                    fragments.append(chunk)
                    chunk = ''
                chunk = (chunk + ' ' + word).strip()
            if chunk:
                fragments.append(chunk)
        elif len(current) + len(sentence) + 1 <= max_chars:
            current = (current + ' ' + sentence).strip()
        else:
            if current:
                fragments.append(current)
            current = sentence
    if current:
        fragments.append(current)
    return fragments


def extract_clean_pdf(raw: bytes, error_type=ValueError, max_pages: int = 450):
    """Extract coherent prose chunks using text-block layout and a reading-order guard.

    Returns (page_count, [{page, text}, ...]) as expected by research_store.store_document.
    Drops table-like material instead of allowing it to contaminate evidence-only Q&A.
    """
    if not raw.startswith(b'%PDF-'):
        raise error_type('Not a PDF')
    try:
        doc = fitz.open(stream=raw, filetype='pdf')
    except Exception as exc:
        raise error_type(f'PDF could not be opened: {exc}') from exc
    with doc:
        if doc.needs_pass:
            raise error_type('Encrypted PDF unsupported')
        if len(doc) > max_pages:
            raise error_type(f'PDF has more than {max_pages} pages')
        collected, seen = [], set()
        for page_index, page in enumerate(doc):
            blocks = []
            for block in page.get_text('dict', sort=False).get('blocks', []):
                if block.get('type') != 0:
                    continue
                x0, y0, x1, y1 = block['bbox']
                if y1 < 34 or y0 > page.rect.height - 28:
                    continue  # repeating page headers/footers
                text = _block_text(block)
                if not text or classify_layout_noise(text):
                    continue
                blocks.append({'column': _column(block, page.rect.width),
                               'bbox': block['bbox'], 'text': text})
            # Reassemble paragraphs only within the same column and near vertical blocks.
            for col in ('wide', 'left', 'right'):
                items = sorted((b for b in blocks if b['column'] == col),
                               key=lambda b: (b['bbox'][1], b['bbox'][0]))
                active, previous = '', None
                for b in items:
                    # Don't join disconnected paragraphs/tables/separate regions.
                    gap = b['bbox'][1] - previous['bbox'][3] if previous else 999
                    combined = len(active) + len(b['text']) + 1 <= MAX_CHARS
                    # Only merge a short header-like block with following related prose.
                    prev_is_heading = previous and len(previous['text']) < 145 and previous['text'][-1:] not in '.!?'
                    if active and not (0 <= gap < 24 and combined and prev_is_heading):
                        for fragment in _fragments(active):
                            if (len(fragment) >= MIN_NARRATIVE_CHARS or is_short_financial_statement(fragment)) and not classify_layout_noise(fragment):
                                key = hashlib.sha1(normalized(fragment.lower()).encode()).hexdigest()
                                if key not in seen:
                                    collected.append({'page': page_index + 1, 'text': fragment})
                                    seen.add(key)
                        active = ''
                    active = (active + '\n' + b['text']).strip() if active else b['text']
                    previous = b
                if active:
                    for fragment in _fragments(active):
                        if (len(fragment) >= MIN_NARRATIVE_CHARS or is_short_financial_statement(fragment)) and not classify_layout_noise(fragment):
                            key = hashlib.sha1(normalized(fragment.lower()).encode()).hexdigest()
                            if key not in seen:
                                collected.append({'page': page_index + 1, 'text': fragment})
                                seen.add(key)
        if not collected:
            raise error_type('No readable narrative passages extracted: no usable selectable text (PDF may be scanned or table-only).')
        return len(doc), collected


def question_terms(question: str):
    words = re.findall(r'[a-z0-9]+', question.lower())
    core = list(dict.fromkeys(w for w in words if len(w) > 2 and w not in EXTRA_STOP))[:10]
    risk = any(w in core for w in ('risk', 'risks', 'cybersecurity', 'security', 'threats'))
    return core, risk


def _quality_rerank_score(entry: dict, tokens: list[str], risk_intent: bool) -> float:
    text = normalized(entry.get('text') or entry.get('excerpt') or '')
    lower = text.lower()
    if not text:
        return -100.0
    if classify_layout_noise(text):
        return -30.0
    present = [t for t in tokens if re.search(r'\b' + re.escape(t) + r'\b', lower)]
    coverage = len(present) / max(1, len(tokens))
    score = coverage * 12 + min(len(present), 6) * 1.4
    # Dense, short evidence fragments and loose table remnants are less reliable.
    word_count = len(text.split())
    score += 2.5 if 35 <= word_count <= 180 else 0
    if word_count < 18 and not is_short_financial_statement(text):
        score -= 7
    digit_density = sum(c.isdigit() for c in text) / max(1, len(text))
    if digit_density > .18:
        score -= 7
    if risk_intent:
        if any(phrase in lower for phrase in ('risk management', 'risk factors', 'principal risks', 'key risks', 'material risks')):
            score += 10
        if any(phrase in lower for phrase in ('cybersecurity', 'cyber security', 'information security', 'data privacy', 'data protection')):
            score += 8
        if any(phrase in lower for phrase in ('operational risk', 'regulatory risk', 'financial risk', 'business continuity')):
            score += 5
        if 'risk' not in lower and 'security' not in lower and 'privacy' not in lower:
            score -= 8
    # BM25 ranking is helpful but cannot dominate readability / query coverage.
    relevance = entry.get('relevance')
    if relevance is not None:
        score += min(3.0, max(0.0, -float(relevance) * .20))
    return round(score, 4)


def rerank_candidates(candidates: list[dict], question: str, limit: int = 7) -> list[dict]:
    tokens, risk_intent = question_terms(question)
    seen = set()
    scores = []
    for row in candidates:
        text = normalized(row.get('text') or row.get('excerpt') or '')
        if (len(text) < MIN_NARRATIVE_CHARS and not is_short_financial_statement(text)) or classify_layout_noise(text):
            continue
        fingerprint = hashlib.sha1(re.sub(r'\W+', '', text.lower()).encode()).hexdigest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        score = _quality_rerank_score(row, tokens, risk_intent)
        if score <= 0:
            continue
        scores.append((score, row))
    scores.sort(key=lambda x: (-x[0], str(x[1].get('document_id')), int(x[1].get('page') or 0)))
    selected, pages = [], Counter()
    for score, row in scores:
        key = (row.get('document_id'), row.get('page'))
        if pages[key] >= 2:
            continue
        pages[key] += 1
        selected.append({**row, 'evidence_quality_score': score})
        if len(selected) >= limit:
            break
    return selected


def retrieve_quality_evidence(symbol: str, question: str, path=None, limit: int = 7):
    """Existing research_store.search_chunks API, improved candidate coverage + rerank.

    Several small FTS5 searches prevent a single generic word (e.g. 'risk') from
    monopolizing the top 80 results of a long annual report.
    """
    from app import research_store
    core, risk_intent = question_terms(question)
    if not core:
        return []
    queries = [core]
    if risk_intent:
        queries += [
            ['risk', 'management', 'principal'],
            ['cybersecurity', 'security', 'privacy', 'data'],
            ['operational', 'regulatory', 'compliance', 'geopolitical'],
            ['business', 'continuity', 'risk'],
        ]
    # Use independent candidate pools; FTS5 OR match for each list.
    all_rows = []
    for tokens in queries:
        all_rows.extend(research_store.search_chunks(symbol, tokens, 65 if len(queries) == 1 else 34, path))
    selected = rerank_candidates(all_rows, question, limit)
    return [{**{k: v for k, v in row.items() if k != 'text'},
             'id': f'S{i + 1}', 'excerpt': row['text'][:1300]}
            for i, row in enumerate(selected)]
