"""NSE equity market calendar: trading days and session times in IST.

India has no daylight saving, so IST is a fixed UTC+05:30 offset and no time
zone database is needed.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

PRE_OPEN_START = time(9, 0)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

DEFAULT_HOLIDAY_FILE = Path(__file__).resolve().parent.parent / "config" / "nse_holidays.json"


class NSECalendar:
    def __init__(self, holiday_file: str | Path | None = DEFAULT_HOLIDAY_FILE):
        self.holidays: set[date] = set()
        self.known_years: set[int] = set()
        if holiday_file and Path(holiday_file).exists():
            data = json.loads(Path(holiday_file).read_text())
            for key, value in data.items():
                if key.isdigit() and isinstance(value, list):
                    self.known_years.add(int(key))
                    self.holidays.update(date.fromisoformat(d) for d in value)

    def is_trading_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        return d not in self.holidays

    def holiday_list_known(self, d: date) -> bool:
        """False when the holiday file has no list for this year (weekends only are checked)."""
        return d.year in self.known_years

    def is_market_open(self, now: datetime) -> bool:
        now = to_ist(now)
        return self.is_trading_day(now.date()) and MARKET_OPEN <= now.time() < MARKET_CLOSE

    def next_trading_day(self, d: date) -> date:
        d = d + timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d


def to_ist(dt: datetime) -> datetime:
    """Naive datetimes are assumed to already be IST."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def parse_hhmm(value: str) -> time:
    hh, mm = value.strip().split(":")
    return time(int(hh), int(mm))
