import io
from pathlib import Path
import fitz
import pytest
from fastapi.testclient import TestClient
from app import research_store, research_service
from app.research_pdf import ingest, DocumentError, extract_pdf, validate_url
from app.research_ai import synthesise, ModelUnavailable
from app.research_catalog import parse_catalog
from app.main import app


def pdf_bytes(text):
    doc=fitz.open(); page=doc.new_page(); page.insert_text((40,55),text,fontname='helv',fontsize=11)
    result=doc.tobytes();doc.close();return result


def test_research_index_and_qa_fallback(tmp_path,monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    path=tmp_path/'finn.sqlite3'
    research_store.init(path)
    raw=pdf_bytes('Management guidance for FY2026 revenue growth was 12 percent.')
    url='https://www.infosys.com/example-annual-report.pdf'
    saved=ingest('INFY',url,'Official report FY2026','annual_report',
                 '2026-06-01','FY2026',path,download=lambda _:raw)
    assert saved['page_count']==1
    assert saved['chunk_count']==1
    assert saved['file_hash']
    cached=ingest('INFY',url,'Official report FY2026','annual_report',
                  '2026-06-01','FY2026',path,download=lambda _: (_ for _ in ()).throw(Exception('Not cached')))
    assert cached['cached'] is True
    result=research_service.answer('INFY','What was guidance for FY2026 revenue growth?',path)
    assert result['status']=='evidence_only'
    assert result['sources'][0]['page']==1
    assert result['sources'][0]['source_url']==url
    assert len(research_store.documents('INFY',path))==1
    assert research_service.guidance_evidence('INFY','revenue_growth','FY2026',path)['comparison'] is None


def test_source_restriction_and_pdf_failures():
    for url in ['http://www.infosys.com/a.pdf','https://127.0.0.1/x',
                'https://localhost/x','https://evil.example/pdf','https://www.infosys.com@evil.example/pdf']:
        with pytest.raises(DocumentError): validate_url(url)
    with pytest.raises(DocumentError,match='selectable'):
        doc=fitz.open();doc.new_page();raw=doc.tobytes();doc.close();extract_pdf(raw)


def test_search_includes_outside_portfolio(tmp_path):
    path=tmp_path/'test.sqlite3'
    research_store.init(path)
    research_store.save_catalog([{'symbol':'PIDILITIND','name':'Pidilite Industries'}],path)
    assert research_store.companies('pidili',path)[0]['symbol']=='PIDILITIND'
    assert research_store.known_company('PIDILITIND',path)


def test_catalog_parser_requires_valid_schema():
    text='SYMBOL,NAME OF COMPANY,SERIES\n' + ''.join(f'TEST{i},Company {i},EQ\n' for i in range(115))
    assert len(parse_catalog(text))==115
    with pytest.raises(ValueError):parse_catalog('SYMBOL,NAME OF COMPANY,SERIES\nBAD,Invalid,EQ\n')


def test_citations_invalid_rejected(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','fake-key')
    sources=[{'id':'S1','title':'Test','page':1,'period':'FY2026','published_on':'2026-04-01','excerpt':'Revenue increased 10 percent.'}]
    def fake_ai(prompt,call):
        return {'answer':'Revenue rose by 10% [S99].','citation_ids':['S99'],'insufficient_evidence':False}
    monkeypatch.setattr('app.research_ai.generate_json',fake_ai)
    with pytest.raises(ModelUnavailable,match='invalid source'):
        synthesise('What happened?',sources)


def test_nse_discovery_candidate_typing(monkeypatch,tmp_path):
    from app import research_service
    class R:
        status_code=200
        headers={'Content-Type':'application/json'}
        def json(self):return [
            {'symbol':'INFY','desc':'Earnings call transcript','attchmntText':'Transcript filed',
             'attchmntFile':'https://nsearchives.nseindia.com/file.pdf'},
            {'symbol':'INFY','desc':'Trading window closure','attchmntFile':'https://nsearchives.nseindia.com/no.pdf'},
            {'symbol':'OTHER','desc':'Annual report','attchmntFile':'https://nsearchives.nseindia.com/other.pdf'}]
        def raise_for_status(self):pass
    class S:
        def get(self,*a,**k):return R()
    monkeypatch.setattr(research_service.research_store,'known_company',lambda symbol: {'symbol':symbol})
    result=research_service.nse_candidates('INFY',session=S())
    assert result['count']==1 and result['candidates'][0]['kind']=='transcript'


def test_research_api_uses_existing_database(tmp_path,monkeypatch):
    monkeypatch.setenv('FINN_DB_PATH',str(tmp_path/'existing.sqlite3'))
    with TestClient(app) as client:
        assert client.get('/api/portfolio').json()['count']==16
        r=client.get('/api/research/search?q=INFY')
        assert r.status_code==200 and r.json()['companies'][0]['symbol']=='INFY'
        assert client.get('/api/research/INFY/documents').json()['documents']==[]
        assert client.get('/api/research/INVALID/documents').status_code==404
        insufficient=client.post('/api/research/ask',json={'symbol':'INFY','question':'What was revenue growth?'}).json()
        assert insufficient['status']=='insufficient_evidence'
        unverified=client.post('/api/research/guidance',json={'symbol':'INFY','metric':'revenue_growth','period':'FY2026'}).json()
        assert unverified['status']=='insufficient_evidence' and unverified['comparison'] is None
        assert client.get('/api/briefing').status_code==200


def test_comparable_guidance_requires_verbatim_numeric_source_quotes(tmp_path,monkeypatch):
    path=tmp_path/'guidance.sqlite3'
    research_store.init(path)
    guidance_pdf=pdf_bytes('FY2026 guidance: consolidated revenue growth guidance is 12 percent.')
    actual_pdf=pdf_bytes('FY2026 consolidated revenue growth actual was 10 percent.')
    ingest('INFY','https://www.infosys.com/older-transcript.pdf','Older management call','transcript',
           '2025-10-23','FY2026',path,download=lambda _:guidance_pdf)
    ingest('INFY','https://www.infosys.com/newer-results.pdf','Later reported results','results',
           '2026-05-23','FY2026',path,download=lambda _:actual_pdf)
    monkeypatch.setenv('GEMINI_API_KEY','fake')
    def fake_json(prompt,call):
        # Select source numbers by their content, independently of retrieval ranking.
        sources=research_service.citations_for('INFY','revenue growth guidance actual FY2026',path,limit=12)
        guide=next(s for s in sources if s['kind']=='transcript')
        act=next(s for s in sources if s['kind']=='results')
        return {'comparable':True,
            'guidance':{'citation':guide['id'],'quote':'consolidated revenue growth guidance is 12 percent','value':12,'unit':'percent','basis':'consolidated'},
            'actual':{'citation':act['id'],'quote':'consolidated revenue growth actual was 10 percent','value':10,'unit':'percent','basis':'consolidated'}}
    monkeypatch.setattr('app.research_service.generate_json',fake_json)
    res=research_service.guidance_evidence('INFY','revenue_growth','FY2026',path)
    assert res['status']=='comparison_available'
    assert res['comparison']['difference']==-2
    def fake_bad(prompt,call):
        result=fake_json(prompt,call)
        result['actual']['value']=20  # a fabricated number must not pass verification
        return result
    monkeypatch.setattr('app.research_service.generate_json',fake_bad)
    res=research_service.guidance_evidence('INFY','revenue_growth','FY2026',path)
    assert res['status']=='insufficient_evidence' and res['comparison'] is None
