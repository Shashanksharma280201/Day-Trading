import { useState } from 'react'
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native'
import type { Section } from '../protocol'
import { C, toneColor } from './theme'

/** The engine's sections, top to bottom: the same ones the island's tab shows. */
export function Sections({ sections, onAction }: { sections: Section[]; onAction: (id: string) => Promise<{ ok: boolean; message: string }> }) {
  return (
    <View>
      {sections.map((sec, i) => (
        <SectionView key={i} sec={sec} onAction={onAction} />
      ))}
    </View>
  )
}

function SectionView({ sec, onAction }: { sec: Section; onAction: (id: string) => Promise<{ ok: boolean; message: string }> }) {
  const [msg, setMsg] = useState<string | null>(null)
  switch (sec.type) {
    case 'stats':
      return (
        <View style={s.grid}>
          {sec.items.map((it, i) => (
            <View key={i} style={s.stat}>
              <Text style={s.statLabel}>{it.label}</Text>
              <Text style={[s.statValue, { color: toneColor(it.tone) }]}>{it.value}</Text>
            </View>
          ))}
        </View>
      )
    case 'list':
      return (
        <View style={s.block}>
          {!!sec.title && <Text style={s.group}>{sec.title}</Text>}
          {sec.rows.length === 0 ? (
            <Text style={s.empty}>{sec.empty ?? 'Nothing here'}</Text>
          ) : (
            sec.rows.map((r, i) => (
              <View key={i} style={s.row}>
                <View style={{ flex: 1 }}>
                  <Text style={s.rowTitle}>{r.title}</Text>
                  {!!r.subtitle && <Text style={s.rowSub}>{r.subtitle}</Text>}
                </View>
                {!!r.value && <Text style={[s.rowValue, { color: toneColor(r.tone) }]}>{r.value}</Text>}
              </View>
            ))
          )}
        </View>
      )
    case 'actions':
      return (
        <View style={s.block}>
          {sec.actions.map((a) => (
            <Pressable
              key={a.id}
              style={({ pressed }) => [s.action, a.style === 'danger' && s.danger, pressed && { opacity: 0.7 }]}
              onPress={() => {
                const go = async () => {
                  const res = await onAction(a.id)
                  setMsg(res.message || (res.ok ? 'Done' : 'It didn’t work'))
                }
                if (a.confirm) Alert.alert(a.label, a.confirm, [{ text: 'Cancel', style: 'cancel' }, { text: a.label, style: a.style === 'danger' ? 'destructive' : 'default', onPress: () => void go() }])
                else void go()
              }}
            >
              <Text style={[s.actionText, a.style === 'danger' && { color: C.red }]}>{a.label}</Text>
            </Pressable>
          ))}
          {!!msg && <Text style={s.empty}>{msg}</Text>}
        </View>
      )
    case 'note':
      return <Text style={[s.note, { color: sec.tone === 'warn' ? C.orange : C.text2 }]}>{sec.text}</Text>
  }
}

const s = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', marginHorizontal: -4, marginBottom: 6 },
  stat: { width: '50%', padding: 4 },
  statLabel: { color: C.text3, fontSize: 12, backgroundColor: C.card, borderTopLeftRadius: 12, borderTopRightRadius: 12, paddingHorizontal: 12, paddingTop: 10 },
  statValue: { fontSize: 16, fontWeight: '600', fontVariant: ['tabular-nums'], backgroundColor: C.card, borderBottomLeftRadius: 12, borderBottomRightRadius: 12, paddingHorizontal: 12, paddingBottom: 10 },
  block: { backgroundColor: C.card, borderRadius: 16, padding: 12, marginBottom: 12 },
  group: { color: C.text3, fontSize: 12, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 },
  empty: { color: C.text3, paddingVertical: 4 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 7, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.line },
  rowTitle: { color: C.text, fontSize: 14, fontWeight: '600' },
  rowSub: { color: C.text3, fontSize: 12, marginTop: 1 },
  rowValue: { fontSize: 14, fontWeight: '700', marginLeft: 10, fontVariant: ['tabular-nums'] },
  action: { paddingVertical: 13, alignItems: 'center', borderRadius: 12, backgroundColor: C.card2, marginVertical: 4 },
  danger: { backgroundColor: 'rgba(255,69,58,0.12)' },
  actionText: { color: C.text, fontSize: 15, fontWeight: '700' },
  note: { fontSize: 12, marginVertical: 8, textAlign: 'center' },
})
