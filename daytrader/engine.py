"""The live engine: strategy signals become PROPOSALS, and only your approval
turns a proposal into an order.

Rules it enforces:

* Entries need an explicit approval from you (island or phone). No answer
  means no trade: a proposal expires after `approval_ttl` seconds.
* An approval is bound to one exact proposal. If the price has moved more
  than `max_drift_pct` since the proposal, it is refused as stale.
* The risk rules are checked again at the moment you approve.
* Exits never wait for you: stops, targets, the square-off time and the daily
  loss limit close positions automatically. In live mode the stop also sits
  at Groww as an SL-M order, so it protects you even if this program dies.
* The kill switch stops new proposals for the rest of the day (and can
  flatten open positions).
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .broker.base import Broker, Order
from .costs import ChargeSchedule, round_trip_charges
from .market_calendar import IST, to_ist
from .models import Bar, Signal, Trade
from .risk import RiskConfig, RiskManager
from .strategies.base import Strategy

Listener = Callable[[dict], None]


@dataclass
class Proposal:
    id: str
    symbol: str
    side: str
    qty: int
    ref_price: float
    stop: float
    target: Optional[float]
    risk_rupees: float
    reason: str
    created_at: float
    expires_at: float
    market_time: str
    status: str = "pending"   # pending, placed, rejected, expired, stale, failed
    decided_by: str = ""
    note: str = ""

    def view(self, now: float) -> dict:
        d = asdict(self)
        d["seconds_left"] = max(0, int(self.expires_at - now)) if self.status == "pending" else 0
        d["value"] = round(self.qty * self.ref_price, 2)
        return d


@dataclass
class LivePosition:
    symbol: str
    side: str
    qty: int
    entry_price: float
    entry_time: datetime
    stop: float
    target: Optional[float]
    reason: str
    proposal_id: str
    stop_order_id: str = ""


@dataclass
class EngineConfig:
    mode: str = "paper"              # paper or live
    approval_ttl: float = 60.0       # seconds you have to answer
    max_drift_pct: float = 0.3       # refuse approval if price moved more than this
    state_dir: str = "state"
    tick_every: float = 1.0          # how often P&L ticks are pushed to clients

    @classmethod
    def from_dict(cls, d: dict | None) -> "EngineConfig":
        d = d or {}
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class Engine:
    def __init__(self, strategy: Strategy, risk: RiskConfig, broker: Broker,
                 cfg: EngineConfig | None = None, charges: ChargeSchedule | None = None,
                 clock: Callable[[], float] = time.time):
        self.strategy = strategy
        self.risk_cfg = risk
        self.rm = RiskManager(risk)
        self.broker = broker
        self.cfg = cfg or EngineConfig()
        self.charges = charges or ChargeSchedule()
        self.clock = clock
        if self.cfg.mode == "live" and not broker.is_live:
            raise ValueError("live mode needs a live broker")
        if self.cfg.mode == "paper" and broker.is_live:
            raise ValueError("paper mode must not use a live broker")

        self.lock = threading.RLock()
        self.listeners: list[Listener] = []
        self.day: Optional[date] = None
        self.market_now: Optional[datetime] = None
        self.last_price: dict[str, float] = {}
        self.positions: dict[str, LivePosition] = {}
        self.proposals: dict[str, Proposal] = {}
        self.trades: list[Trade] = []
        self.killed = False
        self.kill_reason = ""
        self.feed_status = "starting"
        self.feed_detail = ""
        self._last_tick = 0.0
        Path(self.cfg.state_dir).mkdir(parents=True, exist_ok=True)

    # ---- events --------------------------------------------------------
    def subscribe(self, fn: Listener) -> None:
        with self.lock:
            self.listeners.append(fn)

    def unsubscribe(self, fn: Listener) -> None:
        with self.lock:
            if fn in self.listeners:
                self.listeners.remove(fn)

    def _emit(self, kind: str, data: dict, audit: bool = True) -> None:
        ev = {"type": kind, "time": datetime.now(IST).isoformat(timespec="seconds"), "data": data}
        if audit:
            day = (self.day or date.today()).isoformat()
            with open(Path(self.cfg.state_dir) / f"audit-{day}.jsonl", "a") as fh:
                fh.write(json.dumps(ev, default=str) + "\n")
        for fn in list(self.listeners):
            try:
                fn(ev)
            except Exception:
                self.unsubscribe(fn)

    # ---- day handling --------------------------------------------------
    def _roll_day(self, when: datetime) -> None:
        d = when.date()
        if self.day == d:
            return
        for pos in list(self.positions.values()):  # should not happen: square-off runs first
            self._exit(pos, self.last_price.get(pos.symbol, pos.entry_price), when, "end_of_day")
        for p in self.proposals.values():
            if p.status == "pending":
                p.status, p.note = "expired", "new trading day"
        self.day = d
        self.rm.start_day(d)
        self.strategy.start_day(d)
        self.trades = []
        self.proposals = {}
        self.killed, self.kill_reason = False, ""
        self._emit("day_started", {"date": d.isoformat()})

    # ---- feed callbacks ------------------------------------------------
    def on_feed_status(self, status: str, detail: str = "") -> None:
        with self.lock:
            changed = status != self.feed_status
            self.feed_status, self.feed_detail = status, detail
        if changed:
            self._emit("feed", {"status": status, "detail": detail}, audit=status != "live")

    def on_bar(self, bar: Bar) -> None:
        with self.lock:
            self._roll_day(bar.timestamp)
            close_time = bar.timestamp + timedelta(minutes=1)
            self.market_now = max(self.market_now or close_time, close_time)
            self.last_price[bar.symbol] = bar.close
            pos = self.positions.get(bar.symbol)
            if pos:
                self._check_exit(pos, bar.high, bar.low, close_time)
            sig = self.strategy.on_bar(bar)
            if sig:
                self._propose(sig, bar.close, close_time)

    def on_prices(self, prices: dict, now: datetime) -> None:
        now = to_ist(now)
        with self.lock:
            self._roll_day(now)
            self.market_now = max(self.market_now or now, now)
            self.last_price.update({k: float(v) for k, v in prices.items()})
            self._expire_proposals()
            for pos in list(self.positions.values()):
                px = self.last_price.get(pos.symbol)
                if px is not None:
                    self._check_exit(pos, px, px, now)
            if self.positions and self.rm.unrealized_breach(self._unrealized()):
                self.kill("daily loss limit reached", flatten=True, by="risk")
            elif self.rm.halted and not self.killed:
                self.kill(self.rm.halt_reason, flatten=False, by="risk")
            tick_due = self.clock() - self._last_tick >= self.cfg.tick_every
        if tick_due:
            self._last_tick = self.clock()
            self._emit("tick", self.summary(), audit=False)

    # ---- proposals -----------------------------------------------------
    def _propose(self, sig: Signal, price: float, when: datetime) -> None:
        def skip(why: str):
            self._emit("signal_skipped", {"symbol": sig.symbol, "side": sig.side, "why": why})

        if self.killed:
            return skip(f"kill switch on: {self.kill_reason}")
        if sig.symbol in self.positions:
            return skip("already in a position")
        if any(p.symbol == sig.symbol and p.status == "pending" for p in self.proposals.values()):
            return skip("a proposal for this symbol is already waiting")
        d = self.rm.check_entry(sig.symbol, sig.side, when.time(), price, sig.stop)
        if not d.ok:
            return skip(d.reason)
        now = self.clock()
        p = Proposal(
            id=secrets.token_hex(4), symbol=sig.symbol, side=sig.side, qty=d.qty,
            ref_price=round(price, 2), stop=sig.stop, target=sig.target,
            risk_rupees=round(d.qty * abs(price - sig.stop), 2), reason=sig.reason,
            created_at=now, expires_at=now + self.cfg.approval_ttl,
            market_time=when.isoformat(timespec="minutes"),
        )
        self.proposals[p.id] = p
        self._emit("proposal", p.view(now))

    def _expire_proposals(self) -> None:
        now = self.clock()
        for p in self.proposals.values():
            if p.status == "pending" and now >= p.expires_at:
                p.status, p.note = "expired", "no answer in time"
                self._emit("proposal_update", p.view(now))

    def approve(self, pid: str, by: str = "unknown") -> dict:
        with self.lock:
            p = self.proposals.get(pid)
            if not p:
                return {"ok": False, "error": "no such proposal"}
            if p.status != "pending":
                return {"ok": False, "error": f"proposal is already {p.status}", "proposal": p.view(self.clock())}
            now = self.clock()
            if now >= p.expires_at:
                return self._finish(p, "expired", by, "approved too late")
            if self.killed:
                return self._finish(p, "rejected", by, f"kill switch on: {self.kill_reason}")
            cur = self.last_price.get(p.symbol, p.ref_price)
            drift = abs(cur - p.ref_price) / p.ref_price * 100
            if drift > self.cfg.max_drift_pct:
                return self._finish(p, "stale", by, f"price moved {drift:.2f}% since the proposal")
            when = self.market_now or datetime.now(IST)
            d = self.rm.check_entry(p.symbol, p.side, when.time(), cur, p.stop)
            if not d.ok:
                return self._finish(p, "rejected", by, f"risk check failed now: {d.reason}")
            qty = min(d.qty, p.qty)  # never more than you approved
            res = self.broker.place_order(Order(p.symbol, p.side, qty, tag=f"entry-{p.id}"), ltp=cur)
            if not res.ok:
                return self._finish(p, "failed", by, f"broker refused: {res.message or res.status}")
            fill = res.fill_price or cur
            pos = LivePosition(p.symbol, p.side, qty, fill, when, p.stop, p.target, p.reason, p.id)
            self.positions[p.symbol] = pos
            self.rm.on_entry(p.symbol)
            if self.broker.is_live:
                exit_side = "SELL" if p.side == "BUY" else "BUY"
                sl = self.broker.place_order(Order(p.symbol, exit_side, qty, order_type="SL-M",
                                                   trigger=p.stop, tag=f"stop-{p.id}"))
                if sl.ok:
                    pos.stop_order_id = sl.order_id
                else:  # never hold a position without a broker-side stop
                    self._emit("alert", {"message": f"stop order refused for {p.symbol}; closing now"})
                    self._exit(pos, cur, when, "no_broker_stop")
            out = self._finish(p, "placed", by, f"filled {qty} @ {fill:.2f}")
            self._emit("position_opened", self._pos_view(pos))
            return out

    def reject(self, pid: str, by: str = "unknown") -> dict:
        with self.lock:
            p = self.proposals.get(pid)
            if not p:
                return {"ok": False, "error": "no such proposal"}
            if p.status != "pending":
                return {"ok": False, "error": f"proposal is already {p.status}"}
            return self._finish(p, "rejected", by, "you said no")

    def _finish(self, p: Proposal, status: str, by: str, note: str) -> dict:
        p.status, p.decided_by, p.note = status, by, note
        view = p.view(self.clock())
        self._emit("proposal_update", view)
        return {"ok": status == "placed", "proposal": view, **({} if status == "placed" else {"error": note})}

    # ---- exits ---------------------------------------------------------
    def _check_exit(self, pos: LivePosition, high: float, low: float, when: datetime) -> None:
        if when.time() >= self.risk_cfg.square_off:
            return self._exit(pos, self.last_price.get(pos.symbol, low), when, "square_off")
        if pos.side == "BUY":
            if low <= pos.stop:
                return self._exit(pos, pos.stop, when, "stop")
            if pos.target and high >= pos.target:
                return self._exit(pos, pos.target, when, "target")
        else:
            if high >= pos.stop:
                return self._exit(pos, pos.stop, when, "stop")
            if pos.target and low <= pos.target:
                return self._exit(pos, pos.target, when, "target")

    def _exit(self, pos: LivePosition, price: float, when: datetime, reason: str) -> None:
        exit_side = "SELL" if pos.side == "BUY" else "BUY"
        fill = price
        if self.broker.is_live:
            flat = pos.symbol not in self.broker.positions() or \
                self.broker.positions()[pos.symbol]["qty"] == 0
            if reason == "stop" and flat:
                pass  # the broker-side stop already closed it
            else:
                if pos.stop_order_id:
                    self.broker.cancel_order(pos.stop_order_id)
                res = self.broker.place_order(Order(pos.symbol, exit_side, pos.qty, tag=f"exit-{reason}"),
                                              ltp=self.last_price.get(pos.symbol, price))
                if not res.ok:
                    self._emit("alert", {"message": f"EXIT FAILED for {pos.symbol}: {res.message}. "
                                                    f"Close it in the Groww app now."})
                    return
                fill = res.fill_price or price
        else:
            res = self.broker.place_order(Order(pos.symbol, exit_side, pos.qty, tag=f"exit-{reason}"), ltp=price)
            fill = res.fill_price or price
        tr = self._make_trade(pos, fill, when, reason)
        self.trades.append(tr)
        del self.positions[pos.symbol]
        self.rm.on_exit(pos.symbol, tr.net_pnl)
        self._emit("position_closed", self._trade_view(tr))

    def _make_trade(self, pos: LivePosition, px: float, when: datetime, reason: str) -> Trade:
        if pos.side == "BUY":
            gross = (px - pos.entry_price) * pos.qty
            ch = round_trip_charges(pos.entry_price * pos.qty, px * pos.qty, self.charges)
        else:
            gross = (pos.entry_price - px) * pos.qty
            ch = round_trip_charges(px * pos.qty, pos.entry_price * pos.qty, self.charges)
        return Trade(pos.symbol, pos.side, pos.qty, pos.entry_time, round(pos.entry_price, 2), when,
                     round(px, 2), reason, round(gross, 2), round(ch.total, 2), pos.reason, ch.as_dict())

    # ---- kill switch ---------------------------------------------------
    def kill(self, reason: str = "stopped by you", flatten: bool = False, by: str = "you") -> dict:
        with self.lock:
            self.killed, self.kill_reason = True, reason
            now = self.clock()
            for p in self.proposals.values():
                if p.status == "pending":
                    p.status, p.note = "rejected", f"kill switch: {reason}"
                    self._emit("proposal_update", p.view(now))
            when = self.market_now or datetime.now(IST)
            if flatten:
                for pos in list(self.positions.values()):
                    self._exit(pos, self.last_price.get(pos.symbol, pos.entry_price), when, "kill_switch")
            self._emit("killed", {"reason": reason, "by": by, "flattened": flatten})
            return {"ok": True, "killed": True, "reason": reason}

    # ---- views ---------------------------------------------------------
    def _unrealized(self) -> float:
        total = 0.0
        for pos in self.positions.values():
            px = self.last_price.get(pos.symbol, pos.entry_price)
            total += (px - pos.entry_price) * pos.qty if pos.side == "BUY" else (pos.entry_price - px) * pos.qty
        return total

    def _pos_view(self, pos: LivePosition) -> dict:
        px = self.last_price.get(pos.symbol, pos.entry_price)
        upnl = (px - pos.entry_price) * pos.qty if pos.side == "BUY" else (pos.entry_price - px) * pos.qty
        return {"symbol": pos.symbol, "side": pos.side, "qty": pos.qty, "entry_price": pos.entry_price,
                "ltp": px, "stop": pos.stop, "target": pos.target, "unrealized": round(upnl, 2),
                "entry_time": pos.entry_time.isoformat(timespec="minutes"),
                "broker_stop": bool(pos.stop_order_id)}

    @staticmethod
    def _trade_view(t: Trade) -> dict:
        return {"symbol": t.symbol, "side": t.side, "qty": t.qty, "entry_price": t.entry_price,
                "exit_price": t.exit_price, "exit_reason": t.exit_reason, "gross_pnl": t.gross_pnl,
                "charges": t.charges, "net_pnl": round(t.net_pnl, 2),
                "entry_time": t.entry_time.isoformat(timespec="minutes"),
                "exit_time": t.exit_time.isoformat(timespec="minutes")}

    def summary(self) -> dict:
        with self.lock:
            realized = sum(t.net_pnl for t in self.trades)
            unreal = self._unrealized()
            limit = self.rm.daily_loss_limit
            net = realized + unreal
            return {
                "mode": self.cfg.mode,
                "day": self.day.isoformat() if self.day else None,
                "market_time": self.market_now.isoformat(timespec="minutes") if self.market_now else None,
                "net_today": round(net, 2),
                "realized_today": round(realized, 2),
                "unrealized": round(unreal, 2),
                "charges_today": round(sum(t.charges for t in self.trades), 2),
                "trades_today": len(self.trades),
                "open_positions": len(self.positions),
                "pending_approvals": sum(1 for p in self.proposals.values() if p.status == "pending"),
                "daily_loss_limit": round(limit, 2),
                "loss_limit_used_pct": round(max(0.0, -net) / limit * 100, 1) if limit else 0.0,
                "killed": self.killed,
                "kill_reason": self.kill_reason,
                "feed": self.feed_status,
            }

    def state(self) -> dict:
        with self.lock:
            now = self.clock()
            return {
                **self.summary(),
                "feed_detail": self.feed_detail,
                "strategy": {"name": self.strategy.name, "params": self.strategy.params()},
                "capital": self.risk_cfg.capital,
                "positions": [self._pos_view(p) for p in self.positions.values()],
                "proposals": [p.view(now) for p in sorted(self.proposals.values(),
                                                          key=lambda x: x.created_at, reverse=True)][:20],
                "trades": [self._trade_view(t) for t in reversed(self.trades)][:50],
            }
