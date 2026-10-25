import { useEffect, useRef, useState } from 'react'
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Switch, Text, View } from 'react-native'
import type { EngineLink, LinkState } from '../link'
import { AskCard } from './AskCard'
import { Sections } from './Sections'
import { C, toneColor } from './theme'

/** The engine's view: status, trades waiting for you, then its sections. */
export function HomeScreen({ link, live, setLive, liveAvailable, onUnpair }: { link: EngineLink; live: boolean; setLive: (on: boolean) => void; liveAvailable: boolean; onUnpair: () => void }) {
  const [st, setSt] = useState<LinkState>(link.state)
  const [refreshing, setRefreshing] = useState(false)
  // Each card's countdown is fixed when it first arrives (views come every second).
  const deadlines = useRef(new Map<string, number>())
  useEffect(() => link.subscribe(setSt), [link])

  const v = st.view
  for (const a of v?.asks ?? []) if (!deadlines.current.has(a.id)) deadlines.current.set(a.id, Date.now() + a.secondsLeft * 1000)
  for (const id of [...deadlines.current.keys()]) if (!v?.asks.some((a) => a.id === id)) deadlines.current.delete(id)

  return (
    <ScrollView
      style={s.wrap}
      contentContainerStyle={{ padding: 16, paddingTop: 54, paddingBottom: 40 }}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={C.green}
          onRefresh={async () => {
            setRefreshing(true)
            await link.refresh()
            setRefreshing(false)
          }}
        />
      }
    >
      <View style={s.top}>
        <Text style={s.h1}>{st.manifest?.tabTitle ?? 'Trading'}</Text>
        <Text style={[s.phase, st.phase === 'live' ? { color: C.green } : st.phase === 'offline' ? { color: C.red } : null]}>{st.phase === 'live' ? '● Live' : st.phase === 'connecting' ? 'Connecting…' : 'Offline'}</Text>
      </View>
      {st.phase === 'offline' && !!st.error && <Text style={s.error}>{st.error}</Text>}

      {v && (
        <View style={s.statusCard}>
          <Text style={[s.big, { color: toneColor(v.status.tone) }]}>{v.status.text || 'No data yet'}</Text>
          <Text style={s.detail}>{v.status.detail}</Text>
        </View>
      )}

      {v?.asks.map((a) => (
        <AskCard
          key={a.id}
          ask={a}
          deadline={deadlines.current.get(a.id) ?? Date.now()}
          onAnswer={async (approve) => {
            const res = await link.answer(a.id, approve)
            if (!res.ok && res.message) Alert.alert(approve ? 'Not placed' : 'Couldn’t send', res.message)
          }}
        />
      ))}

      {v && <Sections sections={v.sections} onAction={(id) => link.action(id)} />}

      <View style={s.settings}>
        <View style={s.settingRow}>
          <View style={{ flex: 1 }}>
            <Text style={s.settingTitle}>Live notification</Text>
            <Text style={s.settingHint}>{liveAvailable ? 'Keeps the connection alive in the background so trades reach you within seconds. Turn off after the market closes.' : 'Needs the installed app (not Expo Go).'}</Text>
          </View>
          <Switch value={live && liveAvailable} disabled={!liveAvailable} onValueChange={setLive} trackColor={{ true: C.green }} />
        </View>
        <Pressable
          onPress={() =>
            Alert.alert('Unpair this phone?', 'You can pair again by scanning the QR.', [
              { text: 'Cancel', style: 'cancel' },
              { text: 'Unpair', style: 'destructive', onPress: onUnpair },
            ])
          }
        >
          <Text style={s.unpair}>Unpair</Text>
        </Pressable>
      </View>
    </ScrollView>
  )
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: C.bg },
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 },
  h1: { color: C.text, fontSize: 30, fontWeight: '800' },
  phase: { color: C.text2, fontWeight: '700' },
  error: { color: C.red, marginBottom: 12 },
  statusCard: { backgroundColor: C.card, borderRadius: 18, padding: 18, marginBottom: 12 },
  big: { fontSize: 36, fontWeight: '800', fontVariant: ['tabular-nums'] },
  detail: { color: C.text2, marginTop: 4 },
  settings: { marginTop: 18, backgroundColor: C.card, borderRadius: 16, padding: 14 },
  settingRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  settingTitle: { color: C.text, fontSize: 15, fontWeight: '600' },
  settingHint: { color: C.text3, fontSize: 12, marginTop: 2 },
  unpair: { color: C.red, fontWeight: '600', marginTop: 16, textAlign: 'center' },
})
