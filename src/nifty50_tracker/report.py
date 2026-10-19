"""Markdown report written to reports/latest.md on every run."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from . import config


def _table(df: pd.DataFrame, cols: list[str]) -> str:
    if df.empty:
        return "_None._\n"
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = ""
    for _, r in df.iterrows():
        vals = []
        for c in cols:
            v = r.get(c, "")
            vals.append("" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
        body += "| " + " | ".join(vals) + " |\n"
    return head + body


def build(*, now: datetime, constituents: pd.DataFrame | None, source: str, fetch_ok: bool,
          changes: pd.DataFrame, run_changes: list, announcements: list, news: list,
          perf: pd.DataFrame, stats: dict) -> str:
    md = [f"# Nifty 50 Rebalance Tracker\n",
          f"_Updated {now:%Y-%m-%d %H:%M} UTC._\n"]

    md.append("## Status\n")
    if fetch_ok and constituents is not None:
        md.append(f"- Official list: **{len(constituents)} constituents** from `{source}`\n")
    else:
        md.append("- ⚠️ Official list could not be downloaded this run; previous snapshot kept.\n")
    md.append(f"- Changes detected this run: **{len(run_changes)}**\n")
    md.append(f"- New press releases mentioning Nifty 50: **{len(announcements)}**\n\n")

    if run_changes:
        md.append("## Detected this run\n")
        for c in run_changes:
            extra = f" (was {c.old_symbol})" if c.action == "RENAME" else ""
            md.append(f"- **{c.action}** {c.symbol} – {c.company}{extra}\n")
        md.append("\n")

    if announcements:
        md.append("## New NSE Indices press releases\n")
        for a in announcements:
            md.append(f"- [{a.published:%d %b %Y}]({a.url}) – effective "
                      f"{a.effective or 'see release'}; IN: "
                      f"{', '.join(s for _, s in a.included) or '–'}; OUT: "
                      f"{', '.join(s for _, s in a.excluded) or '–'}\n")
        md.append("\n")

    md.append("## Change log (latest first)\n")
    md.append(_table(changes.head(30), ["effective_date", "action", "symbol", "company",
                                        "status", "announced_on", "source"]))

    md.append("\n## Strategy: buy on inclusion, hold 12 months\n")
    closed = stats.get("closed", {}) if stats else {}
    alln = stats.get("all_inclusions", {}) if stats else {}
    if closed.get("trades"):
        md.append(f"- Closed trades: **{closed['trades']}**, win rate **{closed['win_rate_pct']}%**, "
                  f"avg return **{closed['avg_return_pct']}%**, avg alpha vs Nifty 50 "
                  f"**{closed['avg_alpha_pct']}%**\n")
    if alln.get("trades"):
        md.append(f"- All inclusions incl. open: {alln['trades']} trades, avg return "
                  f"{alln['avg_return_pct']}%, avg alpha {alln['avg_alpha_pct']}%\n")
    md.append("\n")
    md.append(_table(perf, ["action", "symbol", "effective_date", "entry_date", "entry_price",
                            "exit_date", "exit_price", "return_pct", "nifty_return_pct",
                            "alpha_pct", "status", "planned_exit"]) if not perf.empty else "_No priced events yet._\n")

    if news:
        md.append("\n## News hints (unverified, for awareness only)\n")
        for n in news[:15]:
            md.append(f"- {n.published:%d %b} – [{n.title}]({n.link})\n")

    md.append("\n---\nData: NSE `ind_nifty50list.csv`, NSE Indices press releases, Yahoo Finance prices. "
              "Educational use only; not investment advice.\n")
    return "".join(md)


def write(text: str) -> None:
    config.REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.REPORT_FILE.write_text(text, encoding="utf-8")
