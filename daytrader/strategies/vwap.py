"""VWAP cross.

VWAP (volume-weighted average price) is computed from the session open using
the typical price (high + low + close) / 3. After `warmup_minutes`:

* a close above VWAP after the previous close was below it is a long signal
* a close below VWAP after the previous close was above it is a short signal

Stop: `stop_pct` percent beyond the entry. Target: `reward_risk` times the risk.
Needs volume in the data; bars with zero volume do not move VWAP.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from ..market_calendar import MARKET_OPEN
from ..models import Bar, Signal
from .base import Strategy


class VWAPCross(Strategy):
    name = "vwap"

    def __init__(self, warmup_minutes: int = 15, stop_pct: float = 0.5,
                 reward_risk: float = 2.0, max_signals_per_day: int = 2,
                 allow_short: bool = True):
        self.warmup_minutes = warmup_minutes
        self.stop_pct = stop_pct
        self.reward_risk = reward_risk
        self.max_signals_per_day = max_signals_per_day
        self.allow_short = allow_short
        self._state: dict[str, dict] = {}
        self._warm_end = time(9, 15)

    def start_day(self, d: date) -> None:
        self._state = {}
        self._warm_end = (datetime.combine(d, MARKET_OPEN)
                          + timedelta(minutes=self.warmup_minutes)).time()

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        st = self._state.setdefault(bar.symbol, {"pv": 0.0, "v": 0.0, "prev_side": None, "signals": 0})
        tp = (bar.high + bar.low + bar.close) / 3
        st["pv"] += tp * bar.volume
        st["v"] += bar.volume
        if st["v"] <= 0:
            return None
        vwap = st["pv"] / st["v"]
        side = "above" if bar.close > vwap else "below" if bar.close < vwap else st["prev_side"]
        prev, st["prev_side"] = st["prev_side"], side

        if bar.timestamp.time() < self._warm_end or prev is None:
            return None
        if st["signals"] >= self.max_signals_per_day:
            return None

        risk = bar.close * self.stop_pct / 100
        if prev == "below" and side == "above":
            st["signals"] += 1
            return Signal(bar.symbol, "BUY", stop=round(bar.close - risk, 2),
                          target=round(bar.close + self.reward_risk * risk, 2),
                          reason=f"VWAP long: close {bar.close} crossed above {vwap:.2f}")
        if prev == "above" and side == "below" and self.allow_short:
            st["signals"] += 1
            return Signal(bar.symbol, "SELL", stop=round(bar.close + risk, 2),
                          target=round(bar.close - self.reward_risk * risk, 2),
                          reason=f"VWAP short: close {bar.close} crossed below {vwap:.2f}")
        return None
