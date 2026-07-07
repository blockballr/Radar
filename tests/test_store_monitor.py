"""Offline tests for the store + position monitor — no network required.

Run:  python tests/test_store_monitor.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.models import Position, TokenSnapshot  # noqa: E402
from engine.monitor import check_positions  # noqa: E402
from engine.signals import ExitAction  # noqa: E402
from engine.store import JsonStore  # noqa: E402


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    assert cond, name


def _tmp_store() -> JsonStore:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # start empty
    return JsonStore(path)


def _pos(addr="MintA", symbol="AAA", entry=0.01, **kw) -> Position:
    d = dict(
        address=addr, symbol=symbol, entry_price=entry, entry_mc=5_000_000,
        entry_time=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    d.update(kw)
    return Position(**d)


def _snap(addr="MintA", price=0.01, mc=5_000_000, **kw) -> TokenSnapshot:
    d = dict(
        address=addr, symbol="AAA", price=price, market_cap=mc, fdv=mc,
        liquidity=500_000, volume_h24=2_000_000, volume_h1=200_000,
        buys_h1=600, sells_h1=400, change_h1=5.0, change_h6=20.0,
    )
    d.update(kw)
    return TokenSnapshot(**d)


def test_store_roundtrip():
    store = _tmp_store()
    store.add_position("u1", _pos())
    got = store.get_positions("u1")
    check("position persisted and reloaded", len(got) == 1)
    check("round-trip preserves entry price", abs(got[0].entry_price - 0.01) < 1e-9)
    check("round-trip preserves entry time type", isinstance(got[0].entry_time, datetime))
    os.unlink(store.path)


def test_store_dedup_and_remove():
    store = _tmp_store()
    store.add_position("u1", _pos(entry=0.01))
    store.add_position("u1", _pos(entry=0.02))  # same token -> replace
    check("same-token add replaces, not dup", len(store.get_positions("u1")) == 1)
    check("replacement kept latest entry", store.get_positions("u1")[0].entry_price == 0.02)
    removed = store.remove_position("u1", "MintA")
    check("remove returns True when it removed", removed)
    check("position list empty after remove", store.get_positions("u1") == [])
    os.unlink(store.path)


def test_store_user_index():
    store = _tmp_store()
    store.add_position("u1", _pos(addr="MintA"))
    store.add_position("u2", _pos(addr="MintB"))
    users = set(store.all_position_users())
    check("both users indexed", users == {"u1", "u2"})
    allpos = store.all_positions()
    check("all_positions returns per-user lists", len(allpos["u1"]) == 1 and len(allpos["u2"]) == 1)
    os.unlink(store.path)


def test_monitor_take_profit_removes():
    store = _tmp_store()
    store.add_position("u1", _pos(entry=0.01))
    # fake fetcher returns a +60% price -> take-profit
    updates = check_positions(store, fetch=lambda a: _snap(price=0.016, mc=8_000_000))
    check("one exit signal produced", len(updates) == 1)
    check("exit is take-profit", updates[0].exit_signal.action == ExitAction.TAKE_PROFIT)
    check("hard exit removes position from store", store.get_positions("u1") == [])
    os.unlink(store.path)


def test_monitor_hold_keeps_and_persists_peak():
    store = _tmp_store()
    store.add_position("u1", _pos(entry=0.01))
    # +15%, healthy -> HOLD, and peak should be persisted at 0.0115
    updates = check_positions(store, fetch=lambda a: _snap(price=0.0115, mc=5_750_000))
    check("no exit on healthy hold", len(updates) == 0)
    kept = store.get_positions("u1")
    check("position retained", len(kept) == 1)
    check("peak price persisted upward", abs(kept[0].peak_price - 0.0115) < 1e-9)
    os.unlink(store.path)


def test_monitor_momentum_fade_keeps_tracking():
    store = _tmp_store()
    store.add_position("u1", _pos(entry=0.01))
    # +20% but tape turned: sells>buys and 1h down -> advisory fade, keep it
    fade = lambda a: _snap(price=0.012, mc=6_000_000, buys_h1=300, sells_h1=700, change_h1=-8.0)
    updates = check_positions(store, fetch=fade)
    check("momentum-fade emits a signal", len(updates) == 1)
    check("fade is advisory action", updates[0].exit_signal.action == ExitAction.MOMENTUM_FADE)
    check("advisory keeps position tracked", len(store.get_positions("u1")) == 1)
    os.unlink(store.path)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} store/monitor tests...\n")
    for t in tests:
        print(t.__name__)
        t()
    print(f"\nAll {len(tests)} tests passed.")
