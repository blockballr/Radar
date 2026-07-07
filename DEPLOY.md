# Deploying Radar (free, 24/7)

Radar is a long-polling Telegram bot with a background monitor, so it needs an
always-on host. This guide covers a truly free setup end to end.

The recommended host is an Oracle Cloud Always Free VM, a real 24/7 server that is
free forever and runs the bot unchanged. An alternative is Fly.io, which gives a
quick Docker deploy, though you should watch the free allowance if you keep one
machine always on. For storage, a local JSON file on a VM needs zero setup, while
the Upstash Redis free tier is required if you ever move to a serverless or
ephemeral host.

## 1. Prerequisites (do these once)

### 1a. Create the bot

Message BotFather (https://t.me/BotFather), send `/newbot`, and follow the prompts.
Copy the bot token, which looks like `123456:ABC...`; this is `TELEGRAM_TOKEN`. In
BotFather, send `/setprivacy` and disable privacy so the bot can read group
commands.

### 1b. Get your gatekeeper group ID

Create or pick the Telegram group that gates access, which is your VIP group, and
add your bot to it as an admin. Temporarily run the bot using any of the methods
below, then in that group send `/id`, which admins can use to get the chat ID.
That value is `GATEKEEPER_GROUP_ID`, a negative number like `-1001234567890`. On a
first run, set `MASTER_PASSWORD` and message the bot `/override <password>` to make
yourself admin so `/id` works.

### 1c. Optional: the `/ask` assistant

Enable natural-language questions by setting one free API key. Use `GEMINI_API_KEY`
from https://aistudio.google.com/apikey, which is preferred, or `GROQ_API_KEY` from
https://console.groq.com/keys. Leave both unset and `/ask` simply tells users it is
off while everything else works.

### 1d. Optional: Upstash Redis free tier

This is only needed for serverless hosts, or if you want state off the VM disk.
Sign up at https://upstash.com and create a Redis database on the free tier. Open
the database, find the REST API section, and copy `UPSTASH_REDIS_REST_URL` and
`UPSTASH_REDIS_REST_TOKEN`. Set both as environment variables. Radar auto-detects
them and uses Redis; leaving them unset uses the local JSON file.

## 2. Option A: Oracle Cloud Always Free VM (recommended)

This is a free ARM or x86 VM that runs 24/7 at no cost.

First, make sure `main` has the new code. Either merge the pull request into `main`,
or clone the branch directly by adding `-b worktree-radar-serverless` to the clone
command below. Plain `main` holds the old bot until the pull request is merged.

Create an Oracle Cloud account (https://www.oracle.com/cloud/free/) and launch an
Always Free compute instance; Ubuntu 22.04 is a straightforward choice. SSH in,
then run:

```bash
sudo apt update && sudo apt install -y python3-venv git
# Clone first, then create the service user pointing at that dir.
sudo git clone https://github.com/blockballr/Radar.git /opt/radar
sudo useradd -r -s /usr/sbin/nologin -d /opt/radar radar
cd /opt/radar
sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt
```

Create the env file as root:

```bash
sudo cp .env.example .env
sudo nano .env          # fill in TELEGRAM_TOKEN, GATEKEEPER_GROUP_ID, etc.
sudo chmod 600 .env
sudo chown -R radar:radar /opt/radar
```

Install the service and start it:

```bash
sudo cp deploy/radar.service /etc/systemd/system/radar.service
sudo systemctl daemon-reload
sudo systemctl enable --now radar
journalctl -u radar -f     # watch logs; look for "Radar is Online"
```

It now runs forever, restarts on crash, and survives reboots. To update later:

```bash
cd /opt/radar && sudo git pull && sudo ./venv/bin/pip install -r requirements.txt
sudo systemctl restart radar
```

## 3. Option B: Fly.io (Docker)

Install flyctl (https://fly.io/docs/hands-on/install-flyctl/) and run
`fly auth login`. From the repo root:

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

The bundled `fly.toml` keeps one machine always running by setting
`auto_stop_machines = false`, because a polling bot must stay up. On Fly, prefer
Upstash Redis for storage so state survives machine restarts and redeploys.

## 4. Option C: local or any Docker host

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

## 5. Verify it works

Check the logs with `journalctl -u radar -f`, or `fly logs`, or `docker logs -f radar`.
You should see the lines "Radar is Online" and "Position monitor scheduled". Then
message the bot `/scan`, which should return a ranked list within a few seconds.
Use `/track <CA>` on a token, then `/positions` to see it; the monitor messages you
when an exit condition triggers.

## Notes

GeckoTerminal and DexScreener are keyless and free, so the only paid thing you
might hit is a host that is not truly always free, which Oracle's VM is. On rate
limits, GeckoTerminal allows roughly thirty requests per minute; the ninety-second
monitor interval and on-demand `/scan` stay well under this for personal use. To
scan faster than ninety seconds, lower the interval in the `run_repeating` call in
`run_bot`, but mind the rate limit if you track many positions.
