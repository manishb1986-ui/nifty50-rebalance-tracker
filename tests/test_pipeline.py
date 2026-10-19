"""End-to-end run with all network calls replaced by fakes."""
from datetime import date

import pandas as pd

from nifty50_tracker import announcements, config, constituents, main, notify, performance


def _list(symbols):
    rows = [{"company": f"{s} Ltd.", "industry": "X", "symbol": s, "series": "EQ",
             "isin": f"INE{s:0<9}"[:12]} for s in symbols]
    return pd.DataFrame(rows)[constituents.COLUMNS]


def test_two_runs_detect_change(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(config, "CURRENT_FILE", tmp_path / "current.csv")
    monkeypatch.setattr(config, "CHANGES_FILE", tmp_path / "changes.csv")
    monkeypatch.setattr(config, "ANNOUNCEMENTS_FILE", tmp_path / "ann.csv")
    monkeypatch.setattr(config, "PERFORMANCE_FILE", tmp_path / "perf.csv")
    monkeypatch.setattr(config, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(config, "REPORT_FILE", tmp_path / "latest.md")
    monkeypatch.setattr(announcements, "check_press_releases", lambda today, seen: [])
    monkeypatch.setattr(announcements, "news_hints", lambda seen: [])
    monkeypatch.setattr(performance, "history", lambda t, s, e: pd.Series(dtype=float))
    alerts = []
    monkeypatch.setattr(notify, "alert", lambda title, body, labels=None: alerts.append(title))

    base = [f"S{i:02d}" for i in range(49)] + ["WIPRO"]
    lists = iter([(_list(base), "fake"), (_list(base[:-1] + ["BSE"]), "fake")])
    monkeypatch.setattr(constituents, "fetch", lambda: next(lists))

    assert main.main(["run", "--today", "2026-09-29"]) == 0
    assert alerts == []                      # first run = baseline only
    assert main.main(["run", "--today", "2026-09-30"]) == 0
    assert len(alerts) == 1 and "changed" in alerts[0]
    log = pd.read_csv(config.CHANGES_FILE)
    assert set(zip(log.action, log.symbol)) == {("IN", "BSE"), ("OUT", "WIPRO")}
    assert "BSE" in (tmp_path / "latest.md").read_text()
