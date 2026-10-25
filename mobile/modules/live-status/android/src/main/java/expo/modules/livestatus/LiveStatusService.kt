package expo.modules.livestatus

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/**
 * A foreground service whose only job is to keep this app's process (and so
 * its connection to your trading engine) alive while the market is open, and
 * to show today's status as an ongoing notification. The app updates the text.
 */
class LiveStatusService : Service() {
  companion object {
    const val CHANNEL_ID = "live_status"
    const val NOTIFICATION_ID = 4711
    const val EXTRA_TITLE = "title"
    const val EXTRA_TEXT = "text"

    fun ensureChannel(context: Context) {
      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
      val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
      if (manager.getNotificationChannel(CHANNEL_ID) != null) return
      val channel = NotificationChannel(CHANNEL_ID, "Live status", NotificationManager.IMPORTANCE_LOW)
      channel.description = "Today's P&L while the app watches your trading engine"
      channel.setShowBadge(false)
      channel.lockscreenVisibility = Notification.VISIBILITY_PRIVATE
      manager.createNotificationChannel(channel)
    }

    fun build(context: Context, title: String, text: String): Notification {
      ensureChannel(context)
      val launch = context.packageManager.getLaunchIntentForPackage(context.packageName)
      val open = PendingIntent.getActivity(
        context,
        0,
        launch,
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
      )
      val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        Notification.Builder(context, CHANNEL_ID)
      } else {
        @Suppress("DEPRECATION")
        Notification.Builder(context)
      }
      return builder
        .setContentTitle(title)
        .setContentText(text)
        .setSmallIcon(context.applicationInfo.icon)
        .setContentIntent(open)
        .setOngoing(true)
        .setOnlyAlertOnce(true)
        .setShowWhen(false)
        .setVisibility(Notification.VISIBILITY_PRIVATE)
        .build()
    }
  }

  override fun onBind(intent: Intent?): IBinder? = null

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    val title = intent?.getStringExtra(EXTRA_TITLE) ?: "Trading"
    val text = intent?.getStringExtra(EXTRA_TEXT) ?: "Connecting…"
    val notification = build(this, title, text)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
      startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
    } else {
      startForeground(NOTIFICATION_ID, notification)
    }
    // If Android kills the app, don't come back on our own: nothing would be connected.
    return START_NOT_STICKY
  }

  override fun onTaskRemoved(rootIntent: Intent?) {
    // Swiping the app away stops watching.
    stopSelf()
    super.onTaskRemoved(rootIntent)
  }
}
