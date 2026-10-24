"""Opening Range Breakout (ORB).

1. Record the high and low of the first `range_minutes` of the session.
2. After the range is set, a bar that CLOSES above the range high is a long
   signal; a close below the range low is a short signal.
3. Stop: the opposite side of the range (or the range midpoint with
   stop_at_mid). Target: `reward_risk` times the risk.
4. At most `max_signals_per_day` signals per symbol per day.

Filters skip days where the range is too narrow (noise) or too wide (the stop
would be huge) as a percent of price.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from ..market_calendar import MARKET_OPEN
from ..models import Bar, Signal
from .base import Strategy


class OpeningRangeBreakout(Strategy):
    name = "orb"

    def __init__(self, range_minutes: int = 15, reward_risk: float = 2.0,
                 stop_at_mid: bool = False, min_range_pct: float = 0.3,
                 max_range_pct: float = 2.5, max_signals_per_day: int = 1,
                 allow_short: bool = True):
        self.range_minutes = range_minutes
        self.reward_risk = reward_risk
        self.stop_at_mid = stop_at_mid
        self.min_range_pct = min_range_pct
        self.max_range_pct = max_range_pct
        self.max_signals_per_day = max_signals_per_day
        self.allow_short = allow_short
        self._state: dict[str, dict] = {}
        self._range_end = time(9, 15)

    def start_day(self, d: date) -> None:
        self._state = {}
        self._range_end = (datetime.combine(d, MARKET_OPEN)
                           + timedelta(minutes=self.range_minutes)).time()

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        st = self._state.setdefault(bar.symbol, {"hi": None, "lo": None, "signals": 0, "valid": None})
        t = bar.timestamp.time()
        if t < self._range_end:
            st["hi"] = bar.high if st["hi"] is None else max(st["hi"], bar.high)
            st["lo"] = bar.low if st["lo"] is None else min(st["lo"], bar.low)
            return None
        if st["hi"] is None or st["signals"] >= self.max_signals_per_day:
            return None
        hi, lo = st["hi"], st["lo"]
        if st["valid"] is None:
            width_pct = (hi - lo) / lo * 100 if lo > 0 else 0
            st["valid"] = self.min_range_pct <= width_pct <= self.max_range_pct
        if not st["valid"]:
            return None

        mid = (hi + lo) / 2
        if bar.close > hi:
            stop = mid if self.stop_at_mid else lo
            risk = bar.close - stop
            st["signals"] += 1
            return Signal(bar.symbol, "BUY", stop=round(stop, 2),
                          target=round(bar.close + self.reward_risk * risk, 2),
                          reason=f"ORB long: close {bar.close} > range high {hi}")
        if bar.close < lo and self.allow_short:
            stop = mid if self.stop_at_mid else hi
            risk = stop - bar.close
            st["signals"] += 1
            return Signal(bar.symbol, "SELL", stop=round(stop, 2),
                          target=round(bar.close - self.reward_risk * risk, 2),
                          reason=f"ORB short: close {bar.close} < range low {lo}")
        return None
