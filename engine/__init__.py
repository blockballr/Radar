"""Radar signal engine — host-agnostic core.

Discovery + scoring live here with no Telegram or hosting dependencies, so
the same code runs from the CLI, a cron loop, or the bot.
"""

from .discovery import discover, fetch_top_by_volume, fetch_trending
from .models import Position, TokenSnapshot
from .signals import (
    Config,
    EntrySignal,
    ExitAction,
    ExitSignal,
    Verdict,
    evaluate_exit,
    score_entry,
)

__all__ = [
    "discover",
    "fetch_trending",
    "fetch_top_by_volume",
    "TokenSnapshot",
    "Position",
    "Config",
    "Verdict",
    "EntrySignal",
    "score_entry",
    "ExitAction",
    "ExitSignal",
    "evaluate_exit",
]
