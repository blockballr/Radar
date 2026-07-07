# Deploying Radar (free, 24/7)

Radar is a long-polling Telegram bot with a background monitor, so it needs an
**always-on** host. This guide covers a truly-free setup end to end.

- **Recommended:** Oracle Cloud "Always Free" VM — a real 24/7 server, free
  forever, runs the bot unchanged.
- **Alternative:** Fly.io — quick Docker deploy (watch the free allowance if you
  keep one machine always on).
- **Storage:** local JSON file on a VM (zero setup), or Upstash Redis free tier
  (required if you ever move to a serverless/ephemeral host).

---

## 1. Prerequisites (do these once)

### 1a. Create the bot
1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → follow prompts.
2. Copy the **bot token** (looks like `123456:ABC...`). This is `TELEGRAM_TOKEN`.
3. In BotFather, `/setprivacy` → **Disable** so the bot can read group commands.

### 1b. Get your gatekeeper group ID
1. Create (or pick) the Telegram group that gates access (your VIP group).
2. Add your bot to it as an admin.
3. Temporarily run the bot (any of the methods below), then in that group send
   `/id` (admins only) — it replies with the chat ID. That is
   `GATEKEEPER_GROUP_ID` (a negative number like `-1001234567890`).
   - First run? Set `MASTER_PASSWORD`, DM the bot `/override <password>` to make
     yourself admin so `/id` works.

### 1c-bis. (Optional) `/ask` assistant — free LLM
Enable natural-language questions by setting **one** free API key:
- `GEMINI_API_KEY` from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (preferred), or
- `GROQ_API_KEY` from [console.groq.com/keys](https://console.groq.com/keys).

Leave both unset and `/ask` simply tells users it's off — everything else works.

### 1c. (Optional) Upstash Redis — free tier
Only needed for serverless, or if you want state off the VM disk.
1. Sign up at [upstash.com](https://upstash.com) → **Create Database** (Redis, free).
2. Open the DB → **REST API** section → copy `UPSTASH_REDIS_REST_URL` and
   `UPSTASH_REDIS_REST_TOKEN`.
3. Set both as env vars. Radar auto-detects them and uses Redis; unset = local JSON.

---

## 2. Option A — Oracle Cloud "Always Free" VM (recommended)

A free ARM/x86 VM that runs 24/7 at no cost.

> **First:** merge the PR into `main` so `main` has the new code, **or** clone the
> branch directly with `-b worktree-radar-serverless` in the command below.
> (Plain `main` holds the *old* bot until the PR is merged.)

1. Create an [Oracle Cloud](https://www.oracle.com/cloud/free/) account and launch
   an **Always Free** compute instance (Ubuntu 22.04 is easy).
2. SSH in, then:

   ```bash
   sudo apt update && sudo apt install -y python3-venv git
   # Clone first, then create the service user pointing at that dir.
   sudo git clone https://github.com/blockballr/Radar.git /opt/radar
   sudo useradd -r -s /usr/sbin/nologin -d /opt/radar radar
   cd /opt/radar
   sudo python3 -m venv venv
   sudo ./venv/bin/pip install -r requirements.txt
   ```

3. Create the env file (as root):

   ```bash
   sudo cp .env.example .env
   sudo nano .env          # fill in TELEGRAM_TOKEN, GATEKEEPER_GROUP_ID, etc.
   sudo chmod 600 .env
   sudo chown -R radar:radar /opt/radar
   ```

4. Install the service and start it:

   ```bash
   sudo cp deploy/radar.service /etc/systemd/system/radar.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now radar
   journalctl -u radar -f     # watch logs; look for "Radar is Online"
   ```

It now runs forever, restarts on crash, and survives reboots.

**Update later:**
```bash
cd /opt/radar && sudo git pull && sudo ./venv/bin/pip install -r requirements.txt
sudo systemctl restart radar
```

---

## 3. Option B — Fly.io (Docker)

1. Install [flyctl](https://fly.io/docs/hands-on/install-flyctl/) and `fly auth login`.
2. From the repo root:

   ```bash
   fly launch --no-deploy        # accept the bundled fly.toml; pick a unique app name
   fly secrets set \
     TELEGRAM_TOKEN="123456:ABC..." \
     GATEKEEPER_GROUP_ID="-1001234567890" \
     MASTER_PASSWORD="something-secret"
   # optional Redis:
   # fly secrets set UPSTASH_REDIS_REST_URL="https://..." UPSTASH_REDIS_REST_TOKEN="..."
   fly deploy
   fly logs
   ```

`fly.toml` keeps one machine always running (`auto_stop_machines = false`) because
a polling bot must stay up. On Fly, prefer **Upstash Redis** for storage so state
survives machine restarts/redeploys.

---

## 4. Option C — Local / any Docker host

```bash
cp .env.example .env      # fill it in
docker build -t radar .
docker run -d --name radar --env-file .env -p 8080:8080 --restart unless-stopped radar
docker logs -f radar
```

Or without Docker:

```bash
pip install -r requirements.txt
set -a && source .env && set +a      # load env vars
python main.py
```

---

## 5. Verify it works

1. `journalctl -u radar -f` (or `fly logs` / `docker logs -f radar`) shows:
   `🤖 Radar is Online...` and `🛰️  Position monitor scheduled`.
2. DM the bot `/scan` — you should get a ranked list within a few seconds.
3. `/track <CA>` a token, then `/positions` to see it. The monitor DMs you when an
   exit condition triggers.

## Notes

- **Free tiers:** GeckoTerminal & DexScreener are keyless and free. The only paid
  thing you might hit is a host that isn't truly always-free — Oracle's VM is.
- **Rate limits:** GeckoTerminal allows ~30 req/min. The 90s monitor interval and
  on-demand `/scan` stay well under this for personal use.
- **Scaling checks faster than 90s:** lower the `interval` in `run_bot()`'s
  `run_repeating(...)`, but mind the rate limit if you track many positions.
