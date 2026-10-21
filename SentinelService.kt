package com.cxsign.sentinel

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import org.json.JSONObject

/**
 * 常驻服务：让「时刻检测签到」这件事真的成立。
 *
 * 职责只有三件：
 *   1. 前台通知（系统才不会在后台把它杀掉）
 *   2. 挂上相册监听（二维码通道 2）
 *   3. 每 20 秒问一次引擎状态，把「待取码 / 已签到 / 登录失效」写进通知
 *
 * 轮询本身在引擎里（Python），不在这里 —— 引擎才是唯一知道活动列表的人。
 * 这样 App 关掉、服务被杀，签到逻辑照样在引擎那边跑。
 */
class SentinelService : Service() {

    companion object {
        private const val TAG = "CxSentinel"
        private const val CH_ID = "cx_signin"
        private const val NOTI_ID = 1001
        const val ACTION_START = "com.cxsign.sentinel.START"
        const val ACTION_STOP = "com.cxsign.sentinel.STOP"
        const val EXTRA_QR_TEXT = "qr_text"

        fun start(ctx: Context) {
            val i = Intent(ctx, SentinelService::class.java).setAction(ACTION_START)
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i)
            else ctx.startService(i)
        }

        fun stop(ctx: Context) {
            ctx.startService(Intent(ctx, SentinelService::class.java).setAction(ACTION_STOP))
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private var media: MediaObserver? = null
    private var running = false

    /** 二维码扫到就当场投递，不依赖任何界面。 */
    private val qrReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context?, intent: Intent?) {
            val text = intent?.getStringExtra(EXTRA_QR_TEXT) ?: return
            if (QrNotificationWatcher.shouldHandle(text)) {
                EngineClient.io { EngineClient.feedQrText(text) }
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        EngineClient.init(this)
        createChannel()
        registerReceiver(
            qrReceiver,
            IntentFilter("com.cxsign.sentinel.QR"),
            if (Build.VERSION.SDK_INT >= 33) RECEIVER_NOT_EXPORTED else 0
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (!running) {
            startForeground(NOTI_ID, buildNotification("正在连接引擎…", "等待第一次轮询"))
            media = MediaObserver(this).also { it.start() }
            running = true
            tick()
        }
        return START_STICKY          // 被杀后系统会尽量拉起来
    }

    private fun tick() {
        if (!running) return
        EngineClient.io {
            val st = EngineClient.status()
            val text = summarize(st)
            handler.post {
                if (running) {
                    val nm = getSystemService(NotificationManager::class.java)
                    nm.notify(NOTI_ID, buildNotification(text.first, text.second))
                }
            }
        }
        handler.postDelayed({ tick() }, 20_000)
    }

    /** 把引擎状态压成两行通知文案。 */
    private fun summarize(st: JSONObject): Pair<String, String> {
        if (!st.optBoolean("ok", false)) {
            return "引擎未连接" to "检查设置里的地址，或先启动 run.py serve"
        }
        val d = st.optJSONObject("data") ?: return "引擎在线" to ""
        val login = d.optJSONObject("login")
        val uid = login?.optString("uid").orEmpty()
        if (uid.isBlank()) return "未登录" to "点开 App 导入 cookie"

        val signed = d.optInt("signed", 0)
        val pending = d.optJSONArray("pending")?.length() ?: 0
        val courses = d.optInt("courses", 0)
        val stats = d.optJSONObject("stats")
        val rounds = stats?.optInt("polls", 0) ?: 0

        val title = when {
            pending > 0 -> "⏳ 有 $pending 个签到在等二维码"
            else -> "监听中 · 已签 $signed 次"
        }
        val body = "课程 $courses · 轮询 $rounds 轮" +
                if (pending > 0) " · 去 App 里扫一下码" else ""
        return title to body
    }

    private fun buildNotification(title: String, body: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val b = if (Build.VERSION.SDK_INT >= 26) {
            Notification.Builder(this, CH_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return b.setContentTitle(title)
            .setContentText(body)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .build()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val nm = getSystemService(NotificationManager::class.java)
        val ch = NotificationChannel(CH_ID, "签到监听", NotificationManager.IMPORTANCE_LOW)
        ch.description = "常驻监听签到任务，低打扰"
        ch.setShowBadge(false)
        nm.createNotificationChannel(ch)
    }

    override fun onDestroy() {
        running = false
        handler.removeCallbacksAndMessages(null)
        media?.stop()
        try {
            unregisterReceiver(qrReceiver)
        } catch (_: Throwable) {
        }
        super.onDestroy()
        Log.d(TAG, "service destroyed")
    }
}
