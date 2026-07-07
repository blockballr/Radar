"""Radar signal engine - host-agnostic core.

Discovery + scoring live here with no Telegram or hosting dependencies, so
the same code runs from the CLI, a cron loop, or the bot.
"""

from .chat import answer as chat_answer
from .chat import build_context as build_chat_context
from .chat import is_enabled as chat_enabled
from .chat import provider as chat_provider
from .discovery import discover, fetch_token, fetch_top_by_volume, fetch_trending
from .models import Position, TokenSnapshot
from .monitor import PositionUpdate, check_positions
from .pulse import PulseAlert, PulseConfig, find_fast_movers
from .signals import (
    Config,
    EntrySignal,
    ExitAction,
    ExitSignal,
    Verdict,
    evaluate_exit,
    score_entry,
)
from .store import JsonStore, KVStore, UpstashStore, get_store

__all__ = [
    "discover",
    "fetch_trending",
    "fetch_top_by_volume",
    "fetch_token",
    "TokenSnapshot",
    "Position",
    "Config",
    "Verdict",
    "EntrySignal",
    "score_entry",
    "ExitAction",
    "ExitSignal",
    "evaluate_exit",
    "check_positions",
    "PositionUpdate",
    "find_fast_movers",
    "PulseAlert",
    "PulseConfig",
    "chat_enabled",
    "chat_answer",
    "build_chat_context",
    "chat_provider",
    "get_store",
    "KVStore",
    "JsonStore",
    "UpstashStore",
]
