"""Alerts: GitHub issue (works out of the box in Actions) and optional Telegram."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)


def github_issue(title: str, body: str, labels: list[str] | None = None) -> bool:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not token or not repo:
        log.info("GitHub issue skipped (no GITHUB_TOKEN/GITHUB_REPOSITORY): %s", title)
        return False
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.post(url, headers=headers,
                      json={"title": title, "body": body, "labels": labels or []}, timeout=30)
    if r.status_code == 422 and labels:  # label problem: retry without labels
        r = requests.post(url, headers=headers, json={"title": title, "body": body}, timeout=30)
    if r.status_code >= 300:
        log.warning("GitHub issue failed: %s %s", r.status_code, r.text[:200])
        return False
    return True


def telegram(text: str) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
                      timeout=30)
    if r.status_code >= 300:
        log.warning("Telegram failed: %s %s", r.status_code, r.text[:200])
        return False
    return True


def alert(title: str, body: str, labels: list[str] | None = None) -> None:
    github_issue(title, body, labels)
    telegram(f"{title}\n\n{body}")
