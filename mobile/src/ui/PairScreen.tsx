import { useState } from 'react'
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native'
import { CameraView, useCameraPermissions } from 'expo-camera'
import { cleanPairing, parsePairingLink, type Pairing } from '../pairing'
import { testPairing } from '../link'
import { C } from './theme'

/**
 * Pair with your trading engine: scan the QR in the island's Settings →
 * Connected (or paste the pairing link the server prints), or type the
 * address and token yourself. It's tried before it's saved.
 */
export function PairScreen({ onPaired }: { onPaired: (p: Pairing) => void }) {
  const [perm, requestPerm] = useCameraPermissions()
  const [scanning, setScanning] = useState(false)
  const [link, setLink] = useState('')
  const [url, setUrl] = useState('http://100.')
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const tryPair = async (p: Pairing | null) => {
    if (!p) return setError('That isn’t a pairing link, or the address or token looks wrong.')
    setBusy(true)
    setError(null)
    const err = await testPairing(p)
    setBusy(false)
    if (err) setError(err)
    else onPaired(p)
  }

  if (scanning)
    return (
      <View style={{ flex: 1, backgroundColor: '#000' }}>
        <CameraView
          style={{ flex: 1 }}
          facing="back"
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
          onBarcodeScanned={({ data }) => {
            if (!data.startsWith('daytrader://pair?')) return
            setScanning(false)
            void tryPair(parsePairingLink(data))
          }}
        />
        <Pressable style={s.cancelScan} onPress={() => setScanning(false)}>
          <Text style={s.btnText}>Cancel</Text>
        </Pressable>
      </View>
    )

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ padding: 20, paddingTop: 60 }} keyboardShouldPersistTaps="handled">
      <Text style={s.h1}>Day-Trading</Text>
      <Text style={s.p}>Pair this phone with the trading engine on your laptop. Your phone and laptop both need Tailscale on, and the engine must be started with --phone-host.</Text>

      <Pressable
        style={({ pressed }) => [s.primary, pressed && { opacity: 0.8 }]}
        onPress={async () => {
          if (!perm?.granted && !(await requestPerm()).granted) return setError('Camera permission is needed to scan. You can paste the link instead.')
          setScanning(true)
        }}
      >
        <Text style={[s.btnText, { color: '#000' }]}>Scan the QR</Text>
      </Pressable>
      <Text style={s.hint}>On your laptop: Dynamic Island → Settings → Connected → Show QR.</Text>

      <Text style={s.label}>Or paste the pairing link</Text>
      <TextInput style={s.input} value={link} onChangeText={setLink} placeholder="daytrader://pair?url=…&token=…" placeholderTextColor={C.text3} autoCapitalize="none" autoCorrect={false} />
      <Pressable style={s.secondary} disabled={busy} onPress={() => void tryPair(parsePairingLink(link))}>
        <Text style={s.btnText}>Pair with link</Text>
      </Pressable>

      <Text style={s.label}>Or type it in</Text>
      <TextInput style={s.input} value={url} onChangeText={setUrl} placeholder="http://100.x.y.z:8765" placeholderTextColor={C.text3} autoCapitalize="none" autoCorrect={false} keyboardType="url" />
      <TextInput style={s.input} value={token} onChangeText={setToken} placeholder="Token (state/api_token)" placeholderTextColor={C.text3} autoCapitalize="none" autoCorrect={false} secureTextEntry />
      <Pressable style={s.secondary} disabled={busy} onPress={() => void tryPair(cleanPairing(url, token))}>
        <Text style={s.btnText}>Pair</Text>
      </Pressable>

      {busy && <ActivityIndicator style={{ marginTop: 16 }} color={C.green} />}
      {!!error && <Text style={s.error}>{error}</Text>}
    </ScrollView>
  )
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: C.bg },
  h1: { color: C.text, fontSize: 32, fontWeight: '800' },
  p: { color: C.text2, fontSize: 15, marginTop: 8, marginBottom: 24, lineHeight: 21 },
  primary: { backgroundColor: C.green, borderRadius: 14, paddingVertical: 15, alignItems: 'center' },
  secondary: { backgroundColor: C.card2, borderRadius: 14, paddingVertical: 13, alignItems: 'center', marginTop: 8 },
  btnText: { color: C.text, fontSize: 16, fontWeight: '700' },
  hint: { color: C.text3, fontSize: 12, marginTop: 8 },
  label: { color: C.text2, fontSize: 13, fontWeight: '600', marginTop: 28, marginBottom: 8 },
  input: { backgroundColor: C.card, color: C.text, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, marginBottom: 8 },
  error: { color: C.red, marginTop: 16, fontSize: 14 },
  cancelScan: { position: 'absolute', bottom: 50, alignSelf: 'center', backgroundColor: 'rgba(0,0,0,0.6)', paddingHorizontal: 28, paddingVertical: 14, borderRadius: 999 },
})
