"""Plain data types shared across the package."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Bar:
    timestamp: datetime  # bar start time, IST
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Signal:
    """An entry idea from a strategy. The engine decides whether it is taken."""
    symbol: str
    side: str            # "BUY" (go long) or "SELL" (go short)
    stop: float          # protective stop price
    target: Optional[float] = None
    reason: str = ""


@dataclass
class Position:
    symbol: str
    side: str            # "BUY" = long, "SELL" = short
    qty: int
    entry_price: float
    entry_time: datetime
    stop: float
    target: Optional[float]
    reason: str = ""


@dataclass
class Trade:
    symbol: str
    side: str
    qty: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    exit_reason: str
    gross_pnl: float
    charges: float
    entry_reason: str = ""
    charge_detail: dict = field(default_factory=dict)

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.charges

    @property
    def turnover(self) -> float:
        return self.qty * (self.entry_price + self.exit_price)
