"""Transaction costs for NSE equity intraday (MIS) trades.

Defaults follow Zerodha's published equity intraday charges as of October 2026:

    brokerage      0.03% or Rs 20 per executed order, whichever is lower
    STT            0.025% on the sell side
    NSE txn charge 0.00307% of turnover
    SEBI fee       Rs 10 per crore of turnover
    GST            18% on (brokerage + exchange charge + SEBI fee)
    stamp duty     0.003% on the buy side

Other brokers differ mainly in brokerage. Change the ChargeSchedule fields in
config.json to match yours. Check your broker's charges page before trusting
any backtest: costs are the single biggest reason intraday strategies fail.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

CRORE = 10_000_000


@dataclass(frozen=True)
class ChargeSchedule:
    brokerage_pct: float = 0.0003
    brokerage_cap: float = 20.0
    stt_sell_pct: float = 0.00025
    exchange_pct: float = 0.0000307
    sebi_per_crore: float = 10.0
    gst_pct: float = 0.18
    stamp_buy_pct: float = 0.00003

    @classmethod
    def from_dict(cls, d: dict | None) -> "ChargeSchedule":
        if not d:
            return cls()
        known = {k: float(v) for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Charges:
    brokerage: float = 0.0
    stt: float = 0.0
    exchange: float = 0.0
    sebi: float = 0.0
    gst: float = 0.0
    stamp: float = 0.0

    @property
    def total(self) -> float:
        return self.brokerage + self.stt + self.exchange + self.sebi + self.gst + self.stamp

    def __add__(self, other: "Charges") -> "Charges":
        return Charges(**{k: getattr(self, k) + getattr(other, k) for k in asdict(self)})

    def as_dict(self) -> dict:
        d = {k: round(v, 2) for k, v in asdict(self).items()}
        d["total"] = round(self.total, 2)
        return d


def order_charges(side: str, value: float, sched: ChargeSchedule = ChargeSchedule()) -> Charges:
    """Charges for one executed order. side is 'BUY' or 'SELL', value in rupees."""
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if value < 0:
        raise ValueError("order value cannot be negative")
    brokerage = min(value * sched.brokerage_pct, sched.brokerage_cap)
    exchange = value * sched.exchange_pct
    sebi = value * sched.sebi_per_crore / CRORE
    gst = (brokerage + exchange + sebi) * sched.gst_pct
    stt = value * sched.stt_sell_pct if side == "SELL" else 0.0
    stamp = value * sched.stamp_buy_pct if side == "BUY" else 0.0
    return Charges(brokerage, stt, exchange, sebi, gst, stamp)


def round_trip_charges(buy_value: float, sell_value: float,
                       sched: ChargeSchedule = ChargeSchedule()) -> Charges:
    """Charges for a buy plus a sell (either order: long or short intraday)."""
    return order_charges("BUY", buy_value, sched) + order_charges("SELL", sell_value, sched)


def breakeven_move_pct(position_value: float, sched: ChargeSchedule = ChargeSchedule()) -> float:
    """Percent the price must move for a round trip of this size to cover costs."""
    if position_value <= 0:
        raise ValueError("position value must be positive")
    return round_trip_charges(position_value, position_value, sched).total / position_value * 100
