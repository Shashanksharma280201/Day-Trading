"""Paper broker: fills orders against the latest price you pass in, applies
slippage and the full charge schedule, and keeps positions and a ledger in
memory. No network, no keys, no real money."""

from __future__ import annotations

import itertools
from typing import Optional

from ..costs import ChargeSchedule, order_charges
from .base import Broker, Order, OrderResult


class PaperBroker(Broker):
    is_live = False

    def __init__(self, cash: float, charges: ChargeSchedule | None = None, slippage_bps: float = 2.0):
        self.cash = cash
        self.charges = charges or ChargeSchedule()
        self.slip = slippage_bps / 10_000
        self._pos: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self.ledger: list[dict] = []
        self.total_charges = 0.0

    def place_order(self, order: Order, ltp: Optional[float] = None) -> OrderResult:
        order.validate()
        if order.order_type != "MARKET":
            return OrderResult(False, status="REJECTED",
                               message="paper broker fills MARKET orders only; stops are managed by the engine")
        if not ltp or ltp <= 0:
            return OrderResult(False, status="REJECTED", message="no price to fill against")
        px = ltp * (1 + self.slip) if order.side == "BUY" else ltp * (1 - self.slip)
        value = px * order.qty
        ch = order_charges(order.side, value, self.charges).total
        signed = order.qty if order.side == "BUY" else -order.qty

        p = self._pos.setdefault(order.symbol, {"qty": 0, "avg": 0.0, "realized": 0.0})
        old = p["qty"]
        new = old + signed
        if old == 0 or (old > 0) == (signed > 0):  # opening or adding
            p["avg"] = (p["avg"] * abs(old) + px * abs(signed)) / abs(new)
        else:  # reducing, closing or flipping
            closed = min(abs(old), abs(signed))
            p["realized"] += (px - p["avg"]) * closed * (1 if old > 0 else -1)
            if new != 0 and (new > 0) != (old > 0):
                p["avg"] = px
        p["qty"] = new
        if new == 0:
            p["avg"] = 0.0

        self.cash -= signed * px + ch
        self.total_charges += ch
        oid = f"PAPER-{next(self._ids)}"
        self.ledger.append({"id": oid, "symbol": order.symbol, "side": order.side, "qty": order.qty,
                            "price": round(px, 4), "charges": round(ch, 2), "tag": order.tag})
        return OrderResult(True, oid, "COMPLETE", round(px, 4))

    def cancel_order(self, order_id: str) -> OrderResult:
        return OrderResult(False, order_id, "REJECTED", message="paper market orders fill instantly")

    def positions(self) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._pos.items()}
