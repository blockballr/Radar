"""Radar scanner CLI.

Discovers Solana tokens above $1M market cap, scores them with the signal
engine, and prints the best momentum candidates. Runs standalone with no
bot, database, or hosting — just `python scan.py`.

    python scan.py                 # top candidates, human-readable table
    python scan.py --min-score 60  # only strong-ish signals
    python scan.py --json          # machine-readable, for the cron loop
    python scan.py --all           # include AVOID/WEAK for debugging
"""

from __future__ import annotations

import argparse
import json
import sys

from engine import Verdict, discover, score_entry
from engine.signals import Config

# Windows consoles default to cp1252 and crash on emoji/em-dash; force UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _fmt_usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}k"
    return f"${v:,.2f}"


def run(min_score: int, top: int, show_all: bool, as_json: bool, pages: int):
    snaps = discover(pages=pages)
    signals = [score_entry(s) for s in snaps]

    if show_all:
        keep = signals
    else:
        keep = [s for s in signals if s.verdict != Verdict.AVOID and s.score >= min_score]

    keep.sort(key=lambda s: s.score, reverse=True)
    keep = keep[:top]

    if as_json:
        payload = [
            {
                "symbol": s.snapshot.symbol,
                "address": s.snapshot.address,
                "score": s.score,
                "verdict": s.verdict.value,
                "market_cap": s.snapshot.market_cap,
                "liquidity": s.snapshot.liquidity,
                "volume_h24": s.snapshot.volume_h24,
                "change_h1": s.snapshot.change_h1,
                "change_h6": s.snapshot.change_h6,
                "reasons": s.reasons,
                "flags": s.flags,
                "url": s.snapshot.dexscreener_url,
            }
            for s in keep
        ]
        print(json.dumps(payload, indent=2))
        return

    print(f"\nRadar scan - scanned {len(snaps)} tokens, "
          f"showing {len(keep)} (min score {min_score})\n")
    print("Not financial advice - transparent momentum heuristics only.\n")
    if not keep:
        print("No candidates cleared the bar right now. Try again shortly "
              "or lower --min-score.\n")
        return

    for s in keep:
        snap = s.snapshot
        badge = {
            Verdict.STRONG_ENTER: "🟢 STRONG",
            Verdict.WATCH: "🟡 WATCH",
            Verdict.NEUTRAL: "⚪ NEUTRAL",
            Verdict.WEAK: "🔴 WEAK",
            Verdict.AVOID: "⛔ AVOID",
        }[s.verdict]
        print(f"[{s.score:>3}] {badge:<11} ${snap.symbol:<10} "
              f"MC {_fmt_usd(snap.market_cap):>8}  "
              f"Liq {_fmt_usd(snap.liquidity):>7}  "
              f"Vol24 {_fmt_usd(snap.volume_h24):>7}  "
              f"1h {snap.change_h1:+.0f}% 6h {snap.change_h6:+.0f}%")
        for r in s.reasons:
            print(f"        + {r}")
        for f in s.flags:
            print(f"        ! {f}")
        print(f"        CA: {snap.address}")        # paste this into /track
        print(f"        {snap.dexscreener_url}")
        print()


def main(argv=None):
    p = argparse.ArgumentParser(description="Radar token momentum scanner")
    p.add_argument("--min-score", type=int, default=Config.WATCH,
                   help=f"minimum entry score to show (default {Config.WATCH})")
    p.add_argument("--top", type=int, default=15, help="max results to show")
    p.add_argument("--pages", type=int, default=1,
                   help="pages per source (each ~20 pools); mind rate limits")
    p.add_argument("--all", action="store_true",
                   help="include AVOID/WEAK results (debugging)")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args(argv)
    try:
        run(args.min_score, args.top, args.all, args.json, args.pages)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
