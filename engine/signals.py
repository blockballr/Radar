"""The Radar signal engine — deterministic entry/exit scoring.

Design principle: every money-relevant decision lives here, in plain,
inspectable Python. The (optional) LLM layer only narrates what this module
decides; it never makes the call. Each result carries human-readable
`reasons` so the bot can always explain *why*.

Nothing here is financial advice — it is transparent momentum heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from .models import Position, TokenSnapshot


# ---- tunable thresholds (a single place to adjust the strategy) ----------

class Config:
    # Universe gates
    MIN_MARKET_CAP = 1_000_000       # the ">$1M performing well" universe
    MAX_MARKET_CAP = 500_000_000     # ignore mega-caps; no memecoin upside
    MIN_LIQUIDITY = 50_000
    MIN_LIQ_TO_MC = 0.02             # <2% liquidity vs cap => rug-prone
    MIN_VOLUME_H24 = 100_000
    MIN_AGE_HOURS = 1.0              # skip the first hour (snipe/rug window)

    # Momentum shape
    PARABOLIC_H1 = 60.0              # +60% in 1h => likely buying the top
    STRONG_ENTER = 70               # score thresholds
    WATCH = 55
    NEUTRAL = 40

    # Exit defaults live on the Position, but a hard liquidity floor here:
    RUG_LIQ_FLOOR = 25_000
    RUG_LIQ_DROP = -50.0            # % liquidity drop vs entry => rug exit


class Verdict(str, Enum):
    STRONG_ENTER = "STRONG_ENTER"
    WATCH = "WATCH"
    NEUTRAL = "NEUTRAL"
    WEAK = "WEAK"
    AVOID = "AVOID"


class ExitAction(str, Enum):
    HOLD = "HOLD"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    STOP_LOSS = "STOP_LOSS"
    MOMENTUM_FADE = "MOMENTUM_FADE"
    RUG_EXIT = "RUG_EXIT"


@dataclass
class EntrySignal:
    snapshot: TokenSnapshot
    score: int
    verdict: Verdict
    reasons: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)  # disqualifiers / warnings

    @property
    def is_candidate(self) -> bool:
        return self.verdict in (Verdict.STRONG_ENTER, Verdict.WATCH)


@dataclass
class ExitSignal:
    position: Position
    snapshot: TokenSnapshot
    action: ExitAction
    pnl_pct: float
    drawdown_from_peak_pct: float
    reasons: List[str] = field(default_factory=list)

    @property
    def should_exit(self) -> bool:
        return self.action != ExitAction.HOLD


# ---- entry scoring -------------------------------------------------------

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def score_entry(snap: TokenSnapshot, cfg: Config = Config) -> EntrySignal:
    """Score a token 0-100 for entry attractiveness with explanations."""
    reasons: List[str] = []
    flags: List[str] = []

    # --- hard gates: disqualify unsafe / out-of-universe tokens ----------
    if snap.market_cap < cfg.MIN_MARKET_CAP:
        flags.append(f"MC ${snap.market_cap:,.0f} below $1M universe")
        return EntrySignal(snap, 0, Verdict.AVOID, reasons, flags)
    if snap.market_cap > cfg.MAX_MARKET_CAP:
        flags.append("MC too large for meaningful upside")
        return EntrySignal(snap, 0, Verdict.AVOID, reasons, flags)
    if snap.liquidity < cfg.MIN_LIQUIDITY:
        flags.append(f"Liquidity ${snap.liquidity:,.0f} too thin")
        return EntrySignal(snap, 0, Verdict.AVOID, reasons, flags)
    if snap.liq_to_mc < cfg.MIN_LIQ_TO_MC:
        flags.append(f"Liquidity only {snap.liq_to_mc:.1%} of MC (rug risk)")
        return EntrySignal(snap, 0, Verdict.AVOID, reasons, flags)
    if snap.volume_h24 < cfg.MIN_VOLUME_H24:
        flags.append(f"24h volume ${snap.volume_h24:,.0f} too low")
        return EntrySignal(snap, 0, Verdict.AVOID, reasons, flags)
    if snap.age_hours is not None and snap.age_hours < cfg.MIN_AGE_HOURS:
        flags.append(f"Only {snap.age_hours:.1f}h old (snipe window)")
        return EntrySignal(snap, 0, Verdict.AVOID, reasons, flags)

    # --- component 1: trend (25 pts) -------------------------------------
    # Reward sustained upside across h1 + h6; penalize parabolic h1.
    trend = 0.0
    if snap.change_h6 > 0:
        trend += _clamp(snap.change_h6 / 40.0) * 0.6      # up to 60% of comp
    if snap.change_h1 > 0:
        trend += _clamp(snap.change_h1 / 20.0) * 0.4
    if snap.change_h1 > cfg.PARABOLIC_H1:
        trend *= 0.5
        flags.append(f"+{snap.change_h1:.0f}% in 1h — may be topping")
    trend_pts = trend * 25
    if snap.change_h6 > 0 and snap.change_h1 > 0:
        reasons.append(f"Uptrend: +{snap.change_h1:.0f}% 1h, +{snap.change_h6:.0f}% 6h")
    elif snap.change_h1 < 0 and snap.change_h6 < 0:
        flags.append("Price trending down on 1h & 6h")

    # --- component 2: volume acceleration (25 pts) -----------------------
    accel = snap.vol_accel
    accel_pts = _clamp((accel - 0.8) / 1.7) * 25         # 0.8x..2.5x -> 0..25
    if accel >= 1.3:
        reasons.append(f"Volume accelerating ({accel:.1f}x hourly avg)")
    elif accel < 0.7:
        flags.append(f"Volume cooling ({accel:.1f}x hourly avg)")

    # --- component 3: buy pressure (25 pts) ------------------------------
    br_h1 = snap.buy_ratio("h1")
    br_m5 = snap.buy_ratio("m5")
    buy_pts = (_clamp((br_h1 - 0.45) / 0.25) * 0.7
               + _clamp((br_m5 - 0.45) / 0.25) * 0.3) * 25
    if br_h1 > 0.55:
        reasons.append(f"Buy pressure {br_h1:.0%} of 1h trades")
    elif br_h1 < 0.45:
        flags.append(f"Sell pressure — only {br_h1:.0%} buys (1h)")

    # --- component 4: liquidity & turnover quality (25 pts) --------------
    liq_pts = _clamp((snap.liq_to_mc - 0.02) / 0.13) * 12.5   # 2%..15% -> 0..12.5
    # healthy turnover band ~0.2x..3x; too low = dead, too high = churn/exit
    to = snap.turnover_h24
    if to <= 0:
        turn_pts = 0.0
    elif to < 3:
        turn_pts = _clamp(to / 1.0) * 12.5
    else:
        turn_pts = _clamp(1 - (to - 3) / 5) * 12.5
        flags.append(f"Very high turnover ({to:.1f}x MC) — volatile")
    quality_pts = liq_pts + turn_pts
    if snap.liq_to_mc >= 0.08:
        reasons.append(f"Healthy liquidity ({snap.liq_to_mc:.0%} of MC)")

    score = round(trend_pts + accel_pts + buy_pts + quality_pts)
    score = int(_clamp(score, 0, 100))

    if score >= cfg.STRONG_ENTER:
        verdict = Verdict.STRONG_ENTER
    elif score >= cfg.WATCH:
        verdict = Verdict.WATCH
    elif score >= cfg.NEUTRAL:
        verdict = Verdict.NEUTRAL
    else:
        verdict = Verdict.WEAK

    return EntrySignal(snap, score, verdict, reasons, flags)


# ---- exit evaluation -----------------------------------------------------

def evaluate_exit(pos: Position, snap: TokenSnapshot, cfg: Config = Config) -> ExitSignal:
    """Decide whether a tracked position should exit, given fresh data.

    The caller is responsible for persisting `pos.peak_price` between checks;
    we update it here so a live loop that saves the position keeps a valid
    trailing high-water mark.
    """
    price = snap.price if snap.price > 0 else pos.entry_price
    if price > pos.peak_price:
        pos.peak_price = price
    if snap.market_cap > pos.peak_mc:
        pos.peak_mc = snap.market_cap

    pnl = (price / pos.entry_price - 1) * 100 if pos.entry_price > 0 else 0.0
    dd = (price / pos.peak_price - 1) * 100 if pos.peak_price > 0 else 0.0

    reasons: List[str] = []

    # 1) Rug / liquidity collapse — highest priority, exit immediately.
    liq_change = 0.0
    if pos.entry_mc > 0:
        liq_change = (snap.market_cap / pos.entry_mc - 1) * 100
    if snap.liquidity > 0 and snap.liquidity < cfg.RUG_LIQ_FLOOR:
        reasons.append(f"Liquidity collapsed to ${snap.liquidity:,.0f}")
        return ExitSignal(pos, snap, ExitAction.RUG_EXIT, pnl, dd, reasons)

    # 2) Hard stop-loss.
    if pnl <= -pos.stop_loss_pct:
        reasons.append(f"Down {pnl:.0f}% — stop-loss ({pos.stop_loss_pct:.0f}%) hit")
        return ExitSignal(pos, snap, ExitAction.STOP_LOSS, pnl, dd, reasons)

    # 3) Trailing stop once we are in profit and rolling over from the peak.
    if pos.peak_price > pos.entry_price and dd <= -pos.trailing_pct:
        reasons.append(
            f"Down {dd:.0f}% from peak (trailing {pos.trailing_pct:.0f}%); "
            f"still {pnl:+.0f}% overall"
        )
        return ExitSignal(pos, snap, ExitAction.TRAILING_STOP, pnl, dd, reasons)

    # 4) Take-profit target.
    if pnl >= pos.take_profit_pct:
        reasons.append(f"Up {pnl:.0f}% — take-profit ({pos.take_profit_pct:.0f}%) reached")
        return ExitSignal(pos, snap, ExitAction.TAKE_PROFIT, pnl, dd, reasons)

    # 5) Momentum fade — advisory, only when already in profit.
    if pnl > 10 and snap.buy_ratio("h1") < 0.45 and snap.change_h1 < -5:
        reasons.append(
            f"Momentum fading: {snap.buy_ratio('h1'):.0%} buys, "
            f"{snap.change_h1:.0f}% 1h — consider trimming ({pnl:+.0f}%)"
        )
        return ExitSignal(pos, snap, ExitAction.MOMENTUM_FADE, pnl, dd, reasons)

    reasons.append(f"Holding: {pnl:+.0f}% (peak {(pos.peak_price/pos.entry_price-1)*100:+.0f}%)")
    return ExitSignal(pos, snap, ExitAction.HOLD, pnl, dd, reasons)
