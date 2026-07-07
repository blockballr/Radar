"""Offline sanity tests for the signal engine — no network required.

Run with:  python -m pytest tests/ -q      (or)   python tests/test_signals.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.models import Position, TokenSnapshot  # noqa: E402
from engine.signals import (  # noqa: E402
    ExitAction,
    Verdict,
    evaluate_exit,
    score_entry,
)


def _base(**kw) -> TokenSnapshot:
    """A healthy, mid-momentum token; override fields per test."""
    defaults = dict(
        address="Mint111", symbol="TEST", price=0.01,
        market_cap=5_000_000, fdv=5_000_000, liquidity=500_000,
        volume_m5=20_000, volume_h1=250_000, volume_h6=900_000, volume_h24=2_000_000,
        change_m5=1.0, change_h1=8.0, change_h6=20.0, change_h24=35.0,
        buys_m5=60, sells_m5=40, buys_h1=650, sells_h1=350,
        buys_h24=6000, sells_h24=4000,
        pool_created_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    defaults.update(kw)
    return TokenSnapshot(**defaults)


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    assert cond, name


def test_strong_entry():
    sig = score_entry(_base())
    check("healthy momentum token scores as candidate", sig.is_candidate)
    check("strong token score >= 55", sig.score >= 55)
    check("has explanatory reasons", len(sig.reasons) > 0)


def test_below_universe_avoided():
    sig = score_entry(_base(market_cap=400_000))
    check("sub-$1M token is AVOID", sig.verdict == Verdict.AVOID)
    check("sub-$1M scores 0", sig.score == 0)


def test_rug_liquidity_avoided():
    sig = score_entry(_base(liquidity=40_000, market_cap=5_000_000))
    check("thin liquidity/MC is AVOID", sig.verdict == Verdict.AVOID)


def test_parabolic_penalized():
    hot = score_entry(_base(change_h1=120.0))
    calm = score_entry(_base(change_h1=8.0))
    check("parabolic 1h scores <= calmer trend", hot.score <= calm.score)
    check("parabolic flagged", any("top" in f for f in hot.flags))


def test_sell_pressure_lower_score():
    buyers = score_entry(_base(buys_h1=700, sells_h1=300))
    sellers = score_entry(_base(buys_h1=300, sells_h1=700))
    check("buy pressure scores higher than sell pressure",
          buyers.score > sellers.score)


def _pos(**kw) -> Position:
    defaults = dict(
        address="Mint111", symbol="TEST",
        entry_price=0.010, entry_mc=5_000_000,
        entry_time=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    defaults.update(kw)
    return Position(**defaults)


def test_exit_stop_loss():
    pos = _pos()
    snap = _base(price=0.0070, market_cap=3_500_000)  # -30%
    ex = evaluate_exit(pos, snap)
    check("30% drop triggers stop-loss", ex.action == ExitAction.STOP_LOSS)
    check("stop-loss flagged as exit", ex.should_exit)


def test_exit_take_profit():
    pos = _pos()
    snap = _base(price=0.016, market_cap=8_000_000)  # +60%
    ex = evaluate_exit(pos, snap)
    check("60% gain triggers take-profit", ex.action == ExitAction.TAKE_PROFIT)


def test_exit_trailing_stop():
    pos = _pos(peak_price=0.020)  # already ran to +100%, now pulling back
    snap = _base(price=0.015, market_cap=7_500_000)  # -25% from peak, +50% net
    ex = evaluate_exit(pos, snap)
    check("pullback from peak triggers trailing stop",
          ex.action == ExitAction.TRAILING_STOP)


def test_exit_hold():
    pos = _pos()
    snap = _base(price=0.011, market_cap=5_500_000)  # +10%, healthy
    ex = evaluate_exit(pos, snap)
    check("modest gain with healthy tape holds", ex.action == ExitAction.HOLD)


def test_exit_rug():
    pos = _pos()
    snap = _base(price=0.009, liquidity=10_000, market_cap=4_500_000)
    ex = evaluate_exit(pos, snap)
    check("liquidity collapse triggers rug exit", ex.action == ExitAction.RUG_EXIT)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} signal-engine tests...\n")
    for t in tests:
        print(t.__name__)
        t()
    print(f"\nAll {len(tests)} tests passed.")
