"""Radar position tracker CLI.

Paper-track tokens and get exit calls from the same engine the bot will use.
State is stored via the shared store (local JSON by default; Upstash Redis if
its env vars are set), so this CLI and the future bot see the same positions.

    python scripts/track.py add <CA> [--tp 50] [--sl 25] [--trail 20]
    python scripts/track.py list
    python scripts/track.py rm <CA>
    python scripts/track.py check          # evaluate exits now (what the cron runs)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Position, check_positions, fetch_token, get_store  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Single local user for the CLI; the bot keys positions by Telegram user id.
CLI_USER = "cli"


def _fmt_usd(v: float) -> str:
    """Large values: market cap, liquidity."""
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}k"
    return f"${v:,.2f}"


def _fmt_price(v: float) -> str:
    """Token price with enough significant digits for sub-cent memecoins."""
    import math
    if v >= 1:
        return f"${v:,.2f}"
    if v <= 0:
        return "$0"
    # ~4 significant figures below $1 (e.g. $0.000003900)
    decimals = -int(math.floor(math.log10(v))) + 3
    return f"${v:.{decimals}f}"


def cmd_add(args):
    store = get_store()
    snap = fetch_token(args.address)
    if snap is None or snap.price <= 0:
        print(f"Could not fetch token {args.address}, is the mint correct?")
        return 1
    pos = Position(
        address=snap.address,
        symbol=snap.symbol,
        entry_price=snap.price,
        entry_mc=snap.market_cap,
        entry_time=datetime.now(timezone.utc),
        take_profit_pct=args.tp,
        stop_loss_pct=args.sl,
        trailing_pct=args.trail,
    )
    store.add_position(CLI_USER, pos)
    print(f"Tracking ${snap.symbol} @ {_fmt_price(snap.price)} "
          f"(MC {_fmt_usd(snap.market_cap)}): "
          f"TP +{args.tp:.0f}% / SL -{args.sl:.0f}% / trail {args.trail:.0f}%")
    return 0


def cmd_list(args):
    store = get_store()
    positions = store.get_positions(CLI_USER)
    if not positions:
        print("No tracked positions.")
        return 0
    print(f"\n{len(positions)} tracked position(s):\n")
    for p in positions:
        snap = fetch_token(p.address)
        if snap:
            pnl = (snap.price / p.entry_price - 1) * 100 if p.entry_price else 0
            print(f"  ${p.symbol:<10} entry {_fmt_price(p.entry_price):>13}  "
                  f"now {_fmt_price(snap.price):>13}  {pnl:+.0f}%  "
                  f"(TP +{p.take_profit_pct:.0f}/SL -{p.stop_loss_pct:.0f}/trail {p.trailing_pct:.0f})")
        else:
            print(f"  ${p.symbol:<10} entry {_fmt_price(p.entry_price):>13}  (no live data)")
    print()
    return 0


def cmd_rm(args):
    store = get_store()
    if store.remove_position(CLI_USER, args.address):
        print("Removed.")
    else:
        print("No matching tracked position.")
    return 0


def cmd_check(args):
    store = get_store()
    updates = check_positions(store)
    if not updates:
        print("No exit signals, all tracked positions holding.")
        return 0
    print(f"\n{len(updates)} exit signal(s):\n")
    for u in updates:
        ex = u.exit_signal
        print(f"  ${u.position.symbol}: {ex.action.value}  ({ex.pnl_pct:+.0f}%)")
        for r in ex.reasons:
            print(f"       {r}")
    print()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Radar position tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="track a token")
    a.add_argument("address")
    a.add_argument("--tp", type=float, default=50.0, help="take-profit %%")
    a.add_argument("--sl", type=float, default=25.0, help="stop-loss %%")
    a.add_argument("--trail", type=float, default=20.0, help="trailing stop %%")
    a.set_defaults(func=cmd_add)

    sub.add_parser("list", help="list tracked positions").set_defaults(func=cmd_list)

    r = sub.add_parser("rm", help="stop tracking a token")
    r.add_argument("address")
    r.set_defaults(func=cmd_rm)

    sub.add_parser("check", help="evaluate exits now").set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
