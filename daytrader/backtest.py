"""Intraday backtester for NSE equities.

Rules it models, deliberately on the conservative side:

* A signal on a bar's close fills at the NEXT bar's open, plus slippage.
* If a bar touches both the stop and the target, the stop is assumed first.
* A gap through the stop fills at the bar's open (worse than the stop).
* All open positions are squared off at the first bar at or after
  RiskConfig.square_off_at, at that bar's open.
* Realized plus open losses beyond the daily loss limit close everything and
  stop new entries for the day.
* Every round trip pays the full charge schedule (brokerage, STT, exchange,
  SEBI, GST, stamp duty).

It is not a guarantee: real fills, partial fills, circuit limits, auction
sessions and API outages are not modelled. Paper trade before going live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable

from .costs import ChargeSchedule, round_trip_charges
from .data import group_by_day
from .market_calendar import NSECalendar
from .models import Bar, Position, Signal, Trade
from .risk import RiskConfig, RiskManager
from .strategies.base import Strategy


@dataclass
class Skipped:
    time: datetime
    symbol: str
    side: str
    reason: str


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    daily_net: dict[date, float] = field(default_factory=dict)
    halted_days: list[date] = field(default_factory=list)
    days_tested: int = 0
    non_trading_days_in_data: list[date] = field(default_factory=list)


class Backtester:
    def __init__(self, strategy: Strategy, risk: RiskConfig | None = None,
                 charges: ChargeSchedule | None = None, slippage_bps: float = 2.0,
                 calendar: NSECalendar | None = None):
        self.strategy = strategy
        self.risk_cfg = risk or RiskConfig()
        self.charges = charges or ChargeSchedule()
        self.slip = slippage_bps / 10_000
        self.calendar = calendar or NSECalendar()

    # ---- fills ---------------------------------------------------------
    def _fill(self, price: float, side: str) -> float:
        """Adverse slippage: buys fill higher, sells fill lower."""
        return price * (1 + self.slip) if side == "BUY" else price * (1 - self.slip)

    def _close(self, pos: Position, raw_price: float, when: datetime, reason: str,
               slip: bool = True) -> Trade:
        exit_side = "SELL" if pos.side == "BUY" else "BUY"
        px = self._fill(raw_price, exit_side) if slip else raw_price
        if pos.side == "BUY":
            gross = (px - pos.entry_price) * pos.qty
            ch = round_trip_charges(pos.entry_price * pos.qty, px * pos.qty, self.charges)
        else:
            gross = (pos.entry_price - px) * pos.qty
            ch = round_trip_charges(px * pos.qty, pos.entry_price * pos.qty, self.charges)
        return Trade(pos.symbol, pos.side, pos.qty, pos.entry_time, round(pos.entry_price, 4),
                     when, round(px, 4), reason, round(gross, 2), round(ch.total, 2),
                     pos.reason, ch.as_dict())

    # ---- main loop -----------------------------------------------------
    def run(self, bars: Iterable[Bar]) -> BacktestResult:
        res = BacktestResult()
        rm = RiskManager(self.risk_cfg)
        sq_off = self.risk_cfg.square_off

        for day, day_bars in group_by_day(bars).items():
            if not self.calendar.is_trading_day(day):
                res.non_trading_days_in_data.append(day)
                continue
            res.days_tested += 1
            rm.start_day(day)
            self.strategy.start_day(day)
            pending: dict[str, Signal] = {}
            positions: dict[str, Position] = {}
            last_close: dict[str, float] = {}
            kill = False
            day_net = 0.0

            def finish(pos: Position, raw: float, when: datetime, reason: str, slip: bool = True):
                nonlocal day_net
                tr = self._close(pos, raw, when, reason, slip)
                res.trades.append(tr)
                rm.on_exit(pos.symbol, tr.net_pnl)
                day_net += tr.net_pnl
                del positions[pos.symbol]

            for b in day_bars:
                t = b.timestamp.time()
                sym = b.symbol

                # 1. fill a pending entry at this bar's open
                sig = pending.pop(sym, None)
                if sig and sym not in positions:
                    if kill or t >= sq_off:
                        res.skipped.append(Skipped(b.timestamp, sym, sig.side, "too late or halted"))
                    else:
                        fill = self._fill(b.open, sig.side)
                        gapped = (sig.side == "BUY" and (fill <= sig.stop or (sig.target and fill >= sig.target))) or \
                                 (sig.side == "SELL" and (fill >= sig.stop or (sig.target and fill <= sig.target)))
                        if gapped:
                            res.skipped.append(Skipped(b.timestamp, sym, sig.side, "opened beyond stop or target"))
                        else:
                            d = rm.check_entry(sym, sig.side, t, fill, sig.stop)
                            if d.ok:
                                positions[sym] = Position(sym, sig.side, d.qty, fill, b.timestamp,
                                                          sig.stop, sig.target, sig.reason)
                                rm.on_entry(sym)
                            else:
                                res.skipped.append(Skipped(b.timestamp, sym, sig.side, d.reason))

                # 2. manage an open position on this bar
                pos = positions.get(sym)
                if pos:
                    if kill:
                        finish(pos, b.open, b.timestamp, "daily_loss_limit")
                    elif t >= sq_off:
                        finish(pos, b.open, b.timestamp, "square_off")
                    elif pos.side == "BUY":
                        if b.low <= pos.stop:
                            finish(pos, min(b.open, pos.stop), b.timestamp, "stop")
                        elif pos.target and b.high >= pos.target:
                            finish(pos, max(b.open, pos.target), b.timestamp, "target", slip=False)
                    else:
                        if b.high >= pos.stop:
                            finish(pos, max(b.open, pos.stop), b.timestamp, "stop")
                        elif pos.target and b.low <= pos.target:
                            finish(pos, min(b.open, pos.target), b.timestamp, "target", slip=False)

                last_close[sym] = b.close

                # 3. daily loss limit on realized + open P&L
                if not kill and positions:
                    unreal = sum(((last_close.get(p.symbol, p.entry_price) - p.entry_price) * p.qty
                                  if p.side == "BUY" else
                                  (p.entry_price - last_close.get(p.symbol, p.entry_price)) * p.qty)
                                 for p in positions.values())
                    if rm.unrealized_breach(unreal):
                        kill = True
                        if sym in positions:
                            finish(positions[sym], b.close, b.timestamp, "daily_loss_limit")
                if rm.halted:
                    kill = True

                # 4. ask the strategy for a new entry (fills on the next bar)
                new = self.strategy.on_bar(b)
                if new and not kill and sym not in positions and t < sq_off:
                    pending[sym] = new

            # data ended before square-off: close at the last price seen
            for pos in list(positions.values()):
                finish(pos, last_close.get(pos.symbol, pos.entry_price),
                       day_bars[-1].timestamp, "end_of_data")
            if kill or rm.halted:
                res.halted_days.append(day)
            res.daily_net[day] = round(day_net, 2)

        return res
