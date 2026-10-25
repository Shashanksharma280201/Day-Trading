# Setup: engine, Dynamic Island and phone

Everything runs on your laptop. The island and the phone only show what the
engine sends and pass your taps back. Paper trading is the default at every
step; nothing here places a real order until you deliberately switch to live.

```
                 your laptop
 ┌──────────────────────────────────────────────┐
 │  daytrader serve  (strategy · risk · Groww)  │──── Groww Trade API
 │        │ 127.0.0.1:8765                      │
 │  Dynamic Island  (Connected → Trading)       │
 └────────┼─────────────────────────────────────┘
          │ Tailscale (private, encrypted)
     Android app  (same view, Buy / Skip on notifications)
```

## 1. The engine

Needs Python 3.10 or newer. Nothing to install.

```bash
git clone https://github.com/Shashanksharma280201/Day-Trading.git
cd Day-Trading
cp config/config.example.json config/config.json     # edit capital and risk limits

# try everything offline first, on synthetic bars (any day of the week)
python3 -m daytrader.cli sample-data --out data/sample.csv --days 3
python3 -m daytrader.cli serve --feed replay --data data/sample.csv --speed 10
```

The first start creates `state/api_token`. The island and the phone use it;
keep it private. Delete it to revoke every paired device (a new one is made on
the next start).

With a Groww Trade API subscription, use live prices (still paper trading):

```bash
export GROWW_API_KEY=...  GROWW_API_SECRET=...     # never in a file in this repo
python3 -m daytrader.cli serve --feed groww --symbols RELIANCE,INFY,HDFCBANK
```

Groww tokens expire at 6:00 AM every day. With key and secret the engine logs
in by itself (approve the key on Groww Cloud each day if Groww asks); or run
`python3 -m daytrader.cli groww login --totp 123456` each morning.

## 2. The Dynamic Island

1. Install or update [Dynamic Island](https://github.com/Shashanksharma280201/dynamic-island-linux)
   with the **Connected** package (until it's in a release, build it from the
   code: see its `docs/install.md`).
2. **Settings → Connected**: turn it on, keep `http://127.0.0.1:8765`, paste
   the token from `state/api_token`, **Save**. It says **Live** when it's
   connected.
3. You'll see:
   * the capsule: today's P&L (green up, red down) while you have trades or
     positions;
   * a card for every trade the strategy wants: **Buy / Skip** with a
     countdown (or the approval shortcuts, Ctrl+Alt+Y / Ctrl+Alt+N);
   * the **Trading** tab in the rail: P&L, open positions, today's trades with
     charges, recent approvals, **Stop trading today**, **Close everything now**.

## 3. The phone (Android)

1. Install [Tailscale](https://tailscale.com/download) on the laptop and the
   phone, signed in to the same account. Find the laptop's address:
   `tailscale ip -4` (looks like `100.101.102.103`).
2. Start the engine with it:
   `python3 -m daytrader.cli serve --feed groww --phone-host 100.101.102.103`
3. Build and install the app once (see [mobile/README.md](../mobile/README.md);
   the cloud build needs no Android Studio).
4. Pair: island **Settings → Connected → Show QR**, scan it in the app (or
   paste the `daytrader://pair?...` link the engine prints).
5. Leave **Live notification** on during market hours. Trades arrive as
   notifications with **Buy / Skip** buttons; today's P&L stays in the
   notification shade.

Whichever device answers first wins; the card disappears everywhere else.

## Every trading day

1. Laptop awake and plugged in by 9:10 AM. Start the engine.
2. Answer the cards. No answer within the countdown means no trade; a price
   that moved more than 0.3% since the card appeared is refused as stale.
3. Exits are automatic: stop, target, 15:10 square-off, daily loss limit.
4. After the close: read **Today's trades** (net of charges). Turn the phone's
   live notification off.

## Before going live (later, only if paper results justify it)

* Several weeks of paper trading with a positive result **after charges**.
* A static IP registered with Groww (SEBI rule for API orders): from your ISP
  (about ₹1,500 a year), or route the engine through a small static-IP server.
* Then set `"mode": "live"` in `config/config.json` **and** start with
  `--live`. Every entry also places an SL-M stop at Groww.

## When something's wrong

| You see | Do this |
| --- | --- |
| Island: "Nothing is answering at that address" | Is `daytrader serve` running? Same port? |
| Island or phone: "didn't accept the token" | Copy `state/api_token` again (it changes if the file was deleted) |
| Phone: "Can't reach the engine" | Tailscale on, on both? Engine started with `--phone-host`? Laptop asleep? |
| Card says "price moved" | The market moved more than 0.3% before you answered; that trade is gone |
| No cards all day | Normal on quiet days: the strategy only proposes when its rule fires, inside 09:20 to 14:45 |
