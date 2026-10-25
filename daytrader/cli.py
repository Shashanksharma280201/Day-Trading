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


def cmd_serve(a, cfg):
    import signal
    import threading

    from .broker import PaperBroker
    from .engine import Engine, EngineConfig
    from .feeds import GrowwFeed, ReplayFeed
    from .server import ApprovalServer, load_or_create_token

    ecfg = EngineConfig.from_dict(cfg.get("engine"))
    ecfg.mode = cfg.get("mode", "paper")
    risk = RiskConfig.from_dict(cfg.get("risk"))
    charges = ChargeSchedule.from_dict(cfg.get("charges"))
    strat = strategies.build(cfg["strategy"]["name"], cfg["strategy"].get("params", {}))

    if a.live or ecfg.mode == "live":
        if not (a.live and ecfg.mode == "live"):
            sys.exit("Live trading needs BOTH \"mode\": \"live\" in config.json AND the --live flag.")
        if a.feed != "groww":
            sys.exit("Live trading needs --feed groww.")
        from .broker.groww import GrowwBroker, client_from_env
        client = client_from_env()
        broker = GrowwBroker(client, risk.max_orders_per_second)
        print("LIVE MODE: approved orders go to your real Groww account. "
              "Make sure this machine uses the static IP registered with Groww.")
    else:
        broker = PaperBroker(risk.capital, charges, cfg.get("slippage_bps", 2))
        client = None

    if a.feed == "replay":
        if not a.data:
            sys.exit("--feed replay needs --data path/to/bars.csv")
        feed = ReplayFeed(a.data, speed=a.speed, loop=a.loop)
    else:
        if client is None:
            from .broker.groww import client_from_env
            client = client_from_env()
        feed = GrowwFeed(client, a.symbols.split(",") if a.symbols else cfg.get("watchlist", []))

    engine = Engine(strat, risk, broker, ecfg, charges)
    token = load_or_create_token(ecfg.state_dir)
    server = ApprovalServer(engine, token, a.host, a.port, a.phone_host)
    server.start()
    host, port = server.address
    print(f"Mode: {ecfg.mode.upper()}  feed: {a.feed}  strategy: {strat.name}")
    print(f"Approval server: http://{host}:{port}  (token in {ecfg.state_dir}/api_token)")
    if server.phone_url:
        from .server.view import manifest
        print(f"Phone: {server.phone_url}")
        print(f"Pair the Android app with this link (or scan the QR in the island's Settings):")
        print(f"  {manifest(server.phone_url, token)['pairing_link']}")
    print(f"Approvals expire after {ecfg.approval_ttl:g}s; stale if price moves over {ecfg.max_drift_pct}%.")
    if a.print_token:
        print(f"Token: {token}")

    def on_event(ev):
        t, d = ev["type"], ev["data"]
        if t == "proposal":
            print(f"[APPROVAL NEEDED] {d['id']} {d['side']} {d['qty']} {d['symbol']} @ ~{d['ref_price']} "
                  f"stop {d['stop']} target {d['target']} risk Rs {d['risk_rupees']}")
        elif t in ("proposal_update", "position_opened", "position_closed", "killed", "alert", "feed"):
            print(f"[{t}] {json.dumps(d, default=str)}")

    engine.subscribe(on_event)
    t = threading.Thread(target=feed.run, args=(engine,), daemon=True)
    t.start()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while not stop.is_set() and (t.is_alive() or a.stay):
        stop.wait(0.5)
    feed.stop()
    if engine.positions:
        print("Closing open positions before exit...")
        engine.kill("server stopped", flatten=True, by="server")
    server.stop()
    print(json.dumps(engine.summary(), indent=2))


def cmd_groww(a, cfg):
    import os
    from datetime import datetime, timedelta

    from .broker.groww import GrowwClient, client_from_env, save_cached_token

    if a.groww_cmd == "login":
        key = os.environ.get("GROWW_API_KEY")
        if not key:
            sys.exit("set GROWW_API_KEY in your environment first")
        c = GrowwClient()
        if a.totp:
            info = c.login_with_totp(key, a.totp)
        else:
            secret = os.environ.get("GROWW_API_SECRET")
            if not secret:
                sys.exit("give --totp CODE, or set GROWW_API_SECRET")
            info = c.login_with_secret(key, secret)
        save_cached_token(info)
        print(f"Logged in. Token cached in state/ until {info.get('expiry', '6:00 AM tomorrow')}.")
        return
    client = client_from_env()
    if a.groww_cmd == "ltp":
        print(json.dumps(client.ltp(a.symbols.split(",")), indent=2))
    elif a.groww_cmd == "history":
        end = datetime.now().replace(second=0, microsecond=0)
        bars = []
        for sym in a.symbols.split(","):
            stop = end
            left = a.days
            while left > 0:  # 1-minute candles: at most 30 days per request
                span = min(left, 28)
                start = stop - timedelta(days=span)
                bars += client.candles(sym, start, stop, a.interval)
                stop, left = start, left - span
        bars = sorted({(b.timestamp, b.symbol): b for b in bars}.values(), key=lambda b: (b.timestamp, b.symbol))
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        write_csv(bars, a.out)
        print(f"Wrote {len(bars):,} real bars to {a.out}")
    elif a.groww_cmd == "positions":
        print(json.dumps(client.positions(), indent=2))


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

    sv = sub.add_parser("serve", help="run the live engine and approval server (paper by default)")
    sv.add_argument("--feed", choices=["replay", "groww"], default="replay")
    sv.add_argument("--data", help="CSV of bars for --feed replay")
    sv.add_argument("--speed", type=float, default=10.0, help="replay speed (10 = 10x real time)")
    sv.add_argument("--loop", action="store_true", help="replay the data again when it ends")
    sv.add_argument("--stay", action="store_true", help="keep serving after the replay ends")
    sv.add_argument("--symbols", help="comma-separated watchlist for --feed groww")
    sv.add_argument("--host", default="127.0.0.1", help="use your Tailscale IP for the phone")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--phone-host", help="also listen here for the phone: your laptop's Tailscale IP (100.x.y.z)")
    sv.add_argument("--print-token", action="store_true")
    sv.add_argument("--live", action="store_true", help="REAL orders (also needs mode live in config)")

    g = sub.add_parser("groww", help="Groww account tools")
    gs = g.add_subparsers(dest="groww_cmd", required=True)
    gl = gs.add_parser("login", help="get today's access token (key + secret, or TOTP)")
    gl.add_argument("--totp")
    gp = gs.add_parser("ltp", help="last prices")
    gp.add_argument("--symbols", required=True)
    gh = gs.add_parser("history", help="download real candles to CSV for backtests")
    gh.add_argument("--symbols", required=True)
    gh.add_argument("--days", type=int, default=60)
    gh.add_argument("--interval", default="1minute")
    gh.add_argument("--out", default="data/groww_bars.csv")
    gs.add_parser("positions", help="today's positions at Groww")

    a = p.parse_args(argv)
    cfg = load_config(a.config)
    {"costs": cmd_costs, "sample-data": cmd_sample, "backtest": cmd_backtest,
     "compare": cmd_compare, "serve": cmd_serve, "groww": cmd_groww}[a.cmd](a, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
