# Radar

Radar is an autonomous market agent for Solana, delivered through Telegram. It
watches the market for you: continuously scanning for momentum, flagging tokens
that suddenly move on volume, and managing the positions you hold, so you do not
have to stare at charts.

Primarily, Radar monitors the live Solana market and tells you what is moving and
why. It watches the market on its own, scanning about every two minutes and
pushing an alert when a token spikes on rising volume; opt a chat in with
`/radar on` and it needs no further prompting. It screens for momentum on demand,
ranking live tokens above one million dollars by price action, volume
acceleration, buy pressure, and liquidity, with transparent reasons for each. It
manages your positions, tracking entries and messaging you when to exit on a
stop-loss, take-profit, trailing stop, momentum fade, or liquidity rug. It
answers questions about the market in plain English, and it sends custom
market-cap alerts when a token crosses a target you set.

Market data comes from free, no-key public APIs: GeckoTerminal
(https://www.geckoterminal.com/dex-api) for discovery and metrics, and
DexScreener (https://dexscreener.com) for token lookups.

This is not financial advice. The scanner and exit calls are transparent momentum
heuristics, not alpha. Tokens above one million dollars in market cap are still
highly risky.

## Architecture

Every money-relevant decision lives in the `engine/` package as plain, testable
Python with no Telegram or hosting dependencies. Within it, `discovery.py` finds
and normalizes tokens from GeckoTerminal, `signals.py` holds the deterministic
zero-to-one-hundred entry score and the exit engine, `models.py` defines the
TokenSnapshot and Position types, `store.py` provides pluggable key-value
persistence over either a local JSON file or Upstash Redis, `monitor.py`
evaluates exits across tracked positions, `pulse.py` detects fast movers, and
`chat.py` is the optional narrator layer for `/ask`.

The `main.py` module is the Telegram bot: it wires the commands and runs the
background monitor and fast-mover jobs. The two scripts in `scripts/` are thin
shells over the same engine: `scan.py` is a standalone screener and `track.py` is
a standalone position tracker.

## Commands

Radar exposes these Telegram commands. Use `/scan` to screen tokens above one
million dollars by momentum, ranked with reasons. Use `/radar on` to turn on
auto-alerts for the current chat when a token spikes fast on rising volume, and
`/radar off` to stop. Use `/ask` followed by a question to ask about the market
in plain English, which needs a free LLM key. Use `/track` with a contract
address to track a token for exit signals, and `/positions` to view tracked
positions with live profit and loss and to stop tracking. Use `/alert` to set a
market-cap alert through a wizard, or `/alert <CA> <MC>` directly in a group, and
`/alerts` to view or delete your active alerts. Admins can use `/override` with
the master password to activate the admin override, and `/id` to show the current
group's chat ID.

## Command-line scripts

The scripts run without the bot:

```bash
python scripts/scan.py                 # screen the market now, human-readable
python scripts/scan.py --min-score 70  # only strong signals
python scripts/scan.py --json          # machine-readable, for cron

python scripts/track.py add <CA>       # paper-track a token (mint or pool address)
python scripts/track.py list           # live profit and loss on positions
python scripts/track.py check          # evaluate exits now (what the monitor runs)
python scripts/track.py rm <CA>        # stop tracking
```

## Configuration

Radar reads its settings from environment variables. The bot requires
`TELEGRAM_TOKEN`, the bot token from BotFather (https://t.me/BotFather), and
`GATEKEEPER_GROUP_ID`, the chat ID of the VIP group used for access control.

The rest are optional. `MASTER_PASSWORD` sets the password for the `/override`
admin bypass. `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` together
enable Redis storage; leave them unset to use a local JSON file. `RADAR_STATE_FILE`
sets the path for that local JSON store, defaulting to `radar_state.json`.
`GEMINI_API_KEY` enables `/ask` through the Google Gemini free tier, and
`GROQ_API_KEY` enables `/ask` through the Groq free tier, used only when no Gemini
key is set. `PULSE_CHAT_ID` always posts fast-mover alerts to a fixed chat or
channel, and `PULSE_INTERVAL` sets the seconds between fast-mover scans,
defaulting to 120.

The fast-mover radar is a background job that scans every `PULSE_INTERVAL` seconds
and pushes an alert when a token spikes, meaning at least twelve percent in five
minutes or thirty-five percent in one hour, on at least two and a half times its
hourly volume with real buy pressure. Opt a chat in with `/radar on`, or set
`PULSE_CHAT_ID` for a fixed channel. A per-token cooldown prevents spam.

The `/ask` assistant is a free LLM, either Gemini or Groq, that answers questions
grounded only in the live scan and your positions. It narrates the engine's data;
it never scores tokens or invents numbers. It is disabled and harmless if no key
is set.

For storage, with no Upstash variables set, all state (alerts, admins, positions)
lives in a single local JSON file, which is ideal for a persistent VM. Set the two
Upstash variables and the exact same code stores everything in Upstash Redis
instead, making the bot safe to run on ephemeral or serverless hosts.

## Running locally

```bash
pip install -r requirements.txt

export TELEGRAM_TOKEN="123456:ABC..."
export GATEKEEPER_GROUP_ID="-1001234567890"
export MASTER_PASSWORD="something-secret"
# optional, turn on Redis storage:
# export UPSTASH_REDIS_REST_URL="https://xxx.upstash.io"
# export UPSTASH_REDIS_REST_TOKEN="..."

python main.py
```

The bot long-polls, pushes its slash commands, and schedules the position monitor
every ninety seconds. A small Flask keep-alive server also runs on port 8080 for
hosts that need it.

## Free hosting

Radar is designed to run at no cost. The recommended setup is an always-on free VM,
such as Oracle Cloud Always Free or Fly.io, running `python main.py`, with the
Upstash Redis free tier for state. See DEPLOY.md for the step-by-step guide.

## Tests

```bash
python tests/test_signals.py        # signal-engine tests
python tests/test_store_monitor.py  # store and monitor tests
python tests/test_chat.py           # chat-layer tests (offline)
python tests/test_pulse.py          # fast-mover detector tests
python tests/test_bot_jobs.py       # integration: background jobs to Telegram delivery
```

## Tech stack

Radar runs on Python 3 with python-telegram-bot (https://python-telegram-bot.org/)
and its JobQueue extra, the requests library for the GeckoTerminal, DexScreener,
and Upstash REST calls, and Flask for the keep-alive server.
