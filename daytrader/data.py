"""Loading intraday bars from CSV, and a synthetic generator for tests.

CSV format (header required, extra columns ignored):

    timestamp,symbol,open,high,low,close,volume
    2026-10-23 09:15:00,RELIANCE,1450.0,1452.5,1449.1,1451.2,182340

Timestamps are bar START times in IST. ISO formats with or without an offset
work ("2026-10-23T09:15:00+05:30"). Export this from your broker's historical
data API (Kite Connect, DhanHQ, Groww, Fyers, OpenAlgo all provide it).
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable

from .market_calendar import IST, MARKET_CLOSE, MARKET_OPEN, NSECalendar, to_ist
from .models import Bar


def _parse_ts(value: str) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        dt = datetime.strptime(value, "%d-%m-%Y %H:%M")
    return to_ist(dt)


def load_csv(path: str | Path, symbol: str | None = None) -> list[Bar]:
    """Load bars sorted by time. `symbol` fills in files without a symbol column."""
    bars: list[Bar] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower().strip(): c for c in reader.fieldnames or []}
        ts_col = cols.get("timestamp") or cols.get("datetime") or cols.get("date")
        if not ts_col:
            raise ValueError("CSV needs a timestamp (or datetime/date) column")
        for row in reader:
            sym = row.get(cols["symbol"]) if "symbol" in cols else symbol
            if not sym:
                raise ValueError("CSV has no symbol column; pass symbol=...")
            o, h, l, c = (float(row[cols[k]]) for k in ("open", "high", "low", "close"))
            if not (l <= min(o, c) and h >= max(o, c)):
                raise ValueError(f"bad OHLC row at {row[ts_col]} {sym}: {o} {h} {l} {c}")
            vol = float(row[cols["volume"]]) if "volume" in cols and row[cols["volume"]] else 0.0
            bars.append(Bar(_parse_ts(row[ts_col]), sym.strip().upper(), o, h, l, c, vol))
    bars.sort(key=lambda b: (b.timestamp, b.symbol))
    return bars


def group_by_day(bars: Iterable[Bar]) -> dict[date, list[Bar]]:
    days: dict[date, list[Bar]] = defaultdict(list)
    for b in bars:
        days[b.timestamp.date()].append(b)
    return dict(sorted(days.items()))


def write_csv(bars: Iterable[Bar], path: str | Path) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.timestamp.strftime("%Y-%m-%d %H:%M:%S"), b.symbol,
                        f"{b.open:.2f}", f"{b.high:.2f}", f"{b.low:.2f}", f"{b.close:.2f}",
                        int(b.volume)])


def synthetic_bars(symbols: list[str], start: date, days: int, seed: int = 7,
                   start_price: float = 1000.0, vol_per_min: float = 0.0012,
                   interval_min: int = 1, calendar: NSECalendar | None = None) -> list[Bar]:
    """Random-walk bars for TESTING ONLY. They contain no real market behaviour,
    so a backtest on them says nothing about whether a strategy works."""
    rng = random.Random(seed)
    cal = calendar or NSECalendar()
    out: list[Bar] = []
    prices = {s: start_price * (1 + 0.2 * i) for i, s in enumerate(symbols)}
    d = start
    made = 0
    while made < days:
        if cal.is_trading_day(d):
            for s in symbols:
                p = prices[s] * (1 + rng.gauss(0, 0.01))  # overnight gap
                t = datetime.combine(d, MARKET_OPEN, IST)
                end = datetime.combine(d, MARKET_CLOSE, IST)
                while t < end:
                    o = p
                    steps = [rng.gauss(0, vol_per_min) for _ in range(interval_min)]
                    path = [o]
                    for st in steps:
                        path.append(path[-1] * (1 + st))
                    c = path[-1]
                    h = max(path) * (1 + abs(rng.gauss(0, vol_per_min / 3)))
                    lo = min(path) * (1 - abs(rng.gauss(0, vol_per_min / 3)))
                    out.append(Bar(t, s, round(o, 2), round(h, 2), round(lo, 2), round(c, 2),
                                   float(rng.randint(1_000, 50_000))))
                    p = c
                    t += timedelta(minutes=interval_min)
                prices[s] = p
            made += 1
        d += timedelta(days=1)
    out.sort(key=lambda b: (b.timestamp, b.symbol))
    return out
