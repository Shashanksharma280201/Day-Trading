import { useEffect, useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import type { Ask } from '../protocol'
import { C, toneColor } from './theme'

/**
 * A trade waiting for you: what, how much, the risk, and a countdown. No
 * answer before it runs out means no trade.
 */
export function AskCard({ ask, deadline, onAnswer }: { ask: Ask; deadline: number; onAnswer: (approve: boolean) => Promise<void> }) {
  const [now, setNow] = useState(Date.now())
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const left = Math.max(0, Math.ceil((deadline - now) / 1000))
  const answer = async (approve: boolean) => {
    setBusy(true)
    await onAnswer(approve)
    setBusy(false)
  }
  const accent = ask.tone === 'down' ? C.red : C.green
  return (
    <View style={[s.card, { borderColor: accent }]}>
      <View style={s.head}>
        <Text style={[s.title, { color: accent }]}>{ask.title}</Text>
        <Text style={[s.timer, left <= 10 && { color: C.orange }]}>{left}s</Text>
      </View>
      {!!ask.subtitle && <Text style={s.sub}>{ask.subtitle}</Text>}
      <View style={s.grid}>
        {ask.lines.map((l, i) => (
          <View key={i} style={s.line}>
            <Text style={s.label}>{l.label}</Text>
            <Text style={[s.value, { color: toneColor(l.tone) }]}>{l.value}</Text>
          </View>
        ))}
      </View>
      {!!ask.note && <Text style={s.note}>{ask.note}</Text>}
      <View style={s.buttons}>
        <Pressable disabled={busy || left === 0} onPress={() => void answer(false)} style={({ pressed }) => [s.btn, s.reject, pressed && s.pressed, (busy || left === 0) && s.disabled]}>
          <Text style={s.btnText}>{ask.rejectLabel}</Text>
        </Pressable>
        <Pressable disabled={busy || left === 0} onPress={() => void answer(true)} style={({ pressed }) => [s.btn, { backgroundColor: accent }, pressed && s.pressed, (busy || left === 0) && s.disabled]}>
          <Text style={[s.btnText, { color: '#000' }]}>{busy ? 'Sending…' : ask.approveLabel}</Text>
        </Pressable>
      </View>
    </View>
  )
}

const s = StyleSheet.create({
  card: { backgroundColor: C.card, borderRadius: 18, padding: 16, borderWidth: 1.5, marginBottom: 12 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontSize: 22, fontWeight: '700' },
  timer: { color: C.text2, fontSize: 15, fontWeight: '700', fontVariant: ['tabular-nums'] },
  sub: { color: C.text2, marginTop: 2 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 12 },
  line: { width: '50%', paddingVertical: 4, paddingRight: 10 },
  label: { color: C.text3, fontSize: 12 },
  value: { fontSize: 15, fontWeight: '600', fontVariant: ['tabular-nums'] },
  note: { color: C.text2, fontSize: 12, marginTop: 8 },
  buttons: { flexDirection: 'row', gap: 10, marginTop: 14 },
  btn: { flex: 1, borderRadius: 14, paddingVertical: 14, alignItems: 'center' },
  reject: { backgroundColor: C.card2 },
  btnText: { color: C.text, fontSize: 16, fontWeight: '700' },
  pressed: { opacity: 0.7 },
  disabled: { opacity: 0.4 },
})
