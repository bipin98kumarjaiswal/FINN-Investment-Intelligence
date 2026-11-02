"""Research router; all endpoints use the SAME SQLite DB as the existing Push app."""
import re
from typing import Literal
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app import research_store, research_service
from app.research_pdf import ingest, DocumentError

router=APIRouter(prefix='/api/research',tags=['Source-grounded research'])


def require_symbol(symbol):
    symbol=symbol.strip().upper()
    if not re.fullmatch(r'[A-Z0-9&-]{1,25}',symbol):
        raise HTTPException(422,'Invalid NSE ticker')
    item=research_store.known_company(symbol)
    if not item:
        raise HTTPException(404,'NSE ticker not in cached company catalog. Run python -m app.research_catalog --refresh')
    return item


class DocumentInput(BaseModel):
    symbol: str=Field(min_length=1,max_length=25)
    title: str=Field(min_length=5,max_length=180)
    kind: Literal['annual_report','transcript','results','presentation']
    url: str=Field(min_length=12,max_length=1600)
    published_on: date | None = None
    period: str | None=Field(default=None,max_length=30)


class AskInput(BaseModel):
    symbol: str=Field(min_length=1,max_length=25)
    question: str=Field(min_length=8,max_length=800)


class GuidanceInput(BaseModel):
    symbol: str
    metric: Literal['revenue_growth','operating_margin','capex']
    period: str=Field(pattern=r'^FY20\d{2}$')


@router.get('/search')
def search(q: str=Query(min_length=1,max_length=60)):
    items=research_store.companies(q.strip())
    return {'companies':items,'count':len(items),
            'note':'Search uses the cached NSE company list. Run catalog refresh periodically for newly listed symbols.'}


@router.get('/{symbol}/documents')
def list_documents(symbol: str):
    company=require_symbol(symbol)
    docs=research_store.documents(company['symbol'])
    return {'company':company,'count':len(docs),'documents':docs}


@router.get('/{symbol}/candidates')
def candidates(symbol: str, days: int=Query(default=90,ge=1,le=90)):
    company=require_symbol(symbol)
    try: return research_service.nse_candidates(company['symbol'],days)
    except Exception as exc:
        # Live NSE can reject/limit requests; don't fabricate candidate records.
        raise HTTPException(502,f'NSE candidate lookup failed: {type(exc).__name__}: {exc}') from exc


@router.post('/documents')
def add_document(item: DocumentInput):
    company=require_symbol(item.symbol)
    try:
        record=ingest(company['symbol'],item.url,item.title,item.kind,
                      item.published_on.isoformat() if item.published_on else None,item.period)
    except DocumentError as exc:
        raise HTTPException(422,str(exc)) from exc
    return {'document':record,'message':'Cached primary-source document indexed' if not record['cached']
            else 'Already indexed; reused cached text'}


@router.post('/ask')
def ask(item: AskInput):
    company=require_symbol(item.symbol)
    return {'company':company,**research_service.answer(company['symbol'],item.question)}


@router.post('/guidance')
def guidance(item: GuidanceInput):
    company=require_symbol(item.symbol)
    return {'company':company,**research_service.guidance_evidence(company['symbol'],item.metric,item.period)}
