import { requireOptionalNativeModule } from 'expo'

type LiveStatusModule = {
  start(title: string, text: string): void
  update(title: string, text: string): void
  stop(): void
  isRunning(): boolean
}

/**
 * The live status notification (Android foreground service). Missing in Expo Go
 * and on iOS: then the app still works, but only while it's open.
 */
const native = requireOptionalNativeModule<LiveStatusModule>('LiveStatus')

export const liveStatus = {
  available: !!native,
  start: (title: string, text: string) => native?.start(title, text),
  update: (title: string, text: string) => native?.update(title, text),
  stop: () => native?.stop(),
  isRunning: () => native?.isRunning() ?? false,
}
