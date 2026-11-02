"""CLI: python -m app.filings_sync --days 7 [--symbols INFY,RELIANCE]"""
import argparse
import json
from app.nse_filings import sync_filings
from app.alerts import sync_filing_alerts


def main():
    parser = argparse.ArgumentParser(description="Sync real NSE corporate filings")
    parser.add_argument("--days",type=int,default=7)
    parser.add_argument("--symbols",help="Comma separated subset, e.g. INFY,RELIANCE")
    parser.add_argument("--analyze-important",action="store_true",
                        help="Only inspect PDFs when stage-one score >=40")
    parser.add_argument("--max-pdfs",type=int,default=10,
                        help="Maximum PDF filings to analyse in this run (default: 10)")
    args = parser.parse_args()
    selected = args.symbols.split(",") if args.symbols else None
    result = sync_filings(days=args.days,symbols=selected)
    if args.analyze_important:
        from app.pdf_priority import enrich_filings
        from app.alerts import rebuild_alerts
        result["pdf_analysis"] = enrich_filings(symbols=selected,max_files=args.max_pdfs)
        result["alerts_rebuilt"] = rebuild_alerts()
    else:
        result["filing_alerts"] = sync_filing_alerts()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["failed"] or (args.analyze_important and result["pdf_analysis"]["failed"]):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
