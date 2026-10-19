"""Back-test / live-track the inclusion strategy.

Rule (from the satellite strategy): buy each newly included stock at the close
of its inclusion (effective) date, hold 12 months, exit. Exclusions are tracked
too, for information, with the same window.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from . import config

log = logging.getLogger(__name__)


def yahoo_symbol(nse_symbol: str) -> str:
    return nse_symbol.strip().upper() + config.YAHOO_SUFFIX


def _as_date_index(s: pd.Series) -> pd.Series:
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s = s.copy()
    s.index = [d.date() for d in idx]
    return s.dropna().sort_index()


def history(ticker: str, start: date, end: date) -> pd.Series:
    """Daily adjusted closes from Yahoo Finance (empty Series on failure)."""
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(start=start.isoformat(),
                                       end=(end + timedelta(days=1)).isoformat(),
                                       auto_adjust=True)
        if df is None or df.empty:
            return pd.Series(dtype=float)
        return _as_date_index(df["Close"])
    except Exception as exc:
        log.warning("price download failed for %s: %s", ticker, exc)
        return pd.Series(dtype=float)


def compute_trade(stock: pd.Series, bench: pd.Series, effective: date, today: date,
                  hold_days: int = config.HOLD_DAYS) -> dict:
    """Pure calculation on date-indexed close series."""
    exit_target = effective + timedelta(days=hold_days)
    out = {"entry_date": "", "entry_price": None, "exit_date": "", "exit_price": None,
           "days_held": 0, "return_pct": None, "nifty_return_pct": None, "alpha_pct": None,
           "status": "PENDING" if today < effective else "NO DATA",
           "planned_exit": exit_target.isoformat()}
    s = stock[[d >= effective for d in stock.index]] if len(stock) else stock
    if s.empty:
        return out
    s = s[[d <= exit_target for d in s.index]]
    if s.empty:
        return out
    entry_d, exit_d = s.index[0], s.index[-1]
    entry, exit_ = float(s.iloc[0]), float(s.iloc[-1])
    out.update(entry_date=entry_d.isoformat(), entry_price=round(entry, 2),
               exit_date=exit_d.isoformat(), exit_price=round(exit_, 2),
               days_held=(exit_d - entry_d).days,
               return_pct=round((exit_ / entry - 1) * 100, 2),
               status="CLOSED" if today >= exit_target else "OPEN")
    b_entry = bench[[d >= entry_d for d in bench.index]] if len(bench) else bench
    b_exit = bench[[d <= exit_d for d in bench.index]] if len(bench) else bench
    if len(b_entry) and len(b_exit):
        b_ret = (float(b_exit.iloc[-1]) / float(b_entry.iloc[0]) - 1) * 100
        out["nifty_return_pct"] = round(b_ret, 2)
        out["alpha_pct"] = round(out["return_pct"] - b_ret, 2)
    return out


def evaluate(changes: pd.DataFrame, today: date) -> pd.DataFrame:
    events = changes[changes["action"].isin(["IN", "OUT"]) & changes["effective_date"].ne("")]
    if events.empty:
        return pd.DataFrame()
    starts = [date.fromisoformat(d) for d in events["effective_date"]]
    first = min(starts) - timedelta(days=7)
    last = min(today, max(starts) + timedelta(days=config.HOLD_DAYS + 7))
    bench = history(config.BENCHMARK_TICKER, first, last)
    rows = []
    for (_, ev), eff in zip(events.iterrows(), starts):
        stock = pd.Series(dtype=float)
        if today >= eff:
            stock = history(yahoo_symbol(ev["symbol"]), eff - timedelta(days=7),
                            min(today, eff + timedelta(days=config.HOLD_DAYS + 7)))
        res = compute_trade(stock, bench, eff, today)
        rows.append({"symbol": ev["symbol"], "company": ev["company"], "action": ev["action"],
                     "effective_date": ev["effective_date"], **res})
    return pd.DataFrame(rows)


def summary(perf: pd.DataFrame) -> dict:
    if perf.empty:
        return {}
    ins = perf[(perf["action"] == "IN") & perf["return_pct"].notna()]
    closed = ins[ins["status"] == "CLOSED"]
    def stats(df: pd.DataFrame) -> dict:
        if df.empty:
            return {"trades": 0}
        return {"trades": int(len(df)),
                "win_rate_pct": round((df["return_pct"] > 0).mean() * 100, 1),
                "avg_return_pct": round(df["return_pct"].mean(), 2),
                "avg_alpha_pct": round(df["alpha_pct"].dropna().mean(), 2)
                if df["alpha_pct"].notna().any() else None}
    return {"closed": stats(closed), "all_inclusions": stats(ins)}
