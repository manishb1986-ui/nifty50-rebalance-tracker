"""The change log: data/changes.csv (one row per inclusion/exclusion event).

status:
  ANNOUNCED  - read from an NSE Indices press release, not yet in the official list
  CONFIRMED  - seen in the official constituent list (or both)
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import config

COLUMNS = ["effective_date", "symbol", "company", "action", "status",
           "announced_on", "detected_on", "isin", "source", "notes"]


def load() -> pd.DataFrame:
    if not config.CHANGES_FILE.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(config.CHANGES_FILE, dtype=str).fillna("")
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[COLUMNS]


def save(df: pd.DataFrame) -> None:
    df = df.sort_values(["effective_date", "action", "symbol"], ascending=[False, True, True])
    df.to_csv(config.CHANGES_FILE, index=False)


def _match(df: pd.DataFrame, symbol: str, action: str, around: date, days: int = 90) -> pd.Index:
    same = df[(df["symbol"] == symbol) & (df["action"] == action)]
    hits = []
    for idx, row in same.iterrows():
        try:
            eff = date.fromisoformat(row["effective_date"])
        except ValueError:
            continue
        if abs((eff - around).days) <= days:
            hits.append(idx)
    return pd.Index(hits)


def record_announcement(df: pd.DataFrame, *, symbol: str, company: str, action: str,
                        effective: date, announced: date, source: str) -> tuple[pd.DataFrame, bool]:
    """Add an ANNOUNCED row unless the same event already exists. Returns (df, added)."""
    if len(_match(df, symbol, action, effective, days=10)):
        return df, False
    row = {"effective_date": effective.isoformat(), "symbol": symbol, "company": company,
           "action": action, "status": "ANNOUNCED", "announced_on": announced.isoformat(),
           "detected_on": "", "isin": "", "source": source, "notes": ""}
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True), True


def record_detected(df: pd.DataFrame, *, symbol: str, company: str, action: str, isin: str,
                    detected: date, source: str, notes: str = "") -> pd.DataFrame:
    """Mark a matching announced event CONFIRMED, or add a new CONFIRMED row.

    When no announcement matched, the effective date is approximated by the
    detection date (the official file updates on or just after the effective day).
    """
    hits = _match(df, symbol, action, detected, days=45)
    if len(hits):
        i = hits[0]
        df.loc[i, ["status", "detected_on"]] = ["CONFIRMED", detected.isoformat()]
        if isin:
            df.loc[i, "isin"] = isin
        return df
    row = {"effective_date": detected.isoformat(), "symbol": symbol, "company": company,
           "action": action, "status": "CONFIRMED", "announced_on": "",
           "detected_on": detected.isoformat(), "isin": isin, "source": source,
           "notes": notes or "effective date approximated by detection date"}
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


def recent(df: pd.DataFrame, today: date, days: int = 400) -> pd.DataFrame:
    cutoff = (today - timedelta(days=days)).isoformat()
    return df[df["effective_date"] >= cutoff]
