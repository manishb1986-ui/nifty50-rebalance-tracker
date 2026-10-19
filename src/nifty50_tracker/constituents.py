"""Download, validate, store and compare Nifty 50 constituent lists."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from . import config, http

log = logging.getLogger(__name__)

COLUMN_MAP = {
    "Company Name": "company",
    "Industry": "industry",
    "Symbol": "symbol",
    "Series": "series",
    "ISIN Code": "isin",
}
COLUMNS = list(COLUMN_MAP.values())


class FetchError(RuntimeError):
    pass


def parse_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text.lstrip("﻿")))
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise FetchError(f"unexpected CSV format, missing columns: {missing}")
    df = df.rename(columns=COLUMN_MAP)[COLUMNS]
    for c in COLUMNS:
        df[c] = df[c].astype(str).str.strip()
    df = df[df["symbol"].ne("") & df["symbol"].ne("nan")]
    return df.sort_values("symbol").reset_index(drop=True)


def validate(df: pd.DataFrame) -> None:
    n = len(df)
    if abs(n - config.EXPECTED_COUNT) > config.COUNT_TOLERANCE:
        raise FetchError(f"expected ~{config.EXPECTED_COUNT} constituents, got {n}")
    if df["symbol"].duplicated().any():
        raise FetchError("duplicate symbols in constituent list")


def fetch() -> tuple[pd.DataFrame, str]:
    """Return (constituents, source_url). Raises FetchError if every source fails."""
    errors = []
    for url in config.CONSTITUENT_URLS:
        r = http.get(url)
        if r is None:
            errors.append(f"{url}: no response")
            continue
        try:
            df = parse_csv(r.text)
            validate(df)
            log.info("fetched %d constituents from %s", len(df), url)
            return df, url
        except (FetchError, pd.errors.ParserError) as exc:
            errors.append(f"{url}: {exc}")
    raise FetchError("all constituent sources failed: " + "; ".join(errors))


def load(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, dtype=str).fillna("")


def save_snapshot(df: pd.DataFrame, on: date) -> Path:
    config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.SNAPSHOT_DIR / f"nifty50_{on.isoformat()}.csv"
    df.to_csv(path, index=False)
    df.to_csv(config.CURRENT_FILE, index=False)
    return path


@dataclass
class Change:
    action: str        # IN, OUT or RENAME
    symbol: str
    company: str
    isin: str
    old_symbol: str = ""


def diff(old: pd.DataFrame, new: pd.DataFrame) -> list[Change]:
    """Compare two lists by ISIN so a symbol rename is not mistaken for IN + OUT."""
    def key(df: pd.DataFrame) -> pd.Series:
        isin = df["isin"].where(df["isin"].str.len() > 0, "SYM:" + df["symbol"])
        return isin

    old = old.assign(_k=key(old)).set_index("_k")
    new = new.assign(_k=key(new)).set_index("_k")
    changes: list[Change] = []
    for k in sorted(set(new.index) - set(old.index)):
        row = new.loc[k]
        changes.append(Change("IN", row["symbol"], row["company"], row["isin"]))
    for k in sorted(set(old.index) - set(new.index)):
        row = old.loc[k]
        changes.append(Change("OUT", row["symbol"], row["company"], row["isin"]))
    for k in sorted(set(old.index) & set(new.index)):
        if old.loc[k, "symbol"] != new.loc[k, "symbol"]:
            changes.append(Change("RENAME", new.loc[k, "symbol"], new.loc[k, "company"],
                                  new.loc[k, "isin"], old_symbol=old.loc[k, "symbol"]))
    return changes
