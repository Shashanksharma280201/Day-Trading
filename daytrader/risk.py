"""Risk guardrails. Every entry, in backtest, paper or live, goes through here.

The rules are deliberately strict by default:

* position size from a fixed rupee risk per trade (distance to the stop)
* no single position bigger than a share of capital (no leverage by default)
* a hard daily loss limit: once hit, no new entries for the rest of the day
* a cap on trades per day
* no entries in the first minutes after the open or late in the session
* forced square-off before the broker's own auto square-off
* F&O symbols blocked unless explicitly allowed
* an orders-per-second throttle kept well under SEBI's 10 OPS threshold
"""

from __future__ import annotations

import math
import re
import time as _time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, time

from .market_calendar import parse_hhmm

FNO_PATTERN = re.compile(r"(FUT|\d+(CE|PE))$")


@dataclass
class RiskConfig:
    capital: float = 100_000.0
    risk_per_trade_pct: float = 0.5        # % of capital lost if the stop is hit
    max_position_pct: float = 20.0         # max position value as % of capital
    daily_loss_limit_pct: float = 2.0      # stop trading for the day past this loss
    max_trades_per_day: int = 5
    max_open_positions: int = 2
    no_entry_before: str = "09:20"
    no_entry_after: str = "14:45"
    square_off_at: str = "15:10"           # brokers auto square-off MIS around 15:20 to 15:25
    allow_short: bool = True               # intraday short selling (MIS) in the cash segment
    allow_fno: bool = False
    blocked_symbols: list = field(default_factory=list)
    max_orders_per_second: int = 5         # SEBI unregistered-algo threshold is 10

    @classmethod
    def from_dict(cls, d: dict | None) -> "RiskConfig":
        if not d:
            return cls()
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.capital <= 0:
            raise ValueError("capital must be positive")
        if not 0 < self.risk_per_trade_pct <= 5:
            raise ValueError("risk_per_trade_pct must be between 0 and 5")
        if not 0 < self.max_position_pct <= 100:
            raise ValueError("max_position_pct must be between 0 and 100 (no leverage)")
        if not 0 < self.daily_loss_limit_pct <= 10:
            raise ValueError("daily_loss_limit_pct must be between 0 and 10")
        if self.max_orders_per_second >= 10:
            raise ValueError("max_orders_per_second must stay below SEBI's 10 OPS threshold")

    @property
    def entry_start(self) -> time:
        return parse_hhmm(self.no_entry_before)

    @property
    def entry_end(self) -> time:
        return parse_hhmm(self.no_entry_after)

    @property
    def square_off(self) -> time:
        return parse_hhmm(self.square_off_at)


@dataclass
class Decision:
    ok: bool
    qty: int = 0
    reason: str = ""


class RiskManager:
    """Stateful per trading day. Call start_day() at the start of each session."""

    def __init__(self, cfg: RiskConfig):
        cfg.validate()
        self.cfg = cfg
        self.day: date | None = None
        self.realized_today = 0.0
        self.trades_today = 0
        self.open_positions: set[str] = set()
        self.halted = False
        self.halt_reason = ""

    # ---- day lifecycle -------------------------------------------------
    def start_day(self, d: date) -> None:
        self.day = d
        self.realized_today = 0.0
        self.trades_today = 0
        self.open_positions.clear()
        self.halted = False
        self.halt_reason = ""

    @property
    def daily_loss_limit(self) -> float:
        return self.cfg.capital * self.cfg.daily_loss_limit_pct / 100

    # ---- checks --------------------------------------------------------
    def is_fno(self, symbol: str) -> bool:
        return bool(FNO_PATTERN.search(symbol.upper()))

    def size(self, entry: float, stop: float) -> int:
        per_share_risk = abs(entry - stop)
        if per_share_risk <= 0 or entry <= 0:
            return 0
        risk_rupees = self.cfg.capital * self.cfg.risk_per_trade_pct / 100
        by_risk = math.floor(risk_rupees / per_share_risk)
        by_value = math.floor(self.cfg.capital * self.cfg.max_position_pct / 100 / entry)
        return max(0, min(by_risk, by_value))

    def check_entry(self, symbol: str, side: str, t: time, entry: float, stop: float) -> Decision:
        c = self.cfg
        side = side.upper()
        if self.halted:
            return Decision(False, reason=f"halted: {self.halt_reason}")
        if symbol.upper() in {s.upper() for s in c.blocked_symbols}:
            return Decision(False, reason="symbol is on the blocked list")
        if self.is_fno(symbol) and not c.allow_fno:
            return Decision(False, reason="F&O is disabled (allow_fno is false)")
        if side == "SELL" and not c.allow_short:
            return Decision(False, reason="short selling is disabled")
        if side == "BUY" and stop >= entry:
            return Decision(False, reason="long stop must be below entry")
        if side == "SELL" and stop <= entry:
            return Decision(False, reason="short stop must be above entry")
        if t < c.entry_start:
            return Decision(False, reason=f"before {c.no_entry_before}")
        if t >= c.entry_end:
            return Decision(False, reason=f"after {c.no_entry_after}")
        if self.trades_today >= c.max_trades_per_day:
            return Decision(False, reason="max trades per day reached")
        if symbol in self.open_positions:
            return Decision(False, reason="already in a position on this symbol")
        if len(self.open_positions) >= c.max_open_positions:
            return Decision(False, reason="max open positions reached")
        qty = self.size(entry, stop)
        if qty < 1:
            return Decision(False, reason="size rounds to zero shares")
        return Decision(True, qty=qty, reason="ok")

    # ---- state updates -------------------------------------------------
    def on_entry(self, symbol: str) -> None:
        self.trades_today += 1
        self.open_positions.add(symbol)

    def on_exit(self, symbol: str, net_pnl: float) -> None:
        self.open_positions.discard(symbol)
        self.realized_today += net_pnl
        if self.realized_today <= -self.daily_loss_limit and not self.halted:
            self.halted = True
            self.halt_reason = (f"daily loss limit hit ({self.realized_today:,.2f} "
                                f"<= -{self.daily_loss_limit:,.2f})")

    def unrealized_breach(self, unrealized: float) -> bool:
        """True when realized plus open losses already exceed the daily limit."""
        return self.realized_today + unrealized <= -self.daily_loss_limit


class OrderThrottle:
    """Blocks until sending another order keeps us under max_per_second."""

    def __init__(self, max_per_second: int, clock=_time.monotonic, sleep=_time.sleep):
        if max_per_second >= 10:
            raise ValueError("stay below SEBI's 10 orders per second threshold")
        self.max = max_per_second
        self.clock = clock
        self.sleep = sleep
        self.sent: deque[float] = deque()

    def wait(self) -> None:
        while True:
            now = self.clock()
            while self.sent and now - self.sent[0] >= 1.0:
                self.sent.popleft()
            if len(self.sent) < self.max:
                self.sent.append(now)
                return
            self.sleep(1.0 - (now - self.sent[0]) + 0.001)
