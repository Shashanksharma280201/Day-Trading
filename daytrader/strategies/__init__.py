from .base import Strategy
from .orb import OpeningRangeBreakout
from .vwap import VWAPCross

REGISTRY = {
    "orb": OpeningRangeBreakout,
    "vwap": VWAPCross,
}


def build(name: str, params: dict | None = None) -> Strategy:
    try:
        cls = REGISTRY[name.lower()]
    except KeyError:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(REGISTRY)}") from None
    return cls(**(params or {}))


__all__ = ["Strategy", "OpeningRangeBreakout", "VWAPCross", "REGISTRY", "build"]
