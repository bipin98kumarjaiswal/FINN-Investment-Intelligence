"""A minimal connectivity smoke test; results are printed, never hard-coded."""
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.nse_filings import LANDING, ENDPOINT, HEADERS, response_records, FilingSourceError


def main():
    with requests.Session() as session:
        session.headers.update(HEADERS)
        try:
            page = session.get(LANDING,timeout=15)
            page.raise_for_status()
            print(f"NSE website: HTTP {page.status_code}")
            today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
            start = today - timedelta(days=7)
            response = session.get(ENDPOINT, params={
                "index":"equities", "symbol":"INFY",
                "from_date":start.strftime("%d-%m-%Y"),
                "to_date":today.strftime("%d-%m-%Y")},timeout=15)
            items = response_records(response)
            matching = [x for x in items if isinstance(x,dict) and x.get("symbol")=="INFY"]
            print(f"NSE API: HTTP {response.status_code}; returned {len(items)} rows; INFY matched {len(matching)}")
            if matching:
                top = matching[0]
                print(f"Sample (exchange metadata): {top.get('an_dt')} | {top.get('desc')} | {top.get('attchmntFile')}")
            print("This smoke test does not store any data. Run app.filings_sync for ingestion.")
        except (requests.RequestException,FilingSourceError) as exc:
            print(f"NSE access FAILED: {type(exc).__name__}: {exc}")
            raise SystemExit(1)

if __name__ == "__main__":
    main()
