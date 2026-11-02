"""Ingest three verifiable, official Infosys PDFs. These are NOT mock filings."""
from app import research_store
from app.research_pdf import ingest, DocumentError

INFY_DOCUMENTS=[
    {'kind':'annual_report','title':'Infosys Integrated Annual Report FY2025–26',
     'url':'https://www.infosys.com/investors/reports-filings/annual-report/annual/documents/infosys-ar-26.pdf',
     'published_on':None,'period':'FY2026'},
    {'kind':'transcript','title':'Infosys Q2 FY2027 Earnings Conference Call',
     'url':'https://www.infosys.com/investors/reports-filings/quarterly-results/2026-2027/q2/documents/transcripts/earningscall.pdf',
     'published_on':'2026-10-23','period':'Q2 FY2027'},
    {'kind':'results','title':'Infosys Q2 FY2027 Financial Results',
     'url':'https://www.infosys.com/investors/reports-filings/quarterly-results/2026-2027/q2/documents/q2-and-h1-fy27-financial-results-auditorsreports.pdf',
     'published_on':'2026-10-23','period':'Q2 FY2027'}
]


def main():
    research_store.init()
    success=0
    for doc in INFY_DOCUMENTS:
        try:
            out=ingest('INFY',**doc)
            print(f'[OK] {out["title"]}: {out["page_count"]} pages, {out["chunk_count"]} passages, cached={out["cached"]}')
            success+=1
        except Exception as exc:
            print(f'[FAILED] {doc["title"]}: {type(exc).__name__}: {exc}')
    print(f'{success}/{len(INFY_DOCUMENTS)} official documents indexed')
    if success==0: raise SystemExit(1)

if __name__=='__main__':main()
