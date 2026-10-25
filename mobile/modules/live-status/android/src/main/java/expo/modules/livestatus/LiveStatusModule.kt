package expo.modules.livestatus

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Build
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/** start / update / stop the live status notification (a foreground service). */
class LiveStatusModule : Module() {
  private val context: Context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()

  private var running = false

  override fun definition() = ModuleDefinition {
    Name("LiveStatus")

    Function("start") { title: String, text: String ->
      val intent = Intent(context, LiveStatusService::class.java)
        .putExtra(LiveStatusService.EXTRA_TITLE, title)
        .putExtra(LiveStatusService.EXTRA_TEXT, text)
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        context.startForegroundService(intent)
      } else {
        context.startService(intent)
      }
      running = true
    }

    Function("update") { title: String, text: String ->
      if (!running) return@Function
      val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
      manager.notify(LiveStatusService.NOTIFICATION_ID, LiveStatusService.build(context, title, text))
    }

    Function("stop") {
      context.stopService(Intent(context, LiveStatusService::class.java))
      running = false
    }

    Function("isRunning") {
      running
    }
  }
}
