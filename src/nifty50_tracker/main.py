"""Command line entry point.

    python -m nifty50_tracker run            # everything (what GitHub Actions runs)
    python -m nifty50_tracker snapshot       # constituent list + diff only
    python -m nifty50_tracker announcements  # press releases only
    python -m nifty50_tracker performance    # strategy table only
    python -m nifty50_tracker nse-participant  # NSE FII/DII/Client/Pro OI + volume files
    python -m nifty50_tracker add-event --symbol BSE --company "BSE Ltd." \
        --action IN --effective 2026-09-30 --source "NSE Indices 10-Aug-2026"
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone

import pandas as pd

from . import announcements, changes, config, constituents, notify, performance, report

log = logging.getLogger("nifty50_tracker")


# ---------- state ----------
def load_state() -> dict:
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text())
    return {"consecutive_failures": 0, "seen_press_releases": [], "seen_news": [],
            "last_success": None, "last_source": None}


def save_state(state: dict) -> None:
    state["seen_news"] = state.get("seen_news", [])[-500:]
    config.STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


# ---------- steps ----------
def step_snapshot(today: date, state: dict, log_df: pd.DataFrame):
    previous = constituents.load(config.CURRENT_FILE)
    try:
        current, source = constituents.fetch()
    except constituents.FetchError as exc:
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        log.error("%s", exc)
        if state["consecutive_failures"] == config.FAILURE_ALERT_THRESHOLD:
            notify.alert("Nifty 50 tracker: constituent download failing",
                         f"{state['consecutive_failures']} runs in a row could not download the "
                         f"official list.\n\nLast error: {exc}\n\nNSE may be blocking the runner; "
                         "see README > Troubleshooting.", ["nifty50", "tracker-error"])
        return previous, "", False, [], log_df

    state.update(consecutive_failures=0, last_success=today.isoformat(), last_source=source)
    run_changes = []
    if previous is not None and len(previous):
        run_changes = constituents.diff(previous, current)
    if run_changes or previous is None or not any(config.SNAPSHOT_DIR.glob("*.csv")):
        constituents.save_snapshot(current, today)       # keep a dated copy only when it changes
    else:
        current.to_csv(config.CURRENT_FILE, index=False)

    for c in run_changes:
        if c.action == "RENAME":
            continue
        log_df = changes.record_detected(log_df, symbol=c.symbol, company=c.company,
                                         action=c.action, isin=c.isin, detected=today,
                                         source="NSE constituent list")
    if run_changes:
        lines = [f"- **{c.action}** `{c.symbol}` – {c.company}"
                 + (f" (renamed from `{c.old_symbol}`)" if c.action == "RENAME" else "")
                 for c in run_changes]
        notify.alert(f"Nifty 50 constituents changed ({today:%d %b %Y})",
                     "The official Nifty 50 list changed:\n\n" + "\n".join(lines)
                     + f"\n\nSource: {source}", ["nifty50", "constituent-change"])
    return current, source, True, run_changes, log_df


def step_announcements(today: date, state: dict, log_df: pd.DataFrame):
    seen = set(state.get("seen_press_releases", []))
    found = announcements.check_press_releases(today, seen)
    state["seen_press_releases"] = sorted(seen)
    for a in found:
        added = []
        eff = a.effective
        for action, rows in (("IN", a.included), ("OUT", a.excluded)):
            for company, symbol in rows:
                if eff is None:
                    continue
                log_df, new = changes.record_announcement(
                    log_df, symbol=symbol, company=company, action=action, effective=eff,
                    announced=a.published, source=a.url)
                if new:
                    added.append(f"- **{action}** `{symbol}` – {company}")
        if a.has_changes:
            body = (f"NSE Indices press release ({a.published:%d %b %Y}) lists Nifty 50 changes, "
                    f"effective **{eff or 'see release'}**:\n\n"
                    + ("\n".join(added) or "(already recorded)")
                    + f"\n\nRelease: {a.url}\n\nStrategy note: entry is planned at the close of the "
                      "effective date; index funds usually trade at the close of the day before.")
            notify.alert(f"Nifty 50 replacement announced – effective {eff or 'TBD'}", body,
                         ["nifty50", "announcement"])
        else:
            notify.alert("NSE Indices release mentions Nifty 50 – check manually",
                         f"A new press release mentions Nifty 50 but the changes could not be "
                         f"parsed automatically.\n\n{a.url}", ["nifty50", "announcement"])
        ann_row = pd.DataFrame([{"published": a.published.isoformat(), "url": a.url,
                                 "effective": a.effective.isoformat() if a.effective else "",
                                 "included": " ".join(s for _, s in a.included),
                                 "excluded": " ".join(s for _, s in a.excluded)}])
        old = pd.read_csv(config.ANNOUNCEMENTS_FILE, dtype=str) if config.ANNOUNCEMENTS_FILE.exists() \
            else pd.DataFrame()
        pd.concat([old, ann_row], ignore_index=True).to_csv(config.ANNOUNCEMENTS_FILE, index=False)

    news_seen = set(state.get("seen_news", []))
    news = announcements.news_hints(news_seen)
    state["seen_news"] = list(news_seen)
    return found, news, log_df


def step_performance(today: date, log_df: pd.DataFrame):
    perf = performance.evaluate(log_df, today)
    if not perf.empty:
        perf.to_csv(config.PERFORMANCE_FILE, index=False)
    return perf, performance.summary(perf)


# ---------- commands ----------
def cmd_run(args) -> int:
    today = args.today or date.today()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    log_df = changes.load()

    current, source, ok, run_changes, log_df = (None, "", False, [], log_df)
    if args.command in ("run", "snapshot"):
        current, source, ok, run_changes, log_df = step_snapshot(today, state, log_df)
    found, news = [], []
    if args.command in ("run", "announcements"):
        found, news, log_df = step_announcements(today, state, log_df)
    changes.save(log_df)
    perf, stats = pd.DataFrame(), {}
    if args.command in ("run", "performance"):
        perf, stats = step_performance(today, log_df)
    save_state(state)

    if current is None:
        current = constituents.load(config.CURRENT_FILE)
    text = report.build(now=datetime.now(timezone.utc), constituents=current, source=source,
                        fetch_ok=ok, changes=changes.load(), run_changes=run_changes,
                        announcements=found, news=news, perf=perf, stats=stats)
    report.write(text)
    log.info("report written to %s", config.REPORT_FILE)
    return 0


def cmd_add_event(args) -> int:
    df = changes.load()
    df, added = changes.record_announcement(
        df, symbol=args.symbol.upper(), company=args.company, action=args.action,
        effective=args.effective, announced=args.announced or args.effective, source=args.source)
    if args.confirmed:
        df = changes.record_detected(df, symbol=args.symbol.upper(), company=args.company,
                                     action=args.action, isin="", detected=args.effective,
                                     source=args.source, notes="added manually")
    changes.save(df)
    print("added" if added else "already present")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="nifty50_tracker")
    sub = p.add_subparsers(dest="command")
    for name in ("run", "snapshot", "announcements", "performance"):
        sp = sub.add_parser(name)
        sp.add_argument("--today", type=date.fromisoformat, help="override date (YYYY-MM-DD)")
        sp.set_defaults(func=cmd_run)
    np_ = sub.add_parser("nse-participant", help="download NSE participant OI/volume files")
    np_.add_argument("--today", type=date.fromisoformat)
    np_.set_defaults(func=lambda a: __import__("nifty50_tracker.nse_participant",
                                               fromlist=["run"]).run(a.today))
    ae = sub.add_parser("add-event", help="add a historical or known event")
    ae.add_argument("--symbol", required=True)
    ae.add_argument("--company", required=True)
    ae.add_argument("--action", choices=["IN", "OUT"], required=True)
    ae.add_argument("--effective", type=date.fromisoformat, required=True)
    ae.add_argument("--announced", type=date.fromisoformat)
    ae.add_argument("--source", default="manual")
    ae.add_argument("--confirmed", action="store_true", help="mark as CONFIRMED")
    ae.set_defaults(func=cmd_add_event)
    args = p.parse_args(argv)
    if not args.command:
        args = p.parse_args(["run"] + (argv or []))
    return args.func(args)
