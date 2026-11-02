import pandas as pd
from app import database
from app.market_data import rows_from_frame,sync_prices
from app.portfolio import PORTFOLIO


def test_invalid_bar_skipped():
    frame=pd.DataFrame({"Open":[100,101],"High":[105,106],"Low":[99,100],
                        "Close":[103,None],"Volume":[125000,126000]},
                        index=pd.to_datetime(["2026-10-29","2026-10-30"]))
    assert len(rows_from_frame(frame))==1


def test_phase1_price_sync_still_works(tmp_path):
    path=tmp_path/"phase1.sqlite3"
    frame=pd.DataFrame({"Open":[100],"High":[105],"Low":[99],
                        "Close":[103],"Volume":[125000]},
                        index=pd.to_datetime(["2026-10-29"]))
    download=pd.concat({"INFY.NS":frame},axis=1)
    def mocked_download(**kwargs): return download
    result=sync_prices("3mo",path,mocked_download,[PORTFOLIO[3],PORTFOLIO[0]])
    assert result["ok"]==1 and result["failed"]==1
    assert result["rows_saved"]==1
    assert database.price_history("INFY",30,path)[0]["volume"]==125000
    sync_prices("3mo",path,mocked_download,[PORTFOLIO[3]])
    assert len(database.price_history("INFY",30,path))==1
