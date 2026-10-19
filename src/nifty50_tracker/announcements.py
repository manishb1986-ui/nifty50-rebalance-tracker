"""Early warning: NSE Indices press releases (weeks before the change) and news hints.

NSE Indices announces Nifty 50 replacements in a press release titled
"Replacements in indices" (semi-annual reviews are usually announced in
February and August, effective at the end of March and September). Ad-hoc
replacements (mergers, demergers, suspensions) can come at any time.
"""
from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from . import config, http

log = logging.getLogger(__name__)

SYMBOL_RE = r"[A-Z][A-Z0-9&\-]{0,19}"
ROW_RE = re.compile(rf"^\s*\d+\s+(?P<company>.+?)\s+(?P<symbol>{SYMBOL_RE})\s*$")
NIFTY50_HEADING = re.compile(r"^\s*(?:\d+\)|[a-z]\)|\d+\.)?\s*nifty\s*50\s*$", re.I)
NEXT_INDEX_HEADING = re.compile(r"^\s*(?:\d+\)|[a-z]\)|\d+\.)\s*nifty\b", re.I)
EFFECTIVE_RE = re.compile(r"effective\s+from\s+([A-Z][a-z]+\s+\d{1,2},\s*\d{4})", re.I)


@dataclass
class Announcement:
    url: str
    published: date
    effective: date | None = None
    included: list[tuple[str, str]] = field(default_factory=list)  # (company, symbol)
    excluded: list[tuple[str, str]] = field(default_factory=list)
    mentions_nifty50: bool = False

    @property
    def has_changes(self) -> bool:
        return bool(self.included or self.excluded)


def candidate_urls(today: date, lookback: int = config.PRESS_RELEASE_LOOKBACK_DAYS):
    for back in range(lookback + 1):
        d = today - timedelta(days=back)
        for pattern in config.PRESS_RELEASE_PATTERNS:
            for suffix in config.PRESS_RELEASE_SUFFIXES:
                yield d, pattern.format(ddmmyyyy=d.strftime("%d%m%Y"), suffix=suffix)


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse(text: str, url: str = "", published: date | None = None) -> Announcement:
    """Pull Nifty 50 inclusions/exclusions and the effective date from release text."""
    ann = Announcement(url=url, published=published or date.today())
    m = EFFECTIVE_RE.search(text)
    if m:
        try:
            ann.effective = datetime.strptime(re.sub(r"\s+", " ", m.group(1)), "%B %d, %Y").date()
        except ValueError:
            pass

    lines = [ln.strip() for ln in text.splitlines()]
    start = next((i for i, ln in enumerate(lines) if NIFTY50_HEADING.match(ln)), None)
    if start is None:
        ann.mentions_nifty50 = bool(re.search(r"\bnifty\s*50\b(?!\s*(?:0|equal|value|arbitrage))", text, re.I))
        return ann
    ann.mentions_nifty50 = True
    end = next((i for i in range(start + 1, len(lines)) if NEXT_INDEX_HEADING.match(lines[i])), len(lines))

    bucket = None
    for ln in lines[start + 1:end]:
        low = ln.lower()
        if "excluded" in low:
            bucket = ann.excluded
            continue
        if "included" in low:
            bucket = ann.included
            continue
        if bucket is None:
            continue
        row = ROW_RE.match(ln)
        if row and row.group("symbol") not in {"NO", "SR"}:
            bucket.append((row.group("company").strip(), row.group("symbol")))
    return ann


def check_press_releases(today: date, seen: set[str]) -> list[Announcement]:
    """Probe recent press-release URLs; return parsed releases not seen before."""
    found = []
    for published, url in candidate_urls(today):
        if url in seen:
            continue
        r = http.get(url, retries=1)
        if r is None or not r.content.startswith(b"%PDF"):
            continue
        seen.add(url)
        try:
            text = pdf_text(r.content)
        except Exception as exc:  # malformed PDF: still record and flag
            log.warning("could not read %s: %s", url, exc)
            found.append(Announcement(url=url, published=published, mentions_nifty50=True))
            continue
        ann = parse(text, url, published)
        log.info("press release %s: nifty50=%s in=%s out=%s", url, ann.mentions_nifty50,
                 ann.included, ann.excluded)
        if ann.mentions_nifty50:
            found.append(ann)
    return found


@dataclass
class NewsItem:
    title: str
    link: str
    published: datetime


def news_hints(seen: set[str], lookback_days: int = config.NEWS_LOOKBACK_DAYS) -> list[NewsItem]:
    url = ("https://news.google.com/rss/search?q=" + quote(config.NEWS_QUERY)
           + "&hl=en-IN&gl=IN&ceid=IN:en")
    r = http.get(url, retries=1)
    if r is None:
        return []
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    items = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        title = (it.findtext("title") or "").strip()
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if pub < cutoff or link in seen:
            continue
        seen.add(link)
        items.append(NewsItem(title, link, pub))
    return items
