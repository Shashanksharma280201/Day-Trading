"""Broker interface. The live engine talks only to this, so switching between
paper trading and a real broker (via OpenAlgo, Kite Connect, DhanHQ or Groww)
is a config change, not a code change.

SEBI retail algo rules that every live implementation must respect:
* API orders come from the static IP registered with the broker
* market orders sent via API need a non-zero market protection percentage
* stay under 10 orders per second (see risk.OrderThrottle)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Order:
    symbol: str
    side: str                       # "BUY" or "SELL"
    qty: int
    order_type: str = "MARKET"      # MARKET, LIMIT, SL, SL-M
    price: Optional[float] = None   # limit price
    trigger: Optional[float] = None  # stop trigger
    product: str = "MIS"            # MIS = intraday, auto squared off by the broker
    exchange: str = "NSE"
    market_protection_pct: float = 1.0
    tag: str = "daytrader"

    def validate(self) -> None:
        if self.side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if self.qty < 1:
            raise ValueError("qty must be at least 1")
        if self.order_type == "LIMIT" and not self.price:
            raise ValueError("LIMIT order needs a price")
        if self.order_type in ("SL", "SL-M") and not self.trigger:
            raise ValueError("stop order needs a trigger")
        if self.order_type == "MARKET" and self.market_protection_pct <= 0:
            raise ValueError("API market orders need market protection above 0 (SEBI/exchange rule)")


@dataclass
class OrderResult:
    ok: bool
    order_id: str = ""
    status: str = ""
    fill_price: Optional[float] = None
    message: str = ""
    time: datetime = field(default_factory=datetime.now)


class Broker(ABC):
    is_live: bool = False

    @abstractmethod
    def place_order(self, order: Order, ltp: Optional[float] = None) -> OrderResult: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> OrderResult: ...

    @abstractmethod
    def positions(self) -> dict[str, dict]: ...

    def square_off_all(self, ltps: dict[str, float]) -> list[OrderResult]:
        out = []
        for sym, p in self.positions().items():
            qty = p["qty"]
            if qty == 0:
                continue
            side = "SELL" if qty > 0 else "BUY"
            out.append(self.place_order(Order(sym, side, abs(qty), tag="square_off"), ltp=ltps.get(sym)))
        return out
