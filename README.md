# Radar 📡

**Radar** (a.k.a. *OffTheBlock / OTB*) is a Telegram **token screener + signal agent**
for Solana. It does three things:

1. **Alerts** — pings you when a token's market cap crosses a target you set.
2. **Scans** — screens live tokens above $1M for the strongest momentum, ranked with
   transparent reasons.
3. **Tracks** — babysits your (paper) positions and DMs you when to exit
   (stop-loss / take-profit / trailing stop / momentum fade / liquidity rug).

Market data comes from free, no-key public APIs — [GeckoTerminal](https://www.geckoterminal.com/dex-api)
for discovery/metrics and [DexScreener](https://dexscreener.com) for the alert wizard.

> ⚠️ **Not financial advice.** The scanner and exit calls are transparent momentum
> heuristics, not alpha. Tokens above $1M market cap are still highly risky.

---

## Architecture

```
GeckoTerminal (discovery + metrics)  ─┐
DexScreener (alert lookups)          ─┤
                                      ▼
              engine/  ── host-agnostic core (no Telegram, no host deps)
                ├─ discovery.py   find + normalize tokens
                ├─ signals.py     deterministic 0–100 entry score + exit engine
                ├─ models.py      TokenSnapshot / Position
                ├─ store.py       KV persistence (JSON file ↔ Upstash Redis)
                └─ monitor.py     evaluate exits across tracked positions
                                      ▼
              main.py   ── Telegram bot (commands + background monitor job)
              scan.py   ── standalone screener CLI
              track.py  ── standalone position-tracker CLI
```

Every money-relevant decision lives in `engine/` as plain, testable Python. The bot
and CLIs are thin shells over it.

## Commands (Telegram)

| Command | Description |
| --- | --- |
| `/scan` | Screen $1M+ tokens by momentum, ranked with reasons |
| `/track <CA>` | Track a token for exit signals |
| `/positions` | View tracked positions with live P&L; tap to stop tracking |
| `/alert` | Set an MC alert (wizard, or `/alert <CA> <MC>` in a group) |
| `/alerts` | View / delete your active alerts |
| `/override <password>` | Activate master admin override |
| `/id` | Show the current group's chat ID (admins only) |

## CLIs (no bot needed)

```bash
python scan.py                 # screen the market now, human-readable
python scan.py --min-score 70  # only STRONG signals
python scan.py --json          # machine-readable (for cron)

python track.py add <CA>       # paper-track a token (mint OR pool address)
python track.py list           # live P&L on positions
python track.py check          # evaluate exits now (what the monitor runs)
python track.py rm <CA>        # stop tracking
```

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `TELEGRAM_TOKEN` | ✅ (bot) | Bot token from [@BotFather](https://t.me/BotFather) |
| `GATEKEEPER_GROUP_ID` | ✅ (bot) | Chat ID of the VIP group used for access control |
| `MASTER_PASSWORD` | optional | Password for the `/override` admin bypass |
| `UPSTASH_REDIS_REST_URL` | optional | Enables Redis storage (else local JSON file) |
| `UPSTASH_REDIS_REST_TOKEN` | optional | Upstash REST token (pair with the URL above) |
| `RADAR_STATE_FILE` | optional | Path for the local JSON store (default `radar_state.json`) |

**Storage:** with no Upstash vars set, all state (alerts, admins, positions) lives in a
single local JSON file — great for a VM. Set the two `UPSTASH_*` vars and the exact same
code stores everything in Upstash Redis instead, making the bot safe to run on ephemeral
/ serverless hosts.

## Running locally

```bash
pip install -r requirements.txt

export TELEGRAM_TOKEN="123456:ABC..."
export GATEKEEPER_GROUP_ID="-1001234567890"
export MASTER_PASSWORD="something-secret"
# optional — turn on Redis storage:
# export UPSTASH_REDIS_REST_URL="https://xxx.upstash.io"
# export UPSTASH_REDIS_REST_TOKEN="..."

python main.py
```

The bot long-polls, pushes its slash commands, and schedules the position monitor
(every 90s). A tiny Flask keep-alive server also runs on `:8080` for hosts that need it.

## Free hosting

Designed to run at $0. Recommended: an always-on free VM (Oracle Cloud "Always Free"
or Fly.io) running `python main.py`, with Upstash Redis (free tier) for state. See the
project notes for the step-by-step deploy.

## Tests

```bash
python tests/test_signals.py        # 10 signal-engine tests
python tests/test_store_monitor.py  # 6 store + monitor tests
```

## Tech stack

- Python 3, [python-telegram-bot](https://python-telegram-bot.org/) (`JobQueue`)
- `requests` — GeckoTerminal + DexScreener + Upstash REST
- Flask (keep-alive)
