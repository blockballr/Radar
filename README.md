# Radar 📡

**Radar** (a.k.a. *OffTheBlock / OTB*) is a Telegram bot that watches Solana token
market caps and pings you the moment a token crosses a target you set.

Prices come from the [DexScreener](https://dexscreener.com) public API, polled every
30 seconds per active alert. Alerts survive restarts (persisted to disk) and can be
managed from a private DM with tap-to-delete buttons.

---

## Features

- **Set alerts two ways**
  - Guided wizard: `/alert` → paste the contract address (CA) → send a target market cap (`1.7M`, `500k`, `$2,000,000`).
  - One-shot: `/alert <CA> <target_mc>` directly in a group.
- **Direction is inferred** — if the target is above the current MC it fires on *rise*, otherwise on *drop*.
- **Manage alerts** — `/alerts` opens a DM list; tap an entry to delete it.
- **Persistence** — active alerts are stored in `alerts_db.json` and restored on boot.
- **Auto-cleanup** — helper/prompt messages self-destruct to keep group chats clean.
- **Access control**
  - Users must be members of a gatekeeper Telegram group (`GATEKEEPER_GROUP_ID`).
  - `/override <MASTER_PASSWORD>` grants an admin bypass (stored in `admins.json`).
  - `/id` (admins only) prints the current chat's group ID to help configure the gatekeeper.
- **Keep-alive** — a tiny Flask server on port `8080` responds "Radar is Online" so the
  process stays awake on always-on hosts (Replit, Render, etc.). Flask auto-installs if missing.

## Commands

| Command | Description |
| --- | --- |
| `/alert` | Start the setup wizard (or `/alert <CA> <MC>` for a quick alert) |
| `/alerts` | View / delete your active alerts |
| `/override <password>` | Activate master admin override |
| `/id` | Show the current group's chat ID (admins only) |
| `/cancel` | Cancel the current wizard |

## Configuration

Set these environment variables before running:

| Variable | Required | Purpose |
| --- | --- | --- |
| `TELEGRAM_TOKEN` | ✅ | Bot token from [@BotFather](https://t.me/BotFather) |
| `GATEKEEPER_GROUP_ID` | ✅ | Chat ID of the VIP group used for access control |
| `MASTER_PASSWORD` | optional | Password for the `/override` admin bypass |

## Running locally

```bash
pip install -r requirements.txt

export TELEGRAM_TOKEN="123456:ABC..."
export GATEKEEPER_GROUP_ID="-1001234567890"
export MASTER_PASSWORD="something-secret"

python main.py
```

The bot starts long-polling and launches the keep-alive server on `:8080`.

## Files

| File | Description |
| --- | --- |
| `main.py` | Entire bot: handlers, alert engine, DexScreener client, Flask keep-alive |
| `requirements.txt` | Python dependencies |
| `alerts_db.json` | *(generated)* persisted active alerts — **git-ignored** |
| `admins.json` | *(generated)* override-admin user IDs — **git-ignored** |

## Tech stack

- Python 3
- [python-telegram-bot](https://python-telegram-bot.org/)
- `requests` (DexScreener API)
- Flask (keep-alive)
- APScheduler (via python-telegram-bot's `JobQueue`)
