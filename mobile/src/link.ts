import EventSource from 'react-native-sse'
import { parseManifest, parseNotify, parseView, type Manifest, type Notify, type View } from './protocol'
import type { Pairing } from './pairing'

export type Phase = 'connecting' | 'live' | 'offline'
export type LinkState = { phase: Phase; error?: string; manifest?: Manifest; view?: View; seenAt?: number }

type Listener = (s: LinkState) => void

/** Plain words for what went wrong. */
export function linkError(status: number | undefined, message?: string): string {
  if (status === 401 || status === 403) return 'The engine didn’t accept the token. Pair again.'
  if (status) return `The engine answered ${status}.`
  if (message && /timeout|network|failed/i.test(message)) return 'Can’t reach the engine. Is your laptop awake, the server running and Tailscale on?'
  return message || 'Can’t reach the engine.'
}

/**
 * The connection to your trading engine: its live event stream (a fresh view
 * on every change, heads-ups as notifications), a slow safety poll, and your
 * answers. One instance for the whole app.
 */
export class EngineLink {
  private es: EventSource<'view' | 'notify'> | null = null
  private poll: ReturnType<typeof setInterval> | null = null
  private listeners = new Set<Listener>()
  private notifyListeners = new Set<(n: Notify) => void>()
  state: LinkState = { phase: 'connecting' }

  constructor(private pairing: Pairing) {}

  private headers(json = false): Record<string, string> {
    return { Authorization: `Bearer ${this.pairing.token}`, Accept: 'application/json', ...(json ? { 'Content-Type': 'application/json' } : {}) }
  }

  private set(patch: Partial<LinkState>) {
    this.state = { ...this.state, ...patch }
    for (const l of this.listeners) l(this.state)
  }

  subscribe(l: Listener): () => void {
    this.listeners.add(l)
    l(this.state)
    return () => this.listeners.delete(l)
  }

  onNotify(l: (n: Notify) => void): () => void {
    this.notifyListeners.add(l)
    return () => this.notifyListeners.delete(l)
  }

  private takeView(raw: any) {
    const view = parseView(raw)
    if (view) this.set({ phase: 'live', view, seenAt: Date.now(), error: undefined })
  }

  async start(): Promise<void> {
    this.stop()
    this.set({ phase: 'connecting', error: undefined })
    try {
      const r = await fetch(`${this.pairing.url}/island/manifest`, { headers: this.headers() })
      if (!r.ok) return this.set({ phase: 'offline', error: linkError(r.status) })
      const manifest = parseManifest(await r.json())
      if (!manifest) return this.set({ phase: 'offline', error: 'That address isn’t a Day-Trading engine.' })
      this.set({ manifest })
    } catch (e: any) {
      this.set({ phase: 'offline', error: linkError(undefined, String(e?.message ?? e)) })
    }
    const es = new EventSource<'view' | 'notify'>(`${this.pairing.url}/island/events`, {
      headers: { Authorization: `Bearer ${this.pairing.token}` },
      pollingInterval: 3000, // reconnect this soon after the stream drops
    })
    es.addEventListener('view', (e) => {
      try {
        const msg = JSON.parse(e.data ?? '{}')
        this.takeView(msg.data ?? msg)
      } catch {
        // ignore a bad line
      }
    })
    es.addEventListener('notify', (e) => {
      try {
        const msg = JSON.parse(e.data ?? '{}')
        const n = parseNotify(msg.data ?? msg)
        if (n) for (const l of this.notifyListeners) l(n)
      } catch {
        // ignore a bad line
      }
    })
    es.addEventListener('error', (e: any) => {
      this.set({ phase: 'offline', error: linkError(e?.xhrStatus || undefined, e?.message) })
    })
    this.es = es
    // A slow poll as a safety net: idle connections can die silently on mobile networks.
    this.poll = setInterval(() => void this.refresh(), 30_000)
  }

  async refresh(): Promise<void> {
    try {
      const r = await fetch(`${this.pairing.url}/island/view`, { headers: this.headers() })
      if (r.ok) this.takeView(await r.json())
      else this.set({ phase: 'offline', error: linkError(r.status) })
    } catch (e: any) {
      this.set({ phase: 'offline', error: linkError(undefined, String(e?.message ?? e)) })
    }
  }

  stop(): void {
    this.es?.removeAllEventListeners()
    this.es?.close()
    this.es = null
    if (this.poll) clearInterval(this.poll)
    this.poll = null
  }

  private async post(path: string, body: object): Promise<{ ok: boolean; message: string }> {
    try {
      const r = await fetch(`${this.pairing.url}${path}`, { method: 'POST', headers: this.headers(true), body: JSON.stringify(body) })
      const j: any = await r.json().catch(() => ({}))
      if (!r.ok && !('ok' in j)) return { ok: false, message: linkError(r.status) }
      void this.refresh()
      return { ok: j.ok === true, message: typeof j.message === 'string' ? j.message : '' }
    } catch (e: any) {
      return { ok: false, message: linkError(undefined, String(e?.message ?? e)) }
    }
  }

  /** Your answer. Only ever called from your tap (in the app or on a notification button). */
  answer(askId: string, approve: boolean) {
    return this.post('/island/answer', { ask_id: askId, answer: approve ? 'approve' : 'reject', device: 'android' })
  }

  action(actionId: string) {
    return this.post('/island/action', { action_id: actionId, device: 'android' })
  }
}

/** Check an address and token before saving them: null if they work, else why not. */
export async function testPairing(p: Pairing): Promise<string | null> {
  try {
    const r = await fetch(`${p.url}/island/manifest`, { headers: { Authorization: `Bearer ${p.token}` } })
    if (!r.ok) return linkError(r.status)
    return parseManifest(await r.json()) ? null : 'That address isn’t a Day-Trading engine.'
  } catch (e: any) {
    return linkError(undefined, String(e?.message ?? e))
  }
}
