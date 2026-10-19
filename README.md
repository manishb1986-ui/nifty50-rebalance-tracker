# Nifty 50 Rebalance Tracker

Tracks which stocks **enter (IN)** and **leave (OUT)** the Nifty 50, alerts you on
GitHub and Telegram, and tracks the satellite strategy **"buy the newly included
stock on its inclusion date, hold 12 months, exit"** against the Nifty 50.

Runs free on GitHub Actions. No server needed.

## What it does

| Step | When | How |
|---|---|---|
| 1. Early warning | Weekdays 20:10 IST | Checks NSE Indices press releases ("Replacements in indices") from the last 7 days and reads the Nifty 50 *included / excluded* tables and the effective date. Semi-annual reviews are usually announced in Feb and Aug, about 4–6 weeks before the change. |
| 2. Confirmation | Weekdays 20:10 IST | Downloads the official `ind_nifty50list.csv`, compares it with yesterday's list by ISIN (so a symbol rename is not counted as IN + OUT) and records every change. |
| 3. Strategy tracking | Weekdays 20:10 IST | For every IN/OUT event: entry at the close of the effective date, exit 365 days later, return vs Nifty 50 (alpha), win rate. Prices from Yahoo Finance. |
| 4. Alerts | On any change | Opens a GitHub issue (you get an email) and sends a Telegram message. |
| 5. Telegram commands | Every 30 min, 07:30–22:00 IST | Answers `/status`, `/changes`, `/perf`, `/list`, `/run`, `/help`. |

Outputs (committed back to the repo on every run):

- `data/changes.csv` – the event log (`ANNOUNCED` → `CONFIRMED`)
- `data/current_nifty50.csv` and dated copies in `data/snapshots/` when the list changes
- `data/performance.csv` – one row per event with entry, exit, return, alpha, status
- `data/announcements.csv` – parsed press releases
- `reports/latest.md` – readable summary (open it on GitHub)

The log is pre-seeded with the latest verified change: **BSE IN, WIPRO OUT, effective 30 Sep 2026**
(NSE Indices press release of 10 Aug 2026).

## Set up on GitHub (10 minutes)

1. Create a new **private or public** repository on GitHub and upload this folder
   (or `git init && git add . && git commit -m init && git push`).
2. **Settings → Actions → General → Workflow permissions** → choose
   **Read and write permissions** → Save.
3. **Actions** tab → enable workflows → open **Nifty 50 rebalance tracker** →
   **Run workflow** once to create the baseline.
4. (Optional) Telegram, see below.

That's it. The tracker runs every weekday at 20:10 IST.

### Telegram setup

**A. Create the bot**
1. In Telegram, open **@BotFather** → send `/newbot` → choose a name and a username ending in `bot`.
2. BotFather replies with a **token** like `123456789:AA...`. Keep it secret.

**B. Find your chat ID**
1. Open your new bot and press **Start** (or send any message, e.g. `hi`).
2. In a browser open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `"chat":{"id":123456789,...}` – that number is your **chat ID**.
   (For a group: add the bot to the group, send a message, and use the group's negative id.)

**C. Add both to GitHub**
Repository → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | your chat id |

**D. Test**
Actions → **Telegram bot commands** → **Run workflow**, after sending `/help` to your bot.
You should get the command list back.

### How Telegram works here

```
 You ──/status──▶ Telegram bot ◀──polls every 30 min── GitHub Actions (telegram-bot.yml)
                                                         │ reads data/*.csv, replies
                                                         │ /run → runs the full tracker, commits data
 GitHub Actions (tracker.yml, 20:10 IST) ──alert──▶ Telegram + GitHub issue
```

- **Alerts are pushed** to you the moment the daily run finds a change or an announcement.
- **Commands are polled**: GitHub cannot receive Telegram messages instantly, so the bot
  workflow checks for new messages every 30 minutes and replies then. For instant replies
  you would need a webhook host (e.g. a free Cloudflare Worker) – not included.
- Only the chat in `TELEGRAM_CHAT_ID` gets answers; anyone else is ignored.

| Command | Reply |
|---|---|
| `/status` | list size, last successful download, latest events |
| `/changes` | last 10 IN/OUT events with status |
| `/perf` | strategy returns per trade, win rate of closed trades |
| `/list` | all current Nifty 50 symbols |
| `/run` | runs the full tracker now and replies when done |
| `/help` | command list |

## NSE FII / DII / Retail positions (participant-wise OI)

`.github/workflows/nse-participant.yml` downloads NSE's official files every weekday
at 20:00, 21:30, 23:00 and 00:00 IST, plus 06:45 IST next morning (NSE publishes late on
expiry days):

- `data/nse/fao_participant_oi_DDMMYYYY.csv` – positions (open interest)
- `data/nse/fao_participant_vol_DDMMYYYY.csv` – today's buying/selling volume
- `data/nse/participant_latest.json` – ready-to-use summary: for FII, DII, Client (retail)
  and Pro, `[long, long_change, short, short_change]` for index futures, calls, puts and
  stock futures, plus today's flows and balance checks

Once a file is saved it is never downloaded again, so later runs cost seconds. A Telegram
message is sent when a new day's positions arrive (if Telegram is set up).

If the repository is **public**, the dashboard can read the summary at
`https://raw.githubusercontent.com/<you>/<repo>/main/data/nse/participant_latest.json`.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export PYTHONPATH=src                                   # Windows: set PYTHONPATH=src
python -m nifty50_tracker run
pytest -q
```

Add historical events (to back-test the strategy over past reviews):

```bash
python -m nifty50_tracker add-event --symbol BSE --company "BSE Ltd." \
  --action IN --effective 2026-09-30 --announced 2026-08-10 --confirmed \
  --source "https://niftyindices.com/Press_Release/ind_prs10082026.pdf"
```

Take past changes from NSE Indices press releases (niftyindices.com → Resources →
Press Releases). Only add events you have verified.

## Settings

Edit `src/nifty50_tracker/config.py`:

- `HOLD_DAYS` – holding period (default 365)
- `PRESS_RELEASE_LOOKBACK_DAYS` – how many past days of releases to probe
- `NEWS_QUERY` – Google News search used for "news hints" in the report
- `FAILURE_ALERT_THRESHOLD` – alert after N failed downloads in a row

Schedules are in `.github/workflows/*.yml` (cron is in UTC; IST = UTC + 5:30).

## Troubleshooting

- **"constituent download failing" issue** – NSE sometimes blocks cloud IPs. The
  tracker tries three official URLs; if all fail for 3 runs you get an issue. Re-run later,
  or run `python -m nifty50_tracker snapshot` from your own PC and push `data/`.
- **Release mentions Nifty 50 but changes not parsed** – you get a "check manually" alert with the PDF link.
  Add the event with `add-event`.
- **Effective date** – index funds trade at the close of the day *before* the effective
  date (e.g. close of 29 Sep for a 30 Sep change). The tracker enters at the close of the
  effective date, matching the "buy on inclusion date" rule.
- **Scheduled runs pause after 60 days without commits** on public repos; daily data
  commits normally keep it active.
- **Actions minutes**: public repos are free. Private repos get a monthly free quota;
  the bot workflow (30 runs/day) is the main user – reduce its cron if needed.

## Limitations

- Press-release URLs follow NSE Indices' naming pattern (`ind_prsDDMMYYYY.pdf`); a
  release published under a different name is caught on the effective day by the list diff.
- Yahoo Finance prices are adjusted for splits/dividends and can have gaps.
- Past results of this strategy do not guarantee future returns. Educational use only;
  not investment advice.
