"""Integration test: the background jobs actually deliver Telegram messages.

This drives the real `radar_pulse_job` and `monitor_positions_job` from main.py
with a fake bot that records `send_message` calls, proving the full pipeline —
detect -> format -> send -> cooldown/removal — end to end. The only thing not
exercised is the real Telegram network hop, which is already proven live by
/scan and /ask.

Requires python-telegram-bot installed (same as running the bot).
Run:  python tests/test_bot_jobs.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Clean, isolated environment BEFORE importing main (main reads env at import).
for _k in ("PULSE_CHAT_ID", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
    os.environ.pop(_k, None)
_fd, _path = tempfile.mkstemp(suffix=".json")
os.close(_fd)
os.unlink(_path)
os.environ["RADAR_STATE_FILE"] = _path

import main  # noqa: E402
from engine import check_positions as real_check_positions  # noqa: E402
from engine.models import Position, TokenSnapshot  # noqa: E402


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    assert cond, name


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((str(chat_id), text))


class Ctx:
    def __init__(self):
        self.bot = FakeBot()


def _fast_snap():
    return TokenSnapshot(
        address="MintFast", symbol="ROCKET", price=0.01,
        market_cap=2_000_000, fdv=2_000_000, liquidity=200_000,
        volume_h24=2_400_000, volume_h1=400_000,     # 4x hourly accel
        change_m5=18.0, change_h1=45.0, change_h6=60.0,
        buys_h1=700, sells_h1=300,
        pool_created_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )


def _drop_snap():
    return TokenSnapshot(
        address="MintDrop", symbol="DUMPME", price=0.0070,   # -30% vs 0.010 entry
        market_cap=3_500_000, fdv=3_500_000, liquidity=400_000,
        volume_h24=1_000_000, volume_h1=100_000,
        buys_h1=300, sells_h1=700, change_h1=-30.0, change_h6=-40.0,
    )


async def scenario():
    # ---------- fast-mover radar delivery ----------
    main.discover = lambda *a, **k: [_fast_snap()]      # inject a live fast mover
    main._save_pulse_subs(["123"])                       # this chat opted in

    ctx = Ctx()
    await main.radar_pulse_job(ctx)
    check("pulse delivered exactly one alert", len(ctx.bot.sent) == 1)
    check("alert went to the subscribed chat", ctx.bot.sent[0][0] == "123")
    check("alert is a FAST MOVER for the right token",
          "FAST MOVER" in ctx.bot.sent[0][1] and "ROCKET" in ctx.bot.sent[0][1])

    ctx2 = Ctx()
    await main.radar_pulse_job(ctx2)
    check("cooldown suppresses an immediate repeat", len(ctx2.bot.sent) == 0)

    # ---------- position exit-signal delivery ----------
    pos = Position(address="MintDrop", symbol="DUMPME", entry_price=0.010,
                   entry_mc=5_000_000,
                   entry_time=datetime.now(timezone.utc) - timedelta(hours=2))
    main.STORE.add_position("456", pos)
    # real exit logic, but with our injected -30% snapshot
    main.check_positions = lambda store: real_check_positions(
        store, fetch=lambda a: _drop_snap())

    ctx3 = Ctx()
    await main.monitor_positions_job(ctx3)
    check("exit DM delivered", len(ctx3.bot.sent) == 1 and ctx3.bot.sent[0][0] == "456")
    check("exit DM is a stop-loss EXIT SIGNAL",
          "EXIT SIGNAL" in ctx3.bot.sent[0][1] and "DUMPME" in ctx3.bot.sent[0][1]
          and "Stop Loss" in ctx3.bot.sent[0][1])
    check("hard exit removed the position from the store",
          main.STORE.get_positions("456") == [])


def main_run():
    try:
        asyncio.run(scenario())
        print("\nAll integration checks passed.")
    finally:
        if os.path.exists(_path):
            os.unlink(_path)


if __name__ == "__main__":
    print("Running background-job delivery integration test...\n")
    main_run()
