/**
 * The engine's view (protocol 1, see ../docs/island-protocol.md): the same
 * thing the Dynamic Island shows. Checked field by field, since it arrives
 * over the network.
 */
export type Tone = 'up' | 'down' | 'neutral' | 'warn'
const TONES: Tone[] = ['up', 'down', 'neutral', 'warn']

export type Line = { label: string; value: string; tone?: Tone }
export type Ask = {
  id: string
  title: string
  subtitle: string
  lines: Line[]
  note: string
  approveLabel: string
  rejectLabel: string
  secondsLeft: number
  tone: Tone
}
export type Section =
  | { type: 'stats'; title?: string; items: Line[] }
  | { type: 'list'; title: string; empty?: string; rows: { title: string; subtitle?: string; value?: string; tone?: Tone }[] }
  | { type: 'actions'; actions: { id: string; label: string; style: 'danger' | 'default'; confirm?: string }[] }
  | { type: 'note'; text: string; tone?: Tone }
export type View = {
  updatedAt: number
  status: { text: string; short: string; tone: Tone; detail: string; show: boolean }
  asks: Ask[]
  sections: Section[]
}
export type Manifest = { id: string; name: string; color: string; tabTitle: string }
export type Notify = { title: string; body: string; urgency: 'low' | 'normal' | 'critical' }

const text = (v: unknown, max = 200) => (typeof v === 'string' ? v.slice(0, max) : '')
const tone = (v: unknown): Tone | undefined => (TONES.includes(v as Tone) ? (v as Tone) : undefined)
const list = (v: unknown, max: number): any[] => (Array.isArray(v) ? v.slice(0, max) : [])
const line = (v: any): Line | null => {
  const label = text(v?.label, 60)
  const value = text(v?.value, 80)
  if (!label && !value) return null
  const t = tone(v?.tone)
  return t ? { label, value, tone: t } : { label, value }
}

export function parseManifest(raw: any): Manifest | null {
  if (raw?.protocol !== 1 || !text(raw.name)) return null
  return { id: text(raw.id, 40), name: text(raw.name, 40), color: /^#[0-9a-f]{3,8}$/i.test(raw.color) ? raw.color : '#30d158', tabTitle: text(raw.tab_title, 30) || text(raw.name, 40) }
}

export function parseView(raw: any): View | null {
  if (raw?.protocol !== 1) return null
  const s = raw.status ?? {}
  const asks: Ask[] = list(raw.asks, 10)
    .map((a: any): Ask | null => {
      const id = text(a?.id, 40)
      if (!/^[A-Za-z0-9_-]+$/.test(id) || !text(a?.title)) return null
      const secs = Number(a?.seconds_left)
      return {
        id,
        title: text(a.title, 80),
        subtitle: text(a.subtitle, 120),
        lines: list(a.lines, 8).map(line).filter((l): l is Line => !!l),
        note: text(a.note, 240),
        approveLabel: text(a.approve_label, 20) || 'Approve',
        rejectLabel: text(a.reject_label, 20) || 'Reject',
        secondsLeft: Number.isFinite(secs) ? Math.max(0, Math.min(3600, Math.floor(secs))) : 0,
        tone: tone(a.tone) ?? 'neutral',
      }
    })
    .filter((a): a is Ask => !!a)
  const sections: Section[] = list(raw.sections, 20)
    .map((v: any): Section | null => {
      if (v?.type === 'stats') return { type: 'stats', title: text(v.title, 60) || undefined, items: list(v.items, 12).map(line).filter((l): l is Line => !!l) }
      if (v?.type === 'list')
        return {
          type: 'list',
          title: text(v.title, 60),
          empty: text(v.empty, 80) || undefined,
          rows: list(v.rows, 50)
            .filter((r: any) => text(r?.title))
            .map((r: any) => ({ title: text(r.title, 100), subtitle: text(r.subtitle, 200), value: text(r.value, 40), tone: tone(r.tone) })),
        }
      if (v?.type === 'actions')
        return {
          type: 'actions',
          actions: list(v.actions, 4)
            .filter((a: any) => /^[a-z0-9_-]+$/.test(text(a?.id, 40)) && text(a?.label))
            .map((a: any) => ({ id: text(a.id, 40), label: text(a.label, 40), style: a.style === 'danger' ? 'danger' : 'default', confirm: text(a.confirm, 200) || undefined })),
        }
      if (v?.type === 'note' && text(v.text)) return { type: 'note', text: text(v.text, 300), tone: tone(v.tone) }
      return null
    })
    .filter((x): x is Section => !!x)
  return {
    updatedAt: Number(raw.updated_at) || 0,
    status: { text: text(s.text, 40), short: text(s.short, 12) || text(s.text, 12), tone: tone(s.tone) ?? 'neutral', detail: text(s.detail, 120), show: s.show === true },
    asks,
    sections,
  }
}

export function parseNotify(raw: any): Notify | null {
  if (!text(raw?.title)) return null
  return { title: text(raw.title, 100), body: text(raw.body, 240), urgency: raw.urgency === 'critical' || raw.urgency === 'low' ? raw.urgency : 'normal' }
}
