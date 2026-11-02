"""CLI for price refresh; computes latest-day alerts after successful price ingestion."""
import argparse
import json
from app.market_data import PERIODS, sync_prices
from app.alerts import sync_market_alerts


def main():
    parser = argparse.ArgumentParser(description="Sync real NSE market data to SQLite")
    parser.add_argument("--period", choices=PERIODS, default="3mo")
    args = parser.parse_args()
    result = sync_prices(args.period)
    result["market_alerts"] = sync_market_alerts()
    print(json.dumps(result, indent=2))
    if result["failed"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
