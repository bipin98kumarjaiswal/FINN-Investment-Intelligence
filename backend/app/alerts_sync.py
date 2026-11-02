import json
from app.alerts import sync_market_alerts, sync_filing_alerts

if __name__ == "__main__":
    print(json.dumps({"market":sync_market_alerts(),"filings":sync_filing_alerts()},indent=2))
