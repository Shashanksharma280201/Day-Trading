"""Strategy interface.

A strategy only proposes ENTRIES. It sees one completed bar at a time, per
symbol, and may return a Signal with a stop (required) and a target. Exits
(stop, target, square-off, daily loss limit) are handled by the engine, so
every strategy is held to the same risk rules.

A signal produced on a bar's close is filled at the NEXT bar's open, which
avoids look-ahead bias.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from ..models import Bar, Signal


class Strategy(ABC):
    name = "base"

    def start_day(self, d: date) -> None:
        """Reset any per-day state. Called before the first bar of each session."""

    @abstractmethod
    def on_bar(self, bar: Bar) -> Optional[Signal]:
        """Called with each completed bar. Return a Signal to propose an entry."""

    def params(self) -> dict:
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}
