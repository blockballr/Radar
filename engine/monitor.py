"""Position monitor - the exit side of the agent.

Given a store of tracked positions, refresh each one's live data, run it
through the exit engine, persist the updated trailing high-water mark, and
return the positions that should exit so the caller (bot / cron) can notify.

Kept transport-agnostic: this returns decisions; it does not send messages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

from .discovery import fetch_token
from .models import Position, TokenSnapshot
from .signals import ExitSignal, evaluate_exit
from .store import KVStore

log = logging.getLogger("radar.monitor")

# A fetcher maps a mint address to a fresh snapshot (or None).
Fetcher = Callable[[str], Optional[TokenSnapshot]]


@dataclass
class PositionUpdate:
    user_id: str
    position: Position
    exit_signal: ExitSignal


def check_positions(store: KVStore, fetch: Fetcher = fetch_token) -> List[PositionUpdate]:
    """Evaluate every tracked position; return the ones that should exit.

    Side effect: persists updated peak_price/peak_mc so trailing stops keep
    a valid high-water mark across runs. Positions flagged for a hard exit
    (stop-loss / take-profit / trailing / rug) are auto-removed from the
    store so they are not alerted on twice; advisory MOMENTUM_FADE is left
    in place.
    """
    from .signals import ExitAction  # local import to avoid cycle at top

    updates: List[PositionUpdate] = []
    for user_id, positions in store.all_positions().items():
        changed = False
        survivors: List[Position] = []
        for pos in positions:
            snap = fetch(pos.address)
            if snap is None:
                survivors.append(pos)  # transient fetch miss - keep it
                continue
            ex = evaluate_exit(pos, snap)  # updates pos.peak_* in place
            if ex.should_exit:
                updates.append(PositionUpdate(user_id, pos, ex))
                if ex.action == ExitAction.MOMENTUM_FADE:
                    survivors.append(pos)  # advisory only, keep tracking
                else:
                    changed = True         # hard exit -> drop it
            else:
                survivors.append(pos)
        # persist peaks (and any removals)
        if changed or survivors:
            store.save_positions(user_id, survivors)
        if not survivors:
            store.save_positions(user_id, [])
    return updates
