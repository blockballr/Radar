"""Normalized token data model shared across the Radar signal engine.

Everything the scanner and signal engine reason about flows through
`TokenSnapshot`. Discovery sources (GeckoTerminal, DexScreener, ...) each
provide a small adapter that produces one of these, so the scoring logic
never has to know which API the data came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _f(value, default: float = 0.0) -> float:
    """Coerce API values (often strings or None) to float, never raising."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TokenSnapshot:
    """A point-in-time view of one token/pool, normalized across sources."""

    address: str                     # base token mint address
    symbol: str
    name: str = ""
    price: float = 0.0

    market_cap: float = 0.0          # falls back to FDV when MC is unknown
    fdv: float = 0.0
    liquidity: float = 0.0           # USD in the pool reserve

    volume_m5: float = 0.0
    volume_h1: float = 0.0
    volume_h6: float = 0.0
    volume_h24: float = 0.0

    change_m5: float = 0.0           # percent, e.g. 12.5 == +12.5%
    change_h1: float = 0.0
    change_h6: float = 0.0
    change_h24: float = 0.0

    buys_m5: int = 0
    sells_m5: int = 0
    buys_h1: int = 0
    sells_h1: int = 0
    buys_h24: int = 0
    sells_h24: int = 0

    pool_created_at: Optional[datetime] = None
    source: str = ""
    pool_address: str = ""

    # ---- derived helpers -------------------------------------------------

    @property
    def age_hours(self) -> Optional[float]:
        if self.pool_created_at is None:
            return None
        now = datetime.now(timezone.utc)
        return (now - self.pool_created_at).total_seconds() / 3600.0

    @property
    def liq_to_mc(self) -> float:
        if self.market_cap <= 0:
            return 0.0
        return self.liquidity / self.market_cap

    @property
    def turnover_h24(self) -> float:
        """24h volume relative to market cap - how much of the cap traded."""
        if self.market_cap <= 0:
            return 0.0
        return self.volume_h24 / self.market_cap

    @property
    def vol_accel(self) -> float:
        """Recent hourly volume vs the trailing 24h hourly average.

        >1 means trading is accelerating right now; <1 means cooling off.
        """
        hourly_avg = self.volume_h24 / 24.0
        if hourly_avg <= 0:
            return 0.0
        return self.volume_h1 / hourly_avg

    def buy_ratio(self, window: str = "h1") -> float:
        """Fraction of trades that were buys in the given window (0..1)."""
        buys = getattr(self, f"buys_{window}", 0)
        sells = getattr(self, f"sells_{window}", 0)
        total = buys + sells
        if total <= 0:
            return 0.5  # neutral when there is no data
        return buys / total

    @property
    def dexscreener_url(self) -> str:
        return f"https://dexscreener.com/solana/{self.pool_address or self.address}"

    # ---- adapters --------------------------------------------------------

    @classmethod
    def from_geckoterminal(cls, pool: dict, tokens_by_id: dict) -> "TokenSnapshot":
        """Build a snapshot from one GeckoTerminal pool object.

        `tokens_by_id` maps the `included` token ids to their attributes so
        we can resolve the base token's mint address and symbol.
        """
        attr = pool.get("attributes", {})
        rel = pool.get("relationships", {})

        base_id = (
            rel.get("base_token", {}).get("data", {}).get("id", "")
        )
        base = tokens_by_id.get(base_id, {})
        # GeckoTerminal omits `included` unless asked; the relationship id is
        # `<network>_<mint>`, so the mint is recoverable even without it.
        base_addr = base.get("address", "")
        if not base_addr and "_" in base_id:
            base_addr = base_id.split("_", 1)[1]
        symbol = base.get("symbol") or attr.get("name", "?").split("/")[0].strip()

        pc = attr.get("price_change_percentage", {}) or {}
        vol = attr.get("volume_usd", {}) or {}
        txns = attr.get("transactions", {}) or {}

        def tx(window, side):
            return _i((txns.get(window) or {}).get(side))

        created = None
        raw_created = attr.get("pool_created_at")
        if raw_created:
            try:
                created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
            except ValueError:
                created = None

        mc = _f(attr.get("market_cap_usd"))
        fdv = _f(attr.get("fdv_usd"))

        return cls(
            address=base_addr,
            symbol=symbol,
            name=base.get("name", ""),
            price=_f(attr.get("base_token_price_usd")),
            market_cap=mc if mc > 0 else fdv,
            fdv=fdv,
            liquidity=_f(attr.get("reserve_in_usd")),
            volume_m5=_f(vol.get("m5")),
            volume_h1=_f(vol.get("h1")),
            volume_h6=_f(vol.get("h6")),
            volume_h24=_f(vol.get("h24")),
            change_m5=_f(pc.get("m5")),
            change_h1=_f(pc.get("h1")),
            change_h6=_f(pc.get("h6")),
            change_h24=_f(pc.get("h24")),
            buys_m5=tx("m5", "buys"),
            sells_m5=tx("m5", "sells"),
            buys_h1=tx("h1", "buys"),
            sells_h1=tx("h1", "sells"),
            buys_h24=tx("h24", "buys"),
            sells_h24=tx("h24", "sells"),
            pool_created_at=created,
            source="geckoterminal",
            pool_address=attr.get("address", ""),
        )


@dataclass
class Position:
    """A tracked (paper) position the agent babysits for exit signals."""

    address: str
    symbol: str
    entry_price: float
    entry_mc: float
    entry_time: datetime
    peak_price: float = 0.0          # highest price seen since entry
    peak_mc: float = 0.0
    # per-position risk parameters (percent)
    take_profit_pct: float = 50.0
    stop_loss_pct: float = 25.0
    trailing_pct: float = 20.0
    notes: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.peak_price <= 0:
            self.peak_price = self.entry_price
        if self.peak_mc <= 0:
            self.peak_mc = self.entry_mc

    def to_dict(self) -> dict:
        d = {
            "address": self.address,
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "entry_mc": self.entry_mc,
            "entry_time": self.entry_time.isoformat(),
            "peak_price": self.peak_price,
            "peak_mc": self.peak_mc,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "trailing_pct": self.trailing_pct,
            "notes": self.notes,
            "extra": self.extra,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        et = d.get("entry_time")
        entry_time = (
            datetime.fromisoformat(et) if isinstance(et, str)
            else et or datetime.now(timezone.utc)
        )
        return cls(
            address=d["address"],
            symbol=d.get("symbol", "?"),
            entry_price=float(d["entry_price"]),
            entry_mc=float(d.get("entry_mc", 0) or 0),
            entry_time=entry_time,
            peak_price=float(d.get("peak_price", 0) or 0),
            peak_mc=float(d.get("peak_mc", 0) or 0),
            take_profit_pct=float(d.get("take_profit_pct", 50.0)),
            stop_loss_pct=float(d.get("stop_loss_pct", 25.0)),
            trailing_pct=float(d.get("trailing_pct", 20.0)),
            notes=d.get("notes", ""),
            extra=d.get("extra", {}) or {},
        )
