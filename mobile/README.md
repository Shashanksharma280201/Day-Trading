# Day-Trading for Android

The phone side of the Day-Trading engine: the same view as the Dynamic
Island (today's P&L, open positions, today's trades, the kill switch), and
every trade waiting for your OK, in the app and as a notification with
**Buy / Skip** buttons.

The app has no trading logic and no broker keys. It shows what your engine
sends (`/island/view`, `/island/events`) and sends back your taps
(`/island/answer`, `/island/action`), using the engine's token.

## How it connects

```
phone ──Tailscale (private, encrypted)──> laptop: daytrader serve --phone-host 100.x.y.z
```

1. Install [Tailscale](https://tailscale.com/download) on your laptop and your
   phone, sign in to the same account on both. Your laptop gets an address like
   `100.101.102.103` (`tailscale ip -4`).
2. Start the engine with that address:
   `python3 -m daytrader.cli serve --feed groww --phone-host 100.101.102.103`
3. Pair: open the app and scan the QR from Dynamic Island → Settings →
   Connected → **Show QR**, or paste the `daytrader://pair?...` link the
   server prints.

Plain `http://` is fine here because Tailscale encrypts everything between
your devices. Never expose the engine's port to the internet.

## Build and install the APK

You don't need Android Studio. Expo's cloud build makes the APK:

```bash
cd mobile
npm install
npx eas-cli@latest login          # free Expo account
npx eas-cli@latest build -p android --profile preview
```

When it finishes, open the link it prints on your phone and install the APK
(allow "install unknown apps" for your browser once).

With Android Studio installed you can build locally instead:
`npx expo run:android --variant release`.

Expo Go can't run this app fully: the live notification is a small native
module (`modules/live-status`), so it needs a real build.

## What runs on the phone

| Part | What it does |
| --- | --- |
| `src/link.ts` | Event stream from the engine, a 30-second safety poll, your answers |
| `src/notify.ts` | Live status notification, one notification per waiting trade with its buttons, heads-ups |
| `modules/live-status` | Android foreground service: keeps the connection alive while the app watches the market; stops when you swipe the app away |
| `src/ui/` | Pairing (QR, link or typed) and the home screen |

## Safety

* Only your tap answers a trade: in the app, or on the notification's
  button. No answer before the countdown ends means no trade.
* Trade notifications are private on the lock screen, so the buttons can't
  be pressed on a locked phone.
* The token is kept in Android's encrypted storage (`expo-secure-store`).
  Unpair from the app, and delete `state/api_token` on the laptop to revoke
  every paired device (a new token is made on the next start).
* Turn the live notification off after market hours to save battery.
