package com.cxsign.sentinel

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.PowerManager
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 常驻扫码：把手机架在那里，摄像头对着老师的屏幕（投影 / 电脑 / 同学手机），
 * 出现二维码就自动解、自动提交。全程不需要人碰。
 *
 * 为什么能做到「不用手动扫」：
 *   二维码里的 enc 不在任何学生端接口里（getPPTActiveInfo 的 118 个字段全扫过，
 *   widget/sign/e 不带 enc 直接 500，通知接口里没有签到）。它只存在于老师屏幕上
 *   那张图。所以「自动」= 「有只眼睛一直盯着看」，而不是「去调一个接口」。
 *
 * 省电设计：
 *   · 每 12 秒问一次引擎「现在有二维码签到在等码吗」
 *   · 没有 -> 一帧都不分析（摄像头开着但空转，功耗很低）
 *   · 有   -> 每秒最多分析 2 帧
 *   · 签成功 -> 立刻停止分析，等下一轮
 */
class AutoScanService : LifecycleService() {

    companion object {
        private const val CH_ID = "cx_autoscan"
        private const val NOTI_ID = 1002
        const val ACTION_START = "com.cxsign.sentinel.AUTOSCAN_START"
        const val ACTION_STOP = "com.cxsign.sentinel.AUTOSCAN_STOP"

        fun start(ctx: Context) {
            val i = Intent(ctx, AutoScanService::class.java).setAction(ACTION_START)
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i)
            else ctx.startService(i)
        }

        fun stop(ctx: Context) {
            ctx.startService(Intent(ctx, AutoScanService::class.java).setAction(ACTION_STOP))
        }
    }

    private val executor = Executors.newSingleThreadExecutor()
    private val busy = AtomicBoolean(false)
    private val handling = AtomicBoolean(false)
    private var camera: Camera? = null
    private var analysis: ImageAnalysis? = null
    private var running = false

    /** 引擎那边有没有二维码签到在等码。没有就不必分析帧。 */
    @Volatile private var watching = false
    @Volatile private var lastFrameAt = 0L
    @Volatile private var lastHit = ""
    @Volatile private var lastHitAt = 0L

    private val scanner: BarcodeScanner by lazy {
        BarcodeScanning.getClient(
            BarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build()
        )
    }

    private val wakeLock: PowerManager.WakeLock? by lazy {
        (getSystemService(Context.POWER_SERVICE) as? PowerManager)
            ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "cxsign:autoscan")
            ?.apply { setReferenceCounted(false) }
    }

    override fun onCreate() {
        super.onCreate()
        EngineClient.init(this)
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (!running) {
            running = true
            startForeground(NOTI_ID, noti("自动扫码已启动", "等待二维码签到"))
            wakeLock?.acquire(60 * 60 * 1000L)
            startCamera()
            Thread { ticker() }.start()
        }
        return START_STICKY
    }

    // ---------------------------------------------------------------- 轮询状态

    private fun ticker() {
        while (running) {
            try {
                val st = EngineClient.status()
                val d = st.optJSONObject("data")
                val pending = d?.optJSONArray("pending")?.length() ?: 0
                val on = pending > 0
                if (on != watching) {
                    watching = on
                    notifyText(
                        if (on) "⏳ 正在自动找码（$pending 个签到在等）" else "待命 · 没有等码的签到"
                    )
                }
            } catch (_: Throwable) {
            }
            try {
                Thread.sleep(12_000)
            } catch (_: InterruptedException) {
                break
            }
        }
    }

    // ---------------------------------------------------------------- 相机

    private fun startCamera() {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            try {
                val provider = future.get()
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(executor, ::analyze)
                this.analysis = analysis

                val selector = CameraSelector.DEFAULT_BACK_CAMERA
                provider.unbindAll()
                camera = provider.bindToLifecycle(this, selector, analysis)
                notifyText("摄像头已就绪，只等二维码签到")
            } catch (t: Throwable) {
                notifyText("相机启动失败：${t.message}")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyze(proxy: ImageProxy) {
        val now = System.currentTimeMillis()

        // 没在等码 / 上一帧还没处理完 / 帧太密 -> 直接丢
        if (!watching || busy.get() || now - lastFrameAt < 500) {
            proxy.close()
            return
        }
        lastFrameAt = now
        busy.set(true)

        val media = proxy.image
        if (media == null) {
            busy.set(false)
            proxy.close()
            return
        }

        val image = InputImage.fromMediaImage(media, proxy.imageInfo.rotationDegrees)
        scanner.process(image)
            .addOnSuccessListener { codes -> onCodes(codes) }
            .addOnCompleteListener {
                busy.set(false)
                proxy.close()
            }
            .addOnFailureListener {
                busy.set(false)
                proxy.close()
            }
    }

    private fun onCodes(codes: List<Barcode>) {
        for (code in codes) {
            val raw = code.rawValue ?: continue
            if (!looksLikeSignQr(raw)) continue

            val now = System.currentTimeMillis()
            // 同一段内容 8 秒内不重复提交（轮换码每 10 秒变一次，但 enc 常常不变）
            if (raw == lastHit && now - lastHitAt < 8_000) continue
            lastHit = raw
            lastHitAt = now

            if (handling.compareAndSet(false, true)) {
                EngineClient.io {
                    try {
                        val r = EngineClient.feedQrText(raw)
                        val n = r.optJSONArray("results")?.length() ?: 0
                        if (n > 0) {
                            val first = r.getJSONArray("results").optJSONObject(0)
                            val okState = first?.optString("state") == "SIGNED"
                            notifyText(
                                if (okState) "✅ 已签到：${first?.optString("name")}"
                                else "尝试过：${first?.optString("message")}"
                            )
                            // 签成功就暂时不看了，等下一条 pending
                            watching = false
                        }
                    } catch (_: Throwable) {
                    } finally {
                        handling.set(false)
                    }
                }
            }
            return
        }
    }

    /** 只处理看起来像学习通签到的码，避免把桌上的商品二维码也提交上去。 */
    private fun looksLikeSignQr(raw: String): Boolean =
        raw.contains("mobilelearn.chaoxing.com", true) ||
                raw.startsWith("SIGNIN", true) ||
                raw.contains("widget/sign", true)

    // ---------------------------------------------------------------- 通知

    private fun notifyText(text: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm?.notify(NOTI_ID, noti("自动扫码", text))
    }

    private fun noti(title: String, body: String): Notification {
        val b = if (Build.VERSION.SDK_INT >= 26) {
            Notification.Builder(this, CH_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return b.setContentTitle(title)
            .setContentText(body)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val nm = getSystemService(NotificationManager::class.java)
        val ch = NotificationChannel(CH_ID, "自动扫码", NotificationManager.IMPORTANCE_LOW)
        ch.description = "摄像头盯着屏幕找签到二维码"
        nm.createNotificationChannel(ch)
    }

    override fun onDestroy() {
        running = false
        watching = false
        try {
            analysis?.clearAnalyzer()
        } catch (_: Throwable) {
        }
        try {
            ProcessCameraProvider.getInstance(this).get().unbindAll()
        } catch (_: Throwable) {
        }
        wakeLock?.let { if (it.isHeld) it.release() }
        executor.shutdownNow()
        super.onDestroy()
    }
}
