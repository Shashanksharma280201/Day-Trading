"""Summary statistics and CSV export for a backtest. Everything is net of costs
unless a field name says gross."""

from __future__ import annotations

import csv
from pathlib import Path

from .backtest import BacktestResult


def summarize(res: BacktestResult, capital: float) -> dict:
    trades = res.trades
    n = len(trades)
    gross = sum(t.gross_pnl for t in trades)
    costs = sum(t.charges for t in trades)
    net = gross - costs
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl <= 0]

    equity, peak, max_dd = capital, capital, 0.0
    for day in sorted(res.daily_net):
        equity += res.daily_net[day]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    days = res.days_tested
    up_days = sum(1 for v in res.daily_net.values() if v > 0)
    exits: dict[str, int] = {}
    for t in trades:
        exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1

    return {
        "days_tested": days,
        "trades": n,
        "win_rate_pct": round(len(wins) / n * 100, 1) if n else 0.0,
        "gross_pnl": round(gross, 2),
        "total_costs": round(costs, 2),
        "net_pnl": round(net, 2),
        "net_return_pct": round(net / capital * 100, 2),
        "avg_net_per_trade": round(net / n, 2) if n else 0.0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "costs_as_pct_of_gross_profit": round(costs / gross * 100, 1) if gross > 0 else None,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd / capital * 100, 2),
        "profitable_days_pct": round(up_days / days * 100, 1) if days else 0.0,
        "days_halted_by_loss_limit": len(res.halted_days),
        "exit_reasons": exits,
        "signals_skipped": len(res.skipped),
    }


def format_summary(s: dict, title: str = "Backtest") -> str:
    def inr(x):
        return "n/a" if x is None else f"Rs {x:,.2f}"

    lines = [
        f"== {title} ==",
        f"Days tested          {s['days_tested']}",
        f"Trades               {s['trades']}   (win rate {s['win_rate_pct']}%)",
        f"Gross P&L            {inr(s['gross_pnl'])}",
        f"Costs (all charges)  {inr(s['total_costs'])}",
        f"NET P&L              {inr(s['net_pnl'])}   ({s['net_return_pct']}% of capital)",
        f"Avg net per trade    {inr(s['avg_net_per_trade'])}",
        f"Avg win / avg loss   {inr(s['avg_win'])} / {inr(s['avg_loss'])}",
        f"Profit factor        {s['profit_factor'] if s['profit_factor'] is not None else 'n/a'}",
        f"Max drawdown         {inr(s['max_drawdown'])} ({s['max_drawdown_pct']}%)",
        f"Profitable days      {s['profitable_days_pct']}%",
        f"Loss-limit days      {s['days_halted_by_loss_limit']}",
        f"Exits                {s['exit_reasons']}",
        f"Signals skipped      {s['signals_skipped']}",
    ]
    if s["costs_as_pct_of_gross_profit"] is not None:
        lines.append(f"Costs ate            {s['costs_as_pct_of_gross_profit']}% of gross profit")
    return "\n".join(lines)


def write_trades_csv(res: BacktestResult, path: str | Path) -> None:
    cols = ["symbol", "side", "qty", "entry_time", "entry_price", "exit_time", "exit_price",
            "exit_reason", "gross_pnl", "charges", "net_pnl", "entry_reason"]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for t in res.trades:
            w.writerow([t.symbol, t.side, t.qty, t.entry_time.isoformat(), t.entry_price,
                        t.exit_time.isoformat(), t.exit_price, t.exit_reason, t.gross_pnl,
                        t.charges, round(t.net_pnl, 2), t.entry_reason])
