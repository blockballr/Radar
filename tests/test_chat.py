"""Offline tests for the LLM chat layer - no network, no API key required.

Run:  python tests/test_chat.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import chat  # noqa: E402
from engine.models import Position, TokenSnapshot  # noqa: E402
from engine.signals import score_entry  # noqa: E402


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    assert cond, name


def _clear_keys():
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        os.environ.pop(k, None)


def test_disabled_without_keys():
    _clear_keys()
    check("no keys -> provider None", chat.provider() is None)
    check("no keys -> disabled", chat.is_enabled() is False)


def test_provider_precedence():
    _clear_keys()
    os.environ["GROQ_API_KEY"] = "x"
    check("groq key -> groq provider", chat.provider() == "groq")
    os.environ["GEMINI_API_KEY"] = "y"
    check("gemini preferred over groq", chat.provider() == "gemini")
    check("enabled when a key is set", chat.is_enabled() is True)
    _clear_keys()
    check("cleared -> disabled again", chat.is_enabled() is False)


def test_answer_raises_without_provider():
    _clear_keys()
    try:
        chat.answer("hi", "data")
        check("answer without provider raises", False)
    except RuntimeError:
        check("answer without provider raises", True)


def _snap():
    return TokenSnapshot(
        address="MintX", symbol="WAGMI", price=0.01,
        market_cap=5_000_000, fdv=5_000_000, liquidity=500_000,
        volume_h24=2_000_000, volume_h1=250_000,
        buys_h1=700, sells_h1=300, change_h1=8.0, change_h6=25.0,
        pool_created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )


def test_context_includes_scan_and_positions():
    sig = score_entry(_snap())
    pos = Position(address="MintX", symbol="WAGMI", entry_price=0.008,
                   entry_mc=4_000_000,
                   entry_time=datetime.now(timezone.utc) - timedelta(hours=3))
    ctx = chat.build_context([sig], [(pos, 25.0)])
    check("context labels the scan", "LIVE MOMENTUM SCAN" in ctx)
    check("context includes the token symbol", "$WAGMI" in ctx)
    check("context includes the score", f"score={sig.score}" in ctx)
    check("context includes positions section", "TRACKED POSITIONS" in ctx)
    check("context includes pnl", "pnl=+25%" in ctx)


def test_context_handles_empty_scan():
    ctx = chat.build_context([], None)
    check("empty scan is described, not crashing", "no candidates" in ctx.lower())


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} chat tests...\n")
    for t in tests:
        print(t.__name__)
        t()
    _clear_keys()
    print(f"\nAll {len(tests)} tests passed.")
