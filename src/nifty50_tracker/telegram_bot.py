"""Telegram commands, polled by GitHub Actions (no server needed).

Every run reads new messages sent to your bot, answers them, then acknowledges
them so they are not processed twice. Only the chat in TELEGRAM_CHAT_ID is
answered; messages from anyone else are ignored.

Commands
  /status   current Nifty 50 list size, last update, last changes
  /changes  last 10 inclusion/exclusion events
  /perf     strategy table (buy on inclusion, hold 12 months)
  /list     all 50 current symbols
  /run      run the full tracker now and reply with the result
  /help     this list
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date

import pandas as pd
import requests

from . import changes, config, constituents

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, **params) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = requests.post(API.format(token=token, method=method), json=params, timeout=40)
    r.raise_for_status()
    return r.json()


def send(chat_id: str | int, text: str) -> None:
    for i in range(0, len(text), 4000):  # Telegram limit is 4096 chars
        _call("sendMessage", chat_id=chat_id, text=text[i:i + 4000],
              disable_web_page_preview=True)


# ---------- command handlers ----------
def h_status() -> str:
    cur = constituents.load(config.CURRENT_FILE)
    state = json.loads(config.STATE_FILE.read_text()) if config.STATE_FILE.exists() else {}
    log_df = changes.load()
    last = log_df.head(4)
    lines = ["Nifty 50 tracker status",
             f"Constituents: {len(cur) if cur is not None else 'not downloaded yet'}",
             f"Last successful download: {state.get('last_success') or 'never'}",
             f"Failed downloads in a row: {state.get('consecutive_failures', 0)}",
             "", "Latest events:"]
    lines += [f"{r.effective_date} {r.action:<3} {r.symbol} ({r.status})" for r in last.itertuples()] \
        or ["none"]
    return "\n".join(lines)


def h_changes() -> str:
    df = changes.load().head(10)
    if df.empty:
        return "No events recorded yet."
    return "Last events (effective date, action, symbol, status):\n" + "\n".join(
        f"{r.effective_date}  {r.action:<3}  {r.symbol} – {r.company} [{r.status}]"
        for r in df.itertuples())


def h_perf() -> str:
    if not config.PERFORMANCE_FILE.exists():
        return "No performance data yet. Send /run first."
    df = pd.read_csv(config.PERFORMANCE_FILE)
    df = df[df["action"] == "IN"]
    if df.empty:
        return "No inclusion trades priced yet."
    lines = ["Buy on inclusion, hold 12 months:"]
    for r in df.itertuples():
        ret = "n/a" if pd.isna(r.return_pct) else f"{r.return_pct:+.1f}%"
        alpha = "n/a" if pd.isna(r.alpha_pct) else f"{r.alpha_pct:+.1f}%"
        lines.append(f"{r.symbol}: {ret} (vs Nifty {alpha}) {r.status}, exit {r.planned_exit}")
    closed = df[(df["status"] == "CLOSED") & df["return_pct"].notna()]
    if len(closed):
        lines.append(f"\nClosed: {len(closed)} trades, win rate "
                     f"{(closed['return_pct'] > 0).mean() * 100:.0f}%, avg "
                     f"{closed['return_pct'].mean():+.1f}%")
    return "\n".join(lines)


def h_list() -> str:
    cur = constituents.load(config.CURRENT_FILE)
    if cur is None:
        return "List not downloaded yet. Send /run."
    return f"Nifty 50 ({len(cur)}):\n" + ", ".join(cur["symbol"].tolist())


def h_run() -> str:
    from .main import main as tracker_main
    tracker_main(["run"])
    return "Tracker run finished.\n\n" + h_status()


def h_help() -> str:
    return __doc__.split("Commands", 1)[1].strip()


HANDLERS = {"/status": h_status, "/changes": h_changes, "/perf": h_perf, "/list": h_list,
            "/run": h_run, "/help": h_help, "/start": h_help}


def poll() -> int:
    """Answer pending commands once, then acknowledge them."""
    allowed = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    updates = _call("getUpdates", timeout=0).get("result", [])
    if not updates:
        log.info("no new Telegram messages")
        return 0
    for u in updates:
        msg = u.get("message") or u.get("edited_message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip().split()
        if not text or chat_id != allowed:
            if chat_id and chat_id != allowed:
                log.warning("ignored message from unauthorised chat %s", chat_id)
            continue
        cmd = text[0].split("@")[0].lower()
        handler = HANDLERS.get(cmd)
        try:
            reply = handler() if handler else f"Unknown command {cmd}.\n\n{h_help()}"
        except Exception as exc:  # never leave the user without an answer
            log.exception("command %s failed", cmd)
            reply = f"{cmd} failed: {exc}"
        send(chat_id, reply)
    _call("getUpdates", offset=updates[-1]["update_id"] + 1, timeout=0)  # acknowledge
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
        log.error("set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return 1
    return poll()


if __name__ == "__main__":
    raise SystemExit(main())
