import type { Tone } from '../protocol'

export const C = {
  bg: '#0b0c0f',
  card: '#16181d',
  card2: '#1e2128',
  line: 'rgba(255,255,255,0.08)',
  text: '#f5f5f7',
  text2: 'rgba(235,235,245,0.62)',
  text3: 'rgba(235,235,245,0.36)',
  green: '#30d158',
  red: '#ff453a',
  orange: '#ff9f0a',
  blue: '#0a84ff',
}

export const toneColor = (t?: Tone) => (t === 'up' ? C.green : t === 'down' ? C.red : t === 'warn' ? C.orange : C.text)
