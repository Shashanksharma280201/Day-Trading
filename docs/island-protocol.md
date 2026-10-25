# Island view protocol (version 1)

The Dynamic Island's **Connected packages** and the **Android app** render
what this server sends and send back your answers. Neither has any trading
logic: every label, number and layout comes from `daytrader/server/view.py`,
so changing that file changes both screens.

All requests need the token from `state/api_token`:
`Authorization: Bearer <token>`, or `?token=<token>` for the event stream.

## Endpoints

| Method | Path | Body | Answer |
| --- | --- | --- | --- |
| GET | `/island/manifest` | | `Manifest` |
| GET | `/island/view` | | `View` |
| GET | `/island/events` | | Server-Sent Events: `view` (a `View`), `notify` (a `Notify`) |
| POST | `/island/answer` | `{"ask_id", "answer": "approve" \| "reject", "device"}` | `{"ok", "message"}` |
| POST | `/island/action` | `{"action_id", "device"}` | `{"ok", "message"}` |

The first `view` event arrives as soon as the stream opens. A comment line
(`: keepalive`) is sent every 15 seconds; clients reconnect if nothing arrives
for 40 seconds.

## Types

```ts
type Manifest = {
  protocol: 1
  id: string              // "trading"
  name: string            // shown as the app name and the tab title
  color: string           // accent colour
  description: string
  permissions: string[]
  tab_title: string
  phone_url?: string      // where the phone reaches this server (Tailscale)
  pairing_link?: string   // daytrader://pair?url=...&token=... (for the QR)
}

type Tone = 'up' | 'down' | 'neutral' | 'warn'

type View = {
  protocol: 1
  updated_at: number      // epoch ms
  status: {               // the island capsule and the phone's ongoing notification
    text: string          // "+₹1,240.00"
    short: string         // "+₹1.2k" (fits the narrow capsule)
    tone: Tone
    detail: string        // "2 open · 3 trades · PAPER"
    show: boolean         // false: nothing worth a capsule right now
  }
  asks: Ask[]             // approvals waiting, oldest first
  sections: Section[]     // the panel / home screen, top to bottom
}

type Ask = {
  id: string
  title: string           // "Buy 19 INFY"
  subtitle: string
  lines: { label: string; value: string; tone?: Tone }[]
  note: string            // why the strategy wants it
  approve_label: string   // "Buy"
  reject_label: string    // "Skip"
  seconds_left: number    // count down from when the view arrived
  expires_at: number      // epoch ms on the server's clock
  tone: Tone
}

type Section =
  | { type: 'stats'; title?: string; items: { label: string; value: string; tone?: Tone }[] }
  | { type: 'list'; title: string; empty?: string; rows: { title: string; subtitle?: string; value?: string; tone?: Tone }[] }
  | { type: 'actions'; actions: { id: string; label: string; style: 'danger' | 'default'; confirm?: string }[] }
  | { type: 'note'; text: string; tone?: Tone }

type Notify = { title: string; body: string; urgency: 'low' | 'normal' | 'critical' }
```

## Rules for clients

* An ask disappears when it is answered, expires or goes stale. Clients
  remove cards that are no longer in the latest `view`.
* Show the countdown from `seconds_left`, not `expires_at`, so a phone whose
  clock is off still counts correctly. The server decides; the countdown is
  only a hint.
* Ask before running an action with `confirm`.
* Never answer an ask on your own. Only a person's tap may send
  `/island/answer`. (The island's AI assistant only gets a read-only view.)
