"""Autonomous "fast mover" detector.

Finds tokens spiking hard in a short window **on surging volume** - the kind
of move you'd want pinged to you in real time without having to run /scan.
Pure and stateless so it's easy to test; the bot layer handles who to notify
and the per-token cooldown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .models import TokenSnapshot


class PulseConfig:
    # Universe / safety
    MIN_MARKET_CAP = 300_000       # allow smaller caps than /scan (they move fast)
    MAX_MARKET_CAP = 500_000_000
    MIN_LIQUIDITY = 30_000
    MIN_VOLUME_H1 = 50_000         # needs real recent volume, not a dead ghost

    # "Moving fast" - a spike in a SHORT window
    SPIKE_M5 = 12.0                # +12% in 5 minutes, or...
    SPIKE_H1 = 35.0                # +35% in 1 hour

    # "On volume" - trading well above its own recent pace
    MIN_VOL_ACCEL = 2.5            # last hour >= 2.5x the 24h hourly average

    # Real buyers, not just a wick
    MIN_BUY_RATIO = 0.55


@dataclass
class PulseAlert:
    snapshot: TokenSnapshot
    trigger: str      # human-readable reason, e.g. "+18% in 5m on 4.1x volume"
    heat: float       # ranking score (bigger = hotter)


def find_fast_movers(snapshots: List[TokenSnapshot],
                     cfg: PulseConfig = PulseConfig) -> List[PulseAlert]:
    """Return tokens spiking fast on rising volume, hottest first."""
    alerts: List[PulseAlert] = []
    for s in snapshots:
        if not (cfg.MIN_MARKET_CAP <= s.market_cap <= cfg.MAX_MARKET_CAP):
            continue
        if s.liquidity < cfg.MIN_LIQUIDITY:
            continue
        if s.volume_h1 < cfg.MIN_VOLUME_H1:
            continue

        accel = s.vol_accel
        fast = s.change_m5 >= cfg.SPIKE_M5 or s.change_h1 >= cfg.SPIKE_H1
        surging = accel >= cfg.MIN_VOL_ACCEL
        buying = s.buy_ratio("h1") >= cfg.MIN_BUY_RATIO
        if not (fast and surging and buying):
            continue

        bits = []
        if s.change_m5 >= cfg.SPIKE_M5:
            bits.append(f"+{s.change_m5:.0f}% in 5m")
        if s.change_h1 >= cfg.SPIKE_H1:
            bits.append(f"+{s.change_h1:.0f}% in 1h")
        trigger = " · ".join(bits) + f" on {accel:.1f}x volume"
        # rank by how much it's accelerating and how sharp the short move is
        heat = accel * max(s.change_m5, s.change_h1 / 3.0)
        alerts.append(PulseAlert(s, trigger, heat))

    alerts.sort(key=lambda a: a.heat, reverse=True)
    return alerts
