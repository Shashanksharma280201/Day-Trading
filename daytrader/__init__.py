"""daytrader: a cost-aware intraday trading toolkit for Indian equities (NSE).

Phase 1 (this package): cost model, NSE calendar, risk guardrails, strategies,
backtester and a paper broker. Everything runs on the Python standard library.

Nothing in this package places a live order. A live broker connector is a
separate, opt-in module and paper trading is the default everywhere.
"""

__version__ = "0.1.0"
