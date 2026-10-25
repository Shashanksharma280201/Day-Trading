import * as SecureStore from 'expo-secure-store'

export type Pairing = { url: string; token: string }

const KEY = 'daytrader.pairing'

/** daytrader://pair?url=http%3A%2F%2F100.64.0.1%3A8765&token=... -> { url, token }, or null. */
export function parsePairingLink(link: string): Pairing | null {
  const m = /^daytrader:\/\/pair\?(.*)$/.exec(link.trim())
  if (!m) return null
  const params: Record<string, string> = {}
  for (const part of m[1].split('&')) {
    const [k, v = ''] = part.split('=')
    try {
      params[decodeURIComponent(k)] = decodeURIComponent(v)
    } catch {
      return null
    }
  }
  return cleanPairing(params.url ?? '', params.token ?? '')
}

/** An http(s) address and a token that look right, or null. */
export function cleanPairing(url: string, token: string): Pairing | null {
  const u = url.trim().replace(/\/+$/, '')
  const t = token.trim()
  if (!/^https?:\/\/[^\s/@]+(:\d+)?$/.test(u) || t.length < 16 || /\s/.test(t)) return null
  return { url: u, token: t }
}

export async function loadPairing(): Promise<Pairing | null> {
  try {
    const raw = await SecureStore.getItemAsync(KEY)
    if (!raw) return null
    const p = JSON.parse(raw)
    return cleanPairing(p.url ?? '', p.token ?? '')
  } catch {
    return null
  }
}

export async function savePairing(p: Pairing): Promise<void> {
  await SecureStore.setItemAsync(KEY, JSON.stringify(p))
}

export async function forgetPairing(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY)
}
