from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app import database
from app.alerts import sync_market_alerts, sync_filing_alerts, rebuild_alerts
from app.nse_filings import parse_nse_record


def test_price_and_volume_only_use_prior_sessions(tmp_path):
    path=tmp_path/"test.sqlite3"
    database.init_db(path)
    # Recent market-day dates ensure 90-day lookback covers the fixture.
    base=datetime.now(ZoneInfo("Asia/Kolkata")).date()-timedelta(days=25)
    bars=[]
    for i in range(22):
        close=110 if i==21 else 100
        vol=2500 if i==21 else 1000
        bars.append({"trade_date":(base+timedelta(days=i)).isoformat(),
                     "open":100,"high":115,"low":99,"close":close,"volume":vol})
    database.save_prices("INFY",bars,datetime.now(timezone.utc).isoformat(),path)
    result=sync_market_alerts(path)
    assert result["matching_signals"]==2
    # Running twice must never create duplicate notifications.
    assert sync_market_alerts(path)["new_alerts"]==0
    entries=database.list_alerts("2000-01-01T00:00:00+00:00","2100-01-01T00:00:00+00:00",path)
    assert {x["alert_type"] for x in entries}=={"price","volume"}
    assert next(x for x in entries if x["alert_type"]=="volume")["details"]["volume_ratio"]==2.5
    assert next(x for x in entries if x["alert_type"]=="price")["details"]["price_change_pct"]==10.0
    settings=database.get_preferences(path)
    settings["price_change_pct"]=12
    settings["volume_multiple"]=3
    database.update_preferences(settings,path)
    rebuilt=rebuild_alerts(path)
    assert rebuilt["market"]["matching_signals"]==0
    assert database.list_alerts("2000-01-01T00:00:00+00:00","2100-01-01T00:00:00+00:00",path)==[]


def test_material_filing_alert_and_category_preferences(tmp_path):
    path=tmp_path/"test.sqlite3"
    database.init_db(path)
    now=datetime.now(ZoneInfo("Asia/Kolkata"))
    timestamp=now.strftime("%d-%b-%Y %H:%M:%S")
    critical={"symbol":"INFY", "desc":"Change in Management",
              "attchmntText":"CFO has resigned", "an_dt":timestamp,
              "seq_id":"arbitrary-test-record", "attchmntFile":None}
    record=parse_nse_record(critical,"INFY")
    database.save_announcements([record],path)
    assert sync_filing_alerts(path)["new_alerts"]==1
    assert sync_filing_alerts(path)["new_alerts"]==0
    prefs=database.get_preferences(path)
    prefs["categories"]=["results"]
    database.update_preferences(prefs,path)
    rebuild_alerts(path)
    assert database.list_alerts("2000-01-01T00:00:00+00:00","2100-01-01T00:00:00+00:00",path)==[]
