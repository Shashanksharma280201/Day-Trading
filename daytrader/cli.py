"""Command line entry point.

    python -m daytrader.cli costs --value 100000
    python -m daytrader.cli sample-data --out data/sample.csv --days 60
    python -m daytrader.cli backtest --data data/your_bars.csv --strategy orb
    python -m daytrader.cli compare --data data/your_bars.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import strategies
from .backtest import Backtester
from .costs import ChargeSchedule, breakeven_move_pct, round_trip_charges
from .data import load_csv, synthetic_bars, write_csv
from .report import format_summary, summarize, write_trades_csv
from .risk import RiskConfig

DEFAULT_CONFIG = Path("config/config.json")
EXAMPLE_CONFIG = Path(__file__).resolve().parent.parent / "config" / "config.example.json"


def load_config(path: str | None) -> dict:
    p = Path(path) if path else (DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else EXAMPLE_CONFIG)
    return json.loads(p.read_text())


def cmd_costs(a, cfg):
    sched = ChargeSchedule.from_dict(cfg.get("charges"))
    ch = round_trip_charges(a.value, a.value, sched)
    print(f"Round trip of Rs {a.value:,.0f} buy + Rs {a.value:,.0f} sell:")
    for k, v in ch.as_dict().items():
        print(f"  {k:<10} Rs {v:,.2f}")
    print(f"Break-even move: {breakeven_move_pct(a.value, sched):.4f}%")
    if a.trades_per_day:
        yearly = ch.total * a.trades_per_day * 240
        print(f"At {a.trades_per_day} round trips a day for 240 days: Rs {yearly:,.0f} a year in charges")


def cmd_sample(a, cfg):
    syms = a.symbols.split(",") if a.symbols else cfg.get("watchlist", ["SAMPLE"])[:3]
    bars = synthetic_bars(syms, date.fromisoformat(a.start), a.days, seed=a.seed,
                          interval_min=a.interval)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    write_csv(bars, a.out)
    print(f"Wrote {len(bars):,} SYNTHETIC bars for {', '.join(syms)} to {a.out}")
    print("Synthetic data is a random walk: use it to test the plumbing, never to judge a strategy.")


def _run(name, params, bars, cfg, slippage):
    strat = strategies.build(name, params)
    risk = RiskConfig.from_dict(cfg.get("risk"))
    bt = Backtester(strat, risk, ChargeSchedule.from_dict(cfg.get("charges")), slippage)
    res = bt.run(bars)
    return res, summarize(res, risk.capital)


def cmd_backtest(a, cfg):
    bars = load_csv(a.data, symbol=a.symbol)
    name = a.strategy or cfg["strategy"]["name"]
    params = cfg["strategy"].get("params", {}) if name == cfg["strategy"]["name"] else {}
    slip = a.slippage_bps if a.slippage_bps is not None else cfg.get("slippage_bps", 2)
    res, s = _run(name, params, bars, cfg, slip)
    print(format_summary(s, f"{name.upper()} on {a.data}"))
    if res.non_trading_days_in_data:
        print(f"Note: skipped {len(res.non_trading_days_in_data)} non-trading days found in the data")
    if a.trades_out:
        write_trades_csv(res, a.trades_out)
        print(f"Trades written to {a.trades_out}")
    if a.json:
        print(json.dumps(s, indent=2, default=str))


def cmd_compare(a, cfg):
    bars = load_csv(a.data, symbol=a.symbol)
    slip = a.slippage_bps if a.slippage_bps is not None else cfg.get("slippage_bps", 2)
    rows = []
    for name in sorted(strategies.REGISTRY):
        params = cfg["strategy"].get("params", {}) if name == cfg["strategy"]["name"] else {}
        _, s = _run(name, params, bars, cfg, slip)
        rows.append((name, s))
    print(f"{'strategy':<8} {'trades':>6} {'win%':>6} {'gross':>12} {'costs':>10} {'NET':>12} {'maxDD%':>7}")
    for name, s in rows:
        print(f"{name:<8} {s['trades']:>6} {s['win_rate_pct']:>6} {s['gross_pnl']:>12,.0f} "
              f"{s['total_costs']:>10,.0f} {s['net_pnl']:>12,.0f} {s['max_drawdown_pct']:>7}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="daytrader")
    p.add_argument("--config", help="config JSON (default config/config.json, else the example)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("costs", help="charges and break-even for one round trip")
    c.add_argument("--value", type=float, default=100_000)
    c.add_argument("--trades-per-day", type=int, default=0)

    s = sub.add_parser("sample-data", help="write SYNTHETIC bars for testing the pipeline")
    s.add_argument("--out", default="data/sample.csv")
    s.add_argument("--symbols")
    s.add_argument("--start", default="2026-07-01")
    s.add_argument("--days", type=int, default=60)
    s.add_argument("--interval", type=int, default=1, help="bar size in minutes")
    s.add_argument("--seed", type=int, default=7)

    for name, helptext in (("backtest", "run one strategy"), ("compare", "run every strategy")):
        b = sub.add_parser(name, help=helptext)
        b.add_argument("--data", required=True, help="CSV of intraday bars")
        b.add_argument("--symbol", help="symbol for CSVs without a symbol column")
        b.add_argument("--slippage-bps", type=float)
        if name == "backtest":
            b.add_argument("--strategy", choices=sorted(strategies.REGISTRY))
            b.add_argument("--trades-out", help="write every trade to this CSV")
            b.add_argument("--json", action="store_true")

    a = p.parse_args(argv)
    cfg = load_config(a.config)
    {"costs": cmd_costs, "sample-data": cmd_sample, "backtest": cmd_backtest,
     "compare": cmd_compare}[a.cmd](a, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
