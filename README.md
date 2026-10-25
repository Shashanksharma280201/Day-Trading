# Day-Trading

A cost-aware toolkit for automating intraday trading on NSE equities, built to
find out honestly whether a strategy works before any real money is at risk.

Pure Python standard library. Nothing to install. Paper trading by default.

> **Not financial advice.** SEBI's own studies found that 71% of individual
> intraday cash traders lost money in FY23, and close to 9 in 10 individual
> F&O traders lost money in FY26. This project is built to measure a strategy
> net of every charge, so a losing idea shows up as a losing idea.

## The plan

| Phase | What | Status |
| --- | --- | --- |
| 1 | Cost model, NSE calendar, risk guardrails, strategies, backtester, paper broker | **done** |
| 2 | Groww connector, live engine with your approval on every entry, approval and portfolio server | **done** |
| 3 | Dynamic Island "Connected" package: P&L on the capsule, approval cards, Trading tab, kill switch | **done** |
| 4 | Android app: same view, live notification, Buy / Skip buttons on trade notifications | **done** (build it once, see `mobile/README.md`) |
| 5 | Weeks of paper trading, then live with a small amount only if the numbers justify it | your call |

**Start here: [docs/SETUP.md](docs/SETUP.md)** (engine, island and phone, step by step).

## Live engine and approvals

```
strategy signal ──> PROPOSAL ──> your tap (island or phone) ──> risk re-check ──> order
                       │
                       └── no answer in 60 s, or price moved > 0.3%  ──> no trade
exits (stop, target, 15:10 square-off, daily loss limit) ──> automatic, never wait for you
```

```bash
# try the whole flow offline, any day of the week (replay of bars at 10x speed)
python3 -m daytrader.cli serve --feed replay --data data/sample.csv --speed 10 --print-token

# reachable from your phone too, over Tailscale
python3 -m daytrader.cli serve --feed replay --data data/sample.csv --phone-host 100.101.102.103

# paper trading on live Groww prices (needs a Groww Trade API subscription)
export GROWW_API_KEY=...  GROWW_API_SECRET=...   # or: daytrader groww login --totp 123456
python3 -m daytrader.cli serve --feed groww --symbols RELIANCE,INFY,HDFCBANK

# download real 1-minute candles for backtests
python3 -m daytrader.cli groww history --symbols RELIANCE,INFY --days 60 --out data/real.csv
```

The server listens on `127.0.0.1:8765`. Clients authenticate with the token
in `state/api_token`:

| Endpoint | What |
| --- | --- |
| `GET /api/health` | is it up (no token) |
| `GET /api/state` | P&L, positions, approvals waiting, today's trades |
| `GET /api/events` | live stream (Server-Sent Events): `proposal`, `proposal_update`, `position_opened`, `position_closed`, `tick`, `killed`, `alert` |
| `/island/*` | the view protocol for the Dynamic Island and the phone ([docs/island-protocol.md](docs/island-protocol.md)) |
| `POST /api/proposals/<id>/approve` | `{"device": "island"}`; the first answer wins |
| `POST /api/proposals/<id>/reject` | |
| `POST /api/kill` | `{"reason": "...", "flatten": true}` stops trading for the day |

**Paper by default.** Real orders need BOTH `"mode": "live"` in
`config/config.json` AND the `--live` flag. In live mode every entry also
places an SL-M stop at Groww, so a crash cannot leave a position unprotected,
and market orders go out as protected limit orders (1% band). Before going
live, the machine must use the static IP you registered with Groww.

Groww keys stay in environment variables on your laptop. Devices only ever
hold the server token.

## Quick start

```bash
# what one round trip costs, and the move needed to break even
python3 -m daytrader.cli costs --value 100000 --trades-per-day 4

# test the pipeline on SYNTHETIC data (a random walk: proves nothing about a strategy)
python3 -m daytrader.cli sample-data --out data/sample.csv --days 60
python3 -m daytrader.cli compare --data data/sample.csv

# backtest on REAL 1-minute bars exported from your broker
python3 -m daytrader.cli backtest --data data/real_bars.csv --strategy orb --trades-out results/orb.csv

# tests
python3 -m unittest discover -s tests -t tests
```

Copy `config/config.example.json` to `config/config.json` to change capital,
risk limits, strategy settings and charges. `config.json` is git-ignored.

### Data format

```
timestamp,symbol,open,high,low,close,volume
2026-10-23 09:15:00,RELIANCE,1450.0,1452.5,1449.1,1451.2,182340
```

Bar start times in IST. Export it from your broker's historical data API.

## What is inside

| File | Job |
| --- | --- |
| `daytrader/costs.py` | Brokerage, STT, exchange charge, SEBI fee, GST, stamp duty. A Rs 1 lakh round trip costs Rs 82.68 (break-even move 0.083%) at Zerodha's intraday rates |
| `daytrader/market_calendar.py` | NSE hours (9:15 to 15:30 IST) and the 2026 holiday list in `config/nse_holidays.json` |
| `daytrader/risk.py` | Size from rupee risk per trade, position cap, daily loss limit, trades per day, entry windows, square-off time, F&O block, orders-per-second throttle under SEBI's 10 OPS line |
| `daytrader/strategies/` | `orb` (opening range breakout) and `vwap` (VWAP cross). Strategies only propose entries; exits are the engine's job |
| `daytrader/backtest.py` | Next-bar-open fills, slippage, stop assumed before target in the same bar, gap fills at the open, forced square-off, full charges |
| `daytrader/report.py` | Net P&L, costs, win rate, profit factor, drawdown, profitable days |
| `daytrader/broker/` | Broker interface, paper broker, and the Groww connector (`groww.py`) |
| `daytrader/engine.py` | Live engine: proposals, approvals, drift and expiry checks, automatic exits, kill switch, audit log in `state/` |
| `daytrader/feeds.py` | Replay feed (offline testing) and Groww feed (1-minute candles plus LTP polling) |
| `daytrader/server/` | Approval and portfolio server; `view.py` decides everything the island and the phone show |
| `mobile/` | The Android app (Expo): pairing, the same view, notifications with Buy / Skip |
| `docs/island-protocol.md` | The view protocol the island and the phone speak |

## Default risk rules

| Rule | Default |
| --- | --- |
| Capital | Rs 1,00,000 |
| Risk per trade | 0.5% of capital (Rs 500) |
| Max position | 20% of capital, no leverage |
| Daily loss limit | 2% of capital, then no more entries that day |
| Trades per day | 5 |
| Entry window | 09:20 to 14:45 |
| Square-off | 15:10 (before the broker's own MIS auto square-off) |
| F&O | blocked |
| Orders per second | 5 (SEBI's unregistered algo limit is 10) |

## Rules this project will not break

* Paper mode is the default. Going live is a deliberate setting you change yourself.
* API keys and passwords live in environment variables on your server, never in this repo or in a chat.
* Every live order goes out with market protection, from your registered static IP, under 10 orders per second.
* Stop-losses are placed with the broker, so a crashed script cannot leave a position unprotected.

## Regulation notes (October 2026)

SEBI's retail algo framework is mandatory for all brokers from April 1, 2026.
A personal algo under 10 orders per second needs no exchange registration, but
every API key must be mapped to a static IP, API orders are tagged, and API
market orders need market protection. Selling or sharing a strategy with
others requires broker empanelment, and black box strategies require SEBI
Research Analyst registration. This repo is for your own use.
