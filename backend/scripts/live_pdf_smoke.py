"""No mocks. Verify 1+ actual NSE attachments already stored in FINN SQLite.

Run after filings_sync. This script fails explicitly if there is no eligible source
or no extracted real PDF, and prints audit links and PDF hash for inspection.
"""
import argparse
import json
from app import database
from app.pdf_priority import candidates, enrich_filings


def main():
    parser=argparse.ArgumentParser(description="Live test actual NSE filing PDFs; no fixtures")
    parser.add_argument("--symbols",help="e.g. INFY,RELIANCE (omit to use whole portfolio)")
    parser.add_argument("--max-files",type=int,default=4)
    parser.add_argument("--sync-first",action="store_true",help="First fetch current genuine NSE records")
    parser.add_argument("--days",type=int,default=14)
    parser.add_argument("--retry-failed",action="store_true")
    parser.add_argument("--force",action="store_true")
    args=parser.parse_args()
    symbols=args.symbols.split(",") if args.symbols else None
    database.init_db()
    if args.sync_first:
        from app.nse_filings import sync_filings
        ingested=sync_filings(days=args.days,symbols=symbols)
        print("NSE source sync:",json.dumps(ingested,indent=2))
    eligible=candidates(symbols=symbols,max_files=args.max_files,
                        retry_failed=args.retry_failed,force=args.force)
    if not eligible:
        print("No unanalysed eligible original NSE PDFs in local database. Check "
              "filings_sync, use --force for previously analysed items, or expand dates/symbols.")
        return 2
    print("Attempting original NSE PDFs:")
    for row in eligible:
        print(row["symbol"],row["score"],row["source_url"])
    result=enrich_filings(symbols=symbols,max_files=args.max_files,
                          retry_failed=args.retry_failed,force=args.force)
    from app.alerts import rebuild_alerts
    result["alerts_rebuilt"]=rebuild_alerts()
    print(json.dumps(result,indent=2,ensure_ascii=False))
    print("PDF cache:",json.dumps(database.pdf_cache_stats()))
    return 0 if result["ok"] and not result["failed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
