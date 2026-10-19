"""Download NSE participant-wise open interest and trading volume every evening.

Saves the official CSVs to data/nse/ and writes data/nse/participant_latest.json
with long/short positions, day changes (latest file minus the previous trading
day's file) and today's buy/sell flows for FII, DII, Client (retail) and Pro.

    python -m nifty50_tracker nse-participant
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config, http, notify

log = logging.getLogger(__name__)

NSE_DIR = config.DATA_DIR / "nse"
LATEST_JSON = NSE_DIR / "participant_latest.json"
OI_URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d}.csv"
VOL_URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_vol_{d}.csv"
PARTICIPANTS = ["Client", "DII", "FII", "Pro"]
IST = timezone(timedelta(hours=5, minutes=30))

# CSV column -> (leg, side)
COLS = {
    "Future Index Long": ("fut", "long"), "Future Index Short": ("fut", "short"),
    "Option Index Call Long": ("call", "long"), "Option Index Call Short": ("call", "short"),
    "Option Index Put Long": ("put", "long"), "Option Index Put Short": ("put", "short"),
    "Future Stock Long": ("stock_fut", "long"), "Future Stock Short": ("stock_fut", "short"),
}


def ddmmyyyy(d: date) -> str:
    return d.strftime("%d%m%Y")


def parse(text: str) -> dict[str, dict[str, dict[str, int]]]:
    """Return {participant: {leg: {"long": n, "short": n}}} from an NSE participant CSV."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    start = next(i for i, ln in enumerate(lines) if ln.lower().startswith("client type"))
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    out: dict[str, dict[str, dict[str, int]]] = {}
    for row in reader:
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        who = row.get("Client Type", "")
        if who not in PARTICIPANTS + ["TOTAL"]:
            continue
        legs: dict[str, dict[str, int]] = {}
        for col, (leg, side) in COLS.items():
            legs.setdefault(leg, {})[side] = int(float(row[col].replace(",", "")))
        out[who] = legs
    missing = [p for p in PARTICIPANTS if p not in out]
    if missing:
        raise ValueError(f"participant rows missing: {missing}")
    return out


def _local(kind: str, d: date) -> Path:
    return NSE_DIR / f"fao_participant_{kind}_{ddmmyyyy(d)}.csv"


def get_file(kind: str, d: date) -> str | None:
    """Return CSV text for a date, from the local copy or NSE. Saves new downloads."""
    path = _local(kind, d)
    if path.exists():
        return path.read_text(encoding="utf-8")
    url = (OI_URL if kind == "oi" else VOL_URL).format(d=ddmmyyyy(d))
    r = http.get(url, retries=2)
    if r is None or "Client Type" not in r.text:
        return None
    NSE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(r.text, encoding="utf-8")
    log.info("downloaded %s", url)
    return r.text


def find_latest(kind: str, start: date, lookback: int = 10) -> tuple[date, str] | None:
    for back in range(lookback + 1):
        d = start - timedelta(days=back)
        if d.weekday() >= 5:  # Saturday/Sunday
            continue
        text = get_file(kind, d)
        if text:
            return d, text
    return None


def build(latest: dict, prev: dict | None, flows: dict | None) -> dict:
    positions = {}
    for who in PARTICIPANTS:
        positions[who] = {}
        for leg, sides in latest[who].items():
            L, S = sides["long"], sides["short"]
            if prev:
                pL, pS = prev[who][leg]["long"], prev[who][leg]["short"]
                positions[who][leg] = [L, L - pL, S, S - pS]
            else:
                positions[who][leg] = [L, None, S, None]
    flow_out = None
    if flows:
        flow_out = {}
        for who in PARTICIPANTS:
            f = flows[who]
            flow_out[who] = {
                "index_fut": [f["fut"]["long"], f["fut"]["short"], f["fut"]["long"] - f["fut"]["short"]],
                "call_net": f["call"]["long"] - f["call"]["short"],
                "put_net": f["put"]["long"] - f["put"]["short"],
                "stock_fut_net": f["stock_fut"]["long"] - f["stock_fut"]["short"],
            }
    checks = {
        "futures_net_sum": sum(latest[w]["fut"]["long"] - latest[w]["fut"]["short"] for w in PARTICIPANTS),
        "call_long_minus_short": sum(latest[w]["call"]["long"] - latest[w]["call"]["short"] for w in PARTICIPANTS),
        "put_long_minus_short": sum(latest[w]["put"]["long"] - latest[w]["put"]["short"] for w in PARTICIPANTS),
    }
    return {"positions": positions, "flows": flow_out, "checks": checks}


def run(today: date | None = None) -> int:
    today = today or datetime.now(IST).date()
    found = find_latest("oi", today)
    if not found:
        log.warning("no participant OI file found in the last 10 days")
        return 0
    d_latest, text = found
    prev_found = find_latest("oi", d_latest - timedelta(days=1))
    latest = parse(text)
    prev = parse(prev_found[1]) if prev_found else None
    vol_text = get_file("vol", d_latest)
    flows = parse(vol_text) if vol_text else None

    old = json.loads(LATEST_JSON.read_text()) if LATEST_JSON.exists() else {}
    result = {
        "date": d_latest.isoformat(),
        "prev_date": prev_found[0].isoformat() if prev_found else None,
        "generated_at": datetime.now(IST).isoformat(timespec="minutes"),
        "source_oi": OI_URL.format(d=ddmmyyyy(d_latest)),
        "source_vol": VOL_URL.format(d=ddmmyyyy(d_latest)) if flows else None,
        "note": "Contracts. positions[leg] = [long, long_change, short, short_change]; "
                "Client = retail. All NSE index derivatives combined (no SENSEX).",
        **build(latest, prev, flows),
    }
    if abs(result["checks"]["futures_net_sum"]) > 2:
        log.warning("futures nets do not balance: %s", result["checks"])
    NSE_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("participant data for %s written to %s", d_latest, LATEST_JSON)

    if old.get("date") != result["date"] or (old.get("flows") is None and result["flows"]):
        fii = result["positions"]["FII"]["fut"]
        cli = result["positions"]["Client"]["fut"]
        def chg(x):
            return "n/a" if x is None else f"{x:+,}"
        notify.telegram(
            f"NSE participant OI {d_latest:%d %b %Y}\n"
            f"FII futures: long {fii[0]:,} ({chg(fii[1])}), short {fii[2]:,} ({chg(fii[3])}), "
            f"net {fii[0] - fii[2]:+,}\n"
            f"Retail futures: long {cli[0]:,} ({chg(cli[1])}), short {cli[2]:,} ({chg(cli[3])}), "
            f"net {cli[0] - cli[2]:+,}")
    return 0
