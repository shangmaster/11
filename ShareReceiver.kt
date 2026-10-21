package com.cxsign.sentinel

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import java.io.ByteArrayOutputStream

/**
 * 「分享到签到哨兵」接收器。
 *
 * 为什么留着这条半自动通道：微信/QQ 的图片消息通知里通常没有缩略图，
 * 通知监听抓不到。这时候长按图片 -> 分享 -> 签到哨兵，一步到位。
 *
 * 收三种：
 *   · image/*        -> 解码后投给引擎（引擎也能自己解）
 *   · text/plain     -> 里面可能就藏着签到链接
 *   · 多图           -> 逐张处理
 */
class ShareReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context?, intent: Intent?) {
        if (context == null || intent == null) return
        EngineClient.init(context)

        when (intent.action) {
            Intent.ACTION_SEND -> {
                val type = intent.type.orEmpty()
                if (type.startsWith("image/")) {
                    uriOf(intent)?.let { pushImage(context, it) }
                } else {
                    intent.getStringExtra(Intent.EXTRA_TEXT)?.let { pushText(it) }
                }
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                @Suppress("DEPRECATION")
                val list = intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
                list?.forEach { pushImage(context, it) }
                intent.getStringExtra(Intent.EXTRA_TEXT)?.let { pushText(it) }
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun uriOf(intent: Intent): Uri? =
        if (android.os.Build.VERSION.SDK_INT >= 33)
            intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else
            intent.getParcelableExtra(Intent.EXTRA_STREAM)

    private fun pushText(text: String) {
        if (text.isBlank()) return
        EngineClient.io { EngineClient.feedQrText(text) }
    }

    private fun pushImage(context: Context, uri: Uri) {
        EngineClient.io {
            val bytes = read(context, uri) ?: return@io
            EngineClient.feedQrImage(bytes)
        }
    }

    private fun read(context: Context, uri: Uri): ByteArray? = try {
        context.contentResolver.openInputStream(uri)?.use { input ->
            val out = ByteArrayOutputStream()
            input.copyTo(out)
            out.toByteArray()
        }
    } catch (_: Throwable) {
        null
    }
}
