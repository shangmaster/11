package com.cxsign.sentinel

import android.app.Notification
import android.content.Context
import android.database.ContentObserver
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.provider.MediaStore
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.util.concurrent.ConcurrentHashMap

/**
 * 二维码自动捕获 —— 「不需要人操作」这个需求真正落地的地方。
 *
 * 三条通道并行，谁先拿到算谁的：
 *
 *   1. 通知栏（本类）：老师的签到通知 / 群里转发的图，缩略图就在 Notification extras 里。
 *      需要用户在系统设置里授予「通知使用权」。
 *   2. 相册（MediaObserver）：学委截图存相册，新图落地就解一次。
 *      只需要 READ_MEDIA_IMAGES。
 *   3. 分享（ShareReceiver）：长按图片 -> 分享 -> 签到哨兵。半自动，但最准。
 *
 * 三条都不是「读别人的聊天记录」——只读系统已经展示出来的通知图片和用户自己存的图。
 */
class QrNotificationWatcher : NotificationListenerService() {

    companion object {
        private const val TAG = "CxQrWatch"

        /** 只处理这几个 App 的通知，其余直接跳过，省电也省误判。 */
        private val WATCHED_PACKAGES = setOf(
            "com.chaoxing.mobile",      // 学习通本体
            "com.tencent.mm",           // 微信
            "com.tencent.mobileqq",     // QQ
            "com.tencent.tim",
            "com.alibaba.android.rimet",// 钉钉
            "com.tencent.wework"        // 企业微信
        )

        /** 同一段文本别重复投递，引擎那边还有一层去重，这里先挡一道。 */
        private val seen = ConcurrentHashMap<String, Long>()

        fun shouldHandle(text: String): Boolean {
            if (text.isBlank()) return false
            val now = System.currentTimeMillis()
            val last = seen[text]
            if (last != null && now - last < 20_000) return false
            seen[text] = now
            if (seen.size > 200) {
                val cut = now - 120_000
                seen.entries.removeAll { it.value < cut }
            }
            return true
        }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val n = sbn?.notification ?: return
        if (sbn.packageName !in WATCHED_PACKAGES) return

        val extras = n.extras ?: return

        // 文本通道：有些老师直接把签到链接/二维码内容贴在通知里
        val texts = buildList {
            extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.let { add(it) }
            extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.let { add(it) }
            extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString()?.let { add(it) }
            extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.let { add(it) }
        }
        for (t in texts) {
            if (t.contains("chaoxing.com", true) || t.contains("SIGNIN", true)) {
                if (shouldHandle(t)) {
                    EngineClient.io { EngineClient.feedQrText(t) }
                }
            }
        }

        // 图片通道：缩略图。字段顺序是有讲究的，BIG_PICTURE 最清晰。
        val bitmaps = listOfNotNull(
            parcelable<Bitmap>(extras, Notification.EXTRA_PICTURE),
            parcelable<Bitmap>(extras, Notification.EXTRA_LARGE_ICON_BIG),
            parcelable<Bitmap>(extras, Notification.EXTRA_LARGE_ICON),
            parcelable<Bitmap>(extras, Notification.EXTRA_SMALL_ICON)
        )
        for (bmp in bitmaps) {
            if (bmp.width < 32 || bmp.height < 32) continue
            EngineClient.io {
                val hits = QrDecoder.decodeWithRetry(bmp)
                for (hit in hits) {
                    if (shouldHandle(hit)) EngineClient.feedQrText(hit)
                }
                if (hits.isEmpty()) {
                    // 本地解不出就整张丢给引擎（引擎那边可能装着 zbar）
                    EngineClient.feedQrImage(QrDecoder.toJpeg(bmp))
                }
                Log.d(TAG, "通知图片 ${sbn.packageName}: ${hits.size} 个码")
            }
        }
    }

    @Suppress("DEPRECATION")
    private inline fun <reified T> parcelable(
        extras: android.os.Bundle, key: String
    ): T? = try {
        if (Build.VERSION.SDK_INT >= 33) extras.getParcelable(key, T::class.java)
        else extras.getParcelable(key) as? T
    } catch (_: Throwable) {
        null
    }
}

/**
 * 相册监听：新照片落地就解一次。
 *
 * 很多课上二维码是学委截图发群里、再被存进相册的。这条通道能覆盖那种情况。
 */
class MediaObserver(context: Context) {

    private val appContext = context.applicationContext
    private val thread = HandlerThread("cx-media").apply { start() }
    private val handler = Handler(thread.looper)
    private var lastId = 0L

    private val observer = object : ContentObserver(handler) {
        override fun onChange(selfChange: Boolean, uri: Uri?) {
            super.onChange(selfChange, uri)
            scanLatest()
        }
    }

    fun start() {
        lastId = queryMaxId()
        appContext.contentResolver.registerContentObserver(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI, true, observer
        )
    }

    fun stop() {
        try {
            appContext.contentResolver.unregisterContentObserver(observer)
        } catch (_: Throwable) {
        }
        thread.quitSafely()
    }

    private fun queryMaxId(): Long {
        val proj = arrayOf(MediaStore.Images.Media._ID)
        appContext.contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            proj, null, null,
            "${MediaStore.Images.Media._ID} DESC"
        )?.use { c ->
            if (c.moveToFirst()) return c.getLong(0)
        }
        return 0L
    }

    /** 只处理「上一轮之后新增」的图，避免每次开机把整个相册扫一遍。 */
    private fun scanLatest() {
        val maxId = queryMaxId()
        if (maxId <= lastId) return
        val from = lastId
        lastId = maxId
        EngineClient.io {
            val proj = arrayOf(MediaStore.Images.Media._ID)
            val sel = "${MediaStore.Images.Media._ID} > ?"
            appContext.contentResolver.query(
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                proj, sel, arrayOf(from.toString()),
                "${MediaStore.Images.Media._ID} ASC LIMIT 5"
            )?.use { c ->
                while (c.moveToNext()) {
                    val id = c.getLong(0)
                    val uri = Uri.withAppendedPath(
                        MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id.toString()
                    )
                    val bytes = readBytes(uri) ?: continue
                    val hits = QrDecoder.decode(bytes)
                    for (h in hits) {
                        if (QrNotificationWatcher.shouldHandle(h)) EngineClient.feedQrText(h)
                    }
                }
            }
        }
    }

    private fun readBytes(uri: Uri): ByteArray? = try {
        val input: InputStream = appContext.contentResolver.openInputStream(uri)
            ?: return null
        input.use { stream ->
            val out = ByteArrayOutputStream()
            stream.copyTo(out)
            out.toByteArray()
        }
    } catch (_: Throwable) {
        null
    }
}
