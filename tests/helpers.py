from datetime import date, datetime, timedelta

from daytrader.market_calendar import IST
from daytrader.models import Bar

DAY = date(2026, 10, 23)  # a Friday, a trading day


def bar(hhmm: str, o, h, l, c, v=1000, sym="TEST", d: date = DAY) -> Bar:
    hh, mm = map(int, hhmm.split(":"))
    return Bar(datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST), sym, o, h, l, c, v)


def flat_bars(start: str, end: str, price: float, sym="TEST", d: date = DAY) -> list[Bar]:
    hh, mm = map(int, start.split(":"))
    t = datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST)
    eh, em = map(int, end.split(":"))
    stop = datetime(d.year, d.month, d.day, eh, em, tzinfo=IST)
    out = []
    while t < stop:
        out.append(Bar(t, sym, price, price, price, price, 1000))
        t += timedelta(minutes=1)
    return out
