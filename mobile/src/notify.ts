import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'
import { liveStatus } from '../modules/live-status'
import type { EngineLink, LinkState } from './link'
import type { Ask, Notify } from './protocol'

/**
 * Notifications on the phone:
 * - live status: today's P&L as an ongoing notification (a foreground
 *   service keeps the connection alive while the market is open);
 * - one notification per trade waiting for you, with its buttons. Private on
 *   the lock screen, so nobody can approve from a locked phone;
 * - heads-ups (position closed, alerts) like the island's.
 */
const CH_ASKS = 'trade-approvals'
const CH_UPDATES = 'trade-updates'
const ASK_PREFIX = 'ask-'
const CATEGORIES: Record<string, { approve: string; reject: string }> = {
  'ask-buy': { approve: 'Buy', reject: 'Skip' },
  'ask-sell': { approve: 'Sell', reject: 'Skip' },
  'ask-generic': { approve: 'Approve', reject: 'Reject' },
}

export async function setupNotifications(): Promise<boolean> {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
  })
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync(CH_ASKS, {
      name: 'Trades waiting for you',
      importance: Notifications.AndroidImportance.MAX,
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PRIVATE,
      vibrationPattern: [0, 250, 150, 250],
    })
    await Notifications.setNotificationChannelAsync(CH_UPDATES, {
      name: 'Trade updates',
      importance: Notifications.AndroidImportance.DEFAULT,
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PRIVATE,
    })
  }
  for (const [id, labels] of Object.entries(CATEGORIES)) {
    await Notifications.setNotificationCategoryAsync(id, [
      // Answering from the notification needs the app running, which the live status keeps.
      { identifier: 'reject', buttonTitle: labels.reject, options: { opensAppToForeground: false } },
      { identifier: 'approve', buttonTitle: labels.approve, options: { opensAppToForeground: false } },
    ])
  }
  const perm = await Notifications.getPermissionsAsync()
  if (perm.granted) return true
  return (await Notifications.requestPermissionsAsync()).granted
}

/** Show it now, on this Android channel. */
const now = (channelId: string): Notifications.NotificationTriggerInput => (Platform.OS === 'android' ? { channelId } : null)

const categoryFor = (a: Ask) => (a.approveLabel === 'Buy' ? 'ask-buy' : a.approveLabel === 'Sell' ? 'ask-sell' : 'ask-generic')

/** Keep the phone's notifications in step with the engine's view. */
export function followLink(link: EngineLink, opts: { live: () => boolean }): () => void {
  const shown = new Set<string>()
  let lastStatus = ''

  const sync = async (s: LinkState) => {
    const name = s.manifest?.name ?? 'Trading'
    // Live status (ongoing notification).
    const title = s.view ? `${name} ${s.view.status.text}` : name
    const text = s.phase === 'live' ? (s.view?.status.detail ?? 'Connected') : s.phase === 'connecting' ? 'Connecting…' : `Offline: ${s.error ?? 'reconnecting'}`
    if (opts.live() && liveStatus.available) {
      if (!liveStatus.isRunning()) liveStatus.start(title, text)
      else if (`${title}|${text}` !== lastStatus) liveStatus.update(title, text)
      lastStatus = `${title}|${text}`
    }
    // One notification per waiting trade; gone when answered or expired.
    const asks = s.view?.asks ?? []
    const wanted = new Set(asks.map((a) => ASK_PREFIX + a.id))
    for (const a of asks) {
      const id = ASK_PREFIX + a.id
      if (shown.has(id)) continue
      shown.add(id)
      await Notifications.scheduleNotificationAsync({
        identifier: id,
        content: {
          title: `${name}: ${a.title}`,
          body: [a.lines.map((l) => `${l.label} ${l.value}`).join(' · '), `Answer within ${a.secondsLeft}s`].filter(Boolean).join('\n'),
          data: { askId: a.id },
          categoryIdentifier: categoryFor(a),
          sticky: true,
          autoDismiss: true,
          color: a.tone === 'down' ? '#ff453a' : '#30d158',
        },
        trigger: now(CH_ASKS),
      })
    }
    for (const id of [...shown]) {
      if (wanted.has(id)) continue
      shown.delete(id)
      await Notifications.dismissNotificationAsync(id).catch(() => {})
    }
  }

  const offState = link.subscribe((s) => void sync(s))
  const offNotify = link.onNotify((n: Notify) => {
    void Notifications.scheduleNotificationAsync({
      content: { title: n.title, body: n.body },
      trigger: now(CH_UPDATES),
    })
  })
  // A button on a trade's notification: only a person's tap gets here.
  const offResponse = Notifications.addNotificationResponseReceivedListener((r) => {
    const askId = r.notification.request.content.data?.askId
    const action = r.actionIdentifier
    if (typeof askId !== 'string' || (action !== 'approve' && action !== 'reject')) return
    void Notifications.dismissNotificationAsync(r.notification.request.identifier).catch(() => {})
    void link.answer(askId, action === 'approve').then((res) => {
      if (!res.ok && res.message)
        void Notifications.scheduleNotificationAsync({
          content: { title: action === 'approve' ? 'Not placed' : 'Couldn’t send your answer', body: res.message },
          trigger: now(CH_UPDATES),
        })
    })
  })
  return () => {
    offState()
    offNotify()
    offResponse.remove()
    liveStatus.stop()
    void Notifications.dismissAllNotificationsAsync()
  }
}
