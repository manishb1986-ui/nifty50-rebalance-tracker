from datetime import date

import pandas as pd

from nifty50_tracker import announcements, changes, constituents, performance

CSV = """Company Name,Industry,Symbol,Series,ISIN Code
Adani Enterprises Ltd.,Metals & Mining,ADANIENT,EQ,INE423A01024
Wipro Ltd.,Information Technology,WIPRO,EQ,INE075A01022
Old Name Ltd.,Consumer Services,OLDSYM,EQ,INE000X01011
"""


def test_parse_csv_maps_columns():
    df = constituents.parse_csv(CSV)
    assert list(df.columns) == constituents.COLUMNS
    assert df["symbol"].tolist() == ["ADANIENT", "OLDSYM", "WIPRO"]


def test_diff_detects_in_out_and_rename():
    old = constituents.parse_csv(CSV)
    new = old[old["symbol"] != "WIPRO"].copy()
    new.loc[new["symbol"] == "OLDSYM", "symbol"] = "NEWSYM"
    new = pd.concat([new, pd.DataFrame([{"company": "BSE Ltd.", "industry": "Financial Services",
                                         "symbol": "BSE", "series": "EQ", "isin": "INE118H01025"}])])
    got = {(c.action, c.symbol) for c in constituents.diff(old, new)}
    assert got == {("IN", "BSE"), ("OUT", "WIPRO"), ("RENAME", "NEWSYM")}


RELEASE = """NSE Indices Limited
Replacements in indices
A. Replacements on account of semi-annual review of broad market indices:
1) Nifty 50
The following company is being excluded:
Sr. No. Company Name Symbol
1 Wipro Ltd. WIPRO
The following company is being included:
Sr. No. Company Name Symbol
1 BSE Ltd. BSE
2) Nifty Next 50
The following companies are being excluded:
1 Some Co Ltd. SOMECO
These changes shall become effective from September 30, 2026 (close of September 29, 2026).
"""


def test_parse_press_release():
    a = announcements.parse(RELEASE, "u", date(2026, 8, 10))
    assert a.mentions_nifty50
    assert a.effective == date(2026, 9, 30)
    assert a.excluded == [("Wipro Ltd.", "WIPRO")]
    assert a.included == [("BSE Ltd.", "BSE")]


def test_release_without_nifty50_section_is_ignored():
    a = announcements.parse("1) Nifty 500\nThe following company is being included:\n1 X Ltd. X\n")
    assert not a.has_changes and not a.mentions_nifty50


def test_announcement_then_detection_confirms_same_row():
    df = changes.load().iloc[0:0]
    df, added = changes.record_announcement(df, symbol="BSE", company="BSE Ltd.", action="IN",
                                            effective=date(2026, 9, 30), announced=date(2026, 8, 10),
                                            source="pr")
    assert added
    df, added = changes.record_announcement(df, symbol="BSE", company="BSE Ltd.", action="IN",
                                            effective=date(2026, 9, 30), announced=date(2026, 8, 10),
                                            source="pr")
    assert not added
    df = changes.record_detected(df, symbol="BSE", company="BSE Ltd.", action="IN", isin="X",
                                 detected=date(2026, 10, 1), source="list")
    assert len(df) == 1 and df.iloc[0]["status"] == "CONFIRMED"


def _series(start, values):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=[d.date() for d in idx])


def test_compute_trade_open_and_closed():
    stock = _series("2025-01-01", [100 + i for i in range(300)])
    bench = _series("2025-01-01", [1000 + i for i in range(300)])
    eff = date(2025, 1, 6)
    res = performance.compute_trade(stock, bench, eff, today=date(2026, 3, 1))
    assert res["status"] == "CLOSED"
    assert res["entry_date"] == "2025-01-06" and res["entry_price"] == 103
    assert res["exit_date"] <= "2026-01-06"
    assert res["alpha_pct"] is not None and res["return_pct"] > res["nifty_return_pct"]
    res_open = performance.compute_trade(stock, bench, eff, today=date(2025, 6, 1))
    assert res_open["status"] == "OPEN"


def test_compute_trade_pending_before_effective():
    res = performance.compute_trade(pd.Series(dtype=float), pd.Series(dtype=float),
                                    date(2027, 3, 31), today=date(2026, 10, 18))
    assert res["status"] == "PENDING"
