"""Offline tests for the fast-mover detector - no network required.

Run:  python tests/test_pulse.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.models import TokenSnapshot  # noqa: E402
from engine.pulse import find_fast_movers  # noqa: E402


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    assert cond, name


def _snap(**kw) -> TokenSnapshot:
    # A token spiking +18% in 5m on ~4x volume with strong buys.
    d = dict(
        address="MintFast", symbol="ROCKET", price=0.01,
        market_cap=2_000_000, fdv=2_000_000, liquidity=200_000,
        volume_h24=2_400_000, volume_h1=400_000,   # 400k vs 100k avg = 4x accel
        change_m5=18.0, change_h1=45.0, change_h6=60.0,
        buys_h1=700, sells_h1=300,
        pool_created_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    d.update(kw)
    return TokenSnapshot(**d)


def test_detects_fast_mover():
    movers = find_fast_movers([_snap()])
    check("clear fast mover is detected", len(movers) == 1)
    check("trigger mentions the volume multiple", "volume" in movers[0].trigger)
    check("trigger mentions a short-window spike",
          "5m" in movers[0].trigger or "1h" in movers[0].trigger)


def test_ignores_slow_token():
    slow = _snap(change_m5=1.0, change_h1=3.0, change_h6=5.0)
    check("no spike -> not a fast mover", find_fast_movers([slow]) == [])


def test_ignores_spike_without_volume():
    # big price move but volume in line with its average (accel ~1x)
    no_vol = _snap(volume_h1=100_000, volume_h24=2_400_000)
    check("spike without volume surge is ignored", find_fast_movers([no_vol]) == [])


def test_ignores_sell_pressure():
    dumping = _snap(buys_h1=300, sells_h1=700)
    check("spike on net selling is ignored", find_fast_movers([dumping]) == [])


def test_ignores_illiquid():
    thin = _snap(liquidity=5_000)
    check("illiquid token is ignored", find_fast_movers([thin]) == [])


def test_ranks_by_heat():
    hot = _snap(address="A", symbol="HOT", change_m5=40.0,
                volume_h1=800_000, volume_h24=2_400_000)   # 8x accel
    mild = _snap(address="B", symbol="MILD", change_m5=13.0)
    order = [m.snapshot.symbol for m in find_fast_movers([mild, hot])]
    check("hotter mover ranks first", order and order[0] == "HOT")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} pulse tests...\n")
    for t in tests:
        print(t.__name__)
        t()
    print(f"\nAll {len(tests)} tests passed.")
