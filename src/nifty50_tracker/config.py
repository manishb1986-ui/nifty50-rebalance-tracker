"""Paths, data sources and strategy settings. Edit here to customise."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
CURRENT_FILE = DATA_DIR / "current_nifty50.csv"
CHANGES_FILE = DATA_DIR / "changes.csv"
ANNOUNCEMENTS_FILE = DATA_DIR / "announcements.csv"
PERFORMANCE_FILE = DATA_DIR / "performance.csv"
STATE_FILE = DATA_DIR / "state.json"
REPORT_FILE = ROOT / "reports" / "latest.md"

# Official constituent list (tried in order).
CONSTITUENT_URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
]
EXPECTED_COUNT = 50          # Nifty 50 always has 50 members
COUNT_TOLERANCE = 2          # accept 48-52 rows (temporary corporate actions)

# NSE Indices press releases follow this naming pattern
# (e.g. ind_prs10082026.pdf = 10 Aug 2026 "Replacements in indices").
PRESS_RELEASE_PATTERNS = [
    "https://niftyindices.com/Press_Release/ind_prs{ddmmyyyy}{suffix}.pdf",
]
PRESS_RELEASE_SUFFIXES = ["", "_1", "_2", "_3"]
PRESS_RELEASE_LOOKBACK_DAYS = 7

# News hints (Google News RSS). Shown in the report only; never opens issues.
NEWS_QUERY = '"Nifty 50" (inclusion OR exclusion OR rejig OR replaces OR reshuffle)'
NEWS_LOOKBACK_DAYS = 3

# Strategy: buy on the inclusion (effective) date, hold 12 months, exit.
HOLD_DAYS = 365
BENCHMARK_TICKER = "^NSEI"   # Nifty 50 on Yahoo Finance
YAHOO_SUFFIX = ".NS"

# Open a GitHub issue after this many consecutive failed constituent downloads.
FAILURE_ALERT_THRESHOLD = 3

HTTP_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
