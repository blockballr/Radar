"""Optional natural-language layer for Radar.

Turns a user question + the live deterministic scan/position data into a
plain-English answer using a free LLM (Google Gemini or Groq). The model is
strictly a *narrator*: it is given the engine's data and told to answer only
from it — it never scores tokens, invents numbers, or decides trades. Those
stay in `signals.py`.

Enabled by setting one env var:
  * GEMINI_API_KEY  — https://aistudio.google.com/apikey  (free tier)
  * GROQ_API_KEY    — https://console.groq.com/keys       (free tier)

If neither is set, `is_enabled()` returns False and the bot tells the user how
to turn it on. No LLM dependency is required to run the rest of Radar.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

import requests

log = logging.getLogger("radar.chat")

GEMINI_MODEL = "gemini-2.0-flash"
GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM = (
    "You are Radar, a Solana token screening assistant. Answer the user's "
    "question using ONLY the DATA block below — a live momentum scan and, if "
    "present, the user's tracked positions. Never invent tokens, prices, or "
    "numbers that are not in the data; if the data doesn't cover the question, "
    "say so. Be concise and specific, reference tokens by their $SYMBOL, and "
    "explain the reasoning from the scores/metrics shown. Always end by "
    "reminding the user this is not financial advice and these tokens are "
    "high-risk."
)


def provider() -> Optional[str]:
    """Which LLM backend is configured (gemini preferred), or None."""
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return None


def is_enabled() -> bool:
    return provider() is not None


def _call_gemini(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={key}")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_groq(prompt: str) -> str:
    key = os.environ["GROQ_API_KEY"]
    url = "https://api.groq.com/openai/v1/chat/completions"
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
    }
    r = requests.post(url, headers={"Authorization": f"Bearer {key}"},
                     json=body, timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def build_context(signals, positions: Optional[List[Tuple]] = None) -> str:
    """Compact factual context the LLM must ground its answer in.

    `signals` is a list of EntrySignal; `positions` is a list of
    (Position, pnl_pct) tuples.
    """
    lines = ["=== LIVE MOMENTUM SCAN (top candidates, $1M+ market cap) ==="]
    if not signals:
        lines.append("(no candidates cleared the bar right now)")
    for s in signals:
        snap = s.snapshot
        lines.append(
            f"${snap.symbol}: score={s.score} verdict={s.verdict.value} "
            f"MC=${snap.market_cap:,.0f} liq=${snap.liquidity:,.0f} "
            f"vol24=${snap.volume_h24:,.0f} 1h={snap.change_h1:+.0f}% "
            f"6h={snap.change_h6:+.0f}% buys1h={snap.buy_ratio('h1'):.0%}"
            + (f" | {'; '.join(s.reasons)}" if s.reasons else "")
            + (f" | flags: {'; '.join(s.flags)}" if s.flags else "")
        )
    if positions:
        lines.append("")
        lines.append("=== USER'S TRACKED POSITIONS ===")
        for pos, pnl in positions:
            lines.append(
                f"${pos.symbol}: pnl={pnl:+.0f}% entry_mc=${pos.entry_mc:,.0f} "
                f"stop=-{pos.stop_loss_pct:.0f}% target=+{pos.take_profit_pct:.0f}%"
            )
    return "\n".join(lines)


def answer(question: str, context: str) -> str:
    """Answer a question grounded in `context`. Raises if no provider set."""
    p = provider()
    if p is None:
        raise RuntimeError("No LLM provider configured")
    prompt = (f"{SYSTEM}\n\nDATA:\n{context}\n\n"
              f"USER QUESTION: {question}\n\nAnswer:")
    if p == "gemini":
        return _call_gemini(prompt)
    return _call_groq(prompt)
