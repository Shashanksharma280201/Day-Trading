"""Market data feeds for the live engine.

A feed calls two engine methods:

    engine.on_bar(bar)                  a completed 1-minute bar (drives the strategy)
    engine.on_prices(prices, now)       latest prices (stops, targets, P&L, expiry)

ReplayFeed   replays a CSV of bars at any speed. Works offline, any day of the
             week, so the whole approval flow can be tested without Groww.
GrowwFeed    polls Groww: 1-minute candles once a minute for the strategy and
             LTP every few seconds for risk. Stays far under Groww's limits
             (10 live-data requests per second).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, time as dtime, timedelta
from typing import Protocol

from .data import load_csv
from .market_calendar import IST, MARKET_CLOSE, MARKET_OPEN, NSECalendar


class EngineLike(Protocol):
    def on_bar(self, bar) -> None: ...
    def on_prices(self, prices: dict, now: datetime) -> None: ...
    def on_feed_status(self, status: str, detail: str = "") -> None: ...


class ReplayFeed:
    def __init__(self, path: str, speed: float = 60.0, loop: bool = False):
        self.bars = load_csv(path)
        self.speed = max(speed, 0.01)
        self.loop = loop
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self, engine: EngineLike) -> None:
        engine.on_feed_status("replay", f"{len(self.bars)} bars at {self.speed:g}x")
        while not self._stop.is_set():
            prev_ts = None
            for b in self.bars:
                if self._stop.is_set():
                    return
                if prev_ts is not None and b.timestamp > prev_ts:
                    gap = (b.timestamp - prev_ts).total_seconds()
                    if gap > 3600:  # overnight: short pause only
                        gap = 60
                    self._stop.wait(gap / self.speed)
                prev_ts = b.timestamp
                end = b.timestamp + timedelta(minutes=1)
                engine.on_bar(b)
                engine.on_prices({b.symbol: b.close}, end)
            if not self.loop:
                engine.on_feed_status("finished", "replay data ended")
                return


class GrowwFeed:
    def __init__(self, client, symbols: list[str], ltp_every: float = 3.0,
                 calendar: NSECalendar | None = None, clock=lambda: datetime.now(IST)):
        self.client = client
        self.symbols = symbols
        self.ltp_every = ltp_every
        self.calendar = calendar or NSECalendar()
        self.clock = clock
        self._stop = threading.Event()
        self._last_bar: dict[str, datetime] = {}

    def stop(self) -> None:
        self._stop.set()

    def _poll_candles(self, now: datetime) -> None:
        start = datetime.combine(now.date(), MARKET_OPEN)
        for sym in self.symbols:
            try:
                bars = self.client.candles(sym, start, now.replace(tzinfo=None), "1minute")
            except Exception as e:  # keep going; one symbol failing must not stop the rest
                self._engine.on_feed_status("degraded", f"candles {sym}: {e}")
                continue
            for b in bars:
                # only completed bars: the bar starting this minute is still forming
                if b.timestamp + timedelta(minutes=1) > now:
                    continue
                if sym in self._last_bar and b.timestamp <= self._last_bar[sym]:
                    continue
                self._last_bar[sym] = b.timestamp
                self._engine.on_bar(b)

    def run(self, engine: EngineLike) -> None:
        self._engine = engine
        engine.on_feed_status("live", f"Groww, {len(self.symbols)} symbols")
        last_candle_minute = None
        while not self._stop.is_set():
            now = self.clock()
            if not self.calendar.is_market_open(now):
                engine.on_feed_status("market_closed", "")
                self._stop.wait(30)
                continue
            minute = now.replace(second=0, microsecond=0)
            if minute != last_candle_minute and now.second >= 3:
                last_candle_minute = minute
                self._poll_candles(now)
            try:
                engine.on_prices(self.client.ltp(self.symbols), now)
                engine.on_feed_status("live", "")
            except Exception as e:
                engine.on_feed_status("degraded", f"prices: {e}")
            self._stop.wait(self.ltp_every)
