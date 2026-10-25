import { useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, Linking, View } from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { liveStatus } from './modules/live-status'
import { EngineLink } from './src/link'
import { followLink, setupNotifications } from './src/notify'
import { forgetPairing, loadPairing, parsePairingLink, savePairing, type Pairing } from './src/pairing'
import { testPairing } from './src/link'
import { HomeScreen } from './src/ui/HomeScreen'
import { PairScreen } from './src/ui/PairScreen'
import { C } from './src/ui/theme'

export default function App() {
  const [pairing, setPairing] = useState<Pairing | null | undefined>(undefined)
  const [live, setLive] = useState(true)
  const liveRef = useRef(live)
  liveRef.current = live

  // Saved pairing, and pairing links opened from elsewhere (daytrader://pair?…).
  useEffect(() => {
    void loadPairing().then(setPairing)
    const take = async (url: string | null | undefined) => {
      const p = url ? parsePairingLink(url) : null
      if (p && !(await testPairing(p))) {
        await savePairing(p)
        setPairing(p)
      }
    }
    void Linking.getInitialURL().then(take)
    const sub = Linking.addEventListener('url', (e) => void take(e.url))
    return () => sub.remove()
  }, [])

  const link = useMemo(() => (pairing ? new EngineLink(pairing) : null), [pairing])
  useEffect(() => {
    if (!link) return
    let off = () => {}
    void setupNotifications().then(() => {
      off = followLink(link, { live: () => liveRef.current })
    })
    void link.start()
    return () => {
      off()
      link.stop()
    }
  }, [link]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!live) liveStatus.stop()
  }, [live])

  if (pairing === undefined)
    return (
      <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: 'center' }}>
        <ActivityIndicator color={C.green} />
      </View>
    )
  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
      <StatusBar style="light" />
      {pairing && link ? (
        <HomeScreen
          link={link}
          live={live}
          setLive={(on) => {
            setLive(on)
            if (on) void link.refresh()
          }}
          liveAvailable={liveStatus.available}
          onUnpair={async () => {
            await forgetPairing()
            setPairing(null)
          }}
        />
      ) : (
        <PairScreen
          onPaired={async (p) => {
            await savePairing(p)
            setPairing(p)
          }}
        />
      )}
    </View>
  )
}
