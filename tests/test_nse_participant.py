import json
from datetime import date
from pathlib import Path

from nifty50_tracker import nse_participant as npt

FIX = Path(__file__).parent / "fixtures"


def test_parse_real_nse_file():
    d = npt.parse((FIX / "fao_participant_oi_19102026.csv").read_text())
    assert d["FII"]["fut"] == {"long": 36661, "short": 316591}
    assert d["Client"]["put"] == {"long": 1939753, "short": 2667176}


def test_run_builds_changes_and_flows(tmp_path, monkeypatch):
    nse = tmp_path / "nse"
    nse.mkdir()
    for f in FIX.glob("*.csv"):
        (nse / f.name).write_text(f.read_text())
    monkeypatch.setattr(npt, "NSE_DIR", nse)
    monkeypatch.setattr(npt, "LATEST_JSON", nse / "participant_latest.json")
    monkeypatch.setattr(npt.http, "get", lambda *a, **k: None)      # offline
    monkeypatch.setattr(npt.notify, "telegram", lambda text: True)
    assert npt.run(date(2026, 10, 20)) == 0                          # Tue holiday -> falls back
    out = json.loads((nse / "participant_latest.json").read_text())
    assert out["date"] == "2026-10-19" and out["prev_date"] == "2026-10-16"
    assert out["positions"]["FII"]["fut"] == [36661, -3305, 316591, 3626]
    assert out["positions"]["Client"]["fut"] == [281397, 4779, 50606, -6098]
    assert out["flows"]["FII"]["index_fut"] == [9464, 16395, -6931]
    assert out["checks"]["futures_net_sum"] == 0


def test_telegram_text_has_all_four_groups():
    pos = {
        "FII": {"fut": [38700, 8051, 123930, 2332]},
        "DII": {"fut": [100, 5, 50, None]},
        "Client": {"fut": [146754, -17058, 76915, 7269]},
        "Pro": {"fut": [10, -1, 20, 2]},
    }
    lines = npt.telegram_text(date(2026, 11, 25), pos).splitlines()
    assert lines[0] == "NSE participant OI 25 Nov 2026"
    assert lines[1] == "FII futures: long 38,700 (+8,051), short 123,930 (+2,332), net -85,230"
    assert lines[2] == "DII futures: long 100 (+5), short 50 (n/a), net +50"
    assert lines[3] == "Retail futures: long 146,754 (-17,058), short 76,915 (+7,269), net +69,839"
    assert lines[4] == "PRO futures: long 10 (-1), short 20 (+2), net -10"
