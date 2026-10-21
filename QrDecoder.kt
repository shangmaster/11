package com.cxsign.sentinel

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * 二维码识别。
 *
 * 用 ML Kit 而不是 ZXing：离线、快、对手里那种「投影仪翻拍 + 有反光」的码容忍度更高。
 * 一帧里可能同时有多个码（老师的码 + 教室墙上的二维码），全返回，交给引擎去筛。
 */
object QrDecoder {

    private val scanner: BarcodeScanner by lazy {
        BarcodeScanning.getClient(
            BarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE, Barcode.FORMAT_CODE_128)
                .build()
        )
    }

    /** 同步解码。必须在后台线程调用（ML Kit 自己会切线程，但这里用 latch 等结果）。 */
    fun decode(bitmap: Bitmap): List<String> {
        if (bitmap.width < 24 || bitmap.height < 24) return emptyList()
        val latch = CountDownLatch(1)
        var out: List<String> = emptyList()
        val image = InputImage.fromBitmap(bitmap, 0)
        scanner.process(image)
            .addOnSuccessListener { codes ->
                out = codes.mapNotNull { it.rawValue }.filter { it.isNotBlank() }
            }
            .addOnFailureListener { out = emptyList() }
            .addOnCompleteListener { latch.countDown() }
        latch.await(4, TimeUnit.SECONDS)
        return out
    }

    fun decode(bytes: ByteArray): List<String> {
        val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return emptyList()
        return decode(bmp)
    }

    /**
     * 通知里拿到的图往往只有缩略图大小，码可能糊成一团。
     * 放大 + 灰度再试一轮，成功率提升明显。
     */
    fun decodeWithRetry(bitmap: Bitmap): List<String> {
        val first = decode(bitmap)
        if (first.isNotEmpty()) return first

        val scale = when {
            bitmap.width < 200 -> 4
            bitmap.width < 500 -> 2
            else -> 1
        }
        if (scale > 1) {
            val big = Bitmap.createScaledBitmap(
                bitmap, bitmap.width * scale, bitmap.height * scale, true
            )
            val second = decode(big)
            if (big !== bitmap) big.recycle()
            if (second.isNotEmpty()) return second
        }

        // 反色再试一次（深色背景的码）
        val inv = Bitmap.createBitmap(bitmap.width, bitmap.height, Bitmap.Config.ARGB_8888)
        for (x in 0 until bitmap.width) {
            for (y in 0 until bitmap.height) {
                val p = bitmap.getPixel(x, y)
                inv.setPixel(
                    x, y,
                    android.graphics.Color.rgb(
                        255 - android.graphics.Color.red(p),
                        255 - android.graphics.Color.green(p),
                        255 - android.graphics.Color.blue(p)
                    )
                )
            }
        }
        val third = decode(inv)
        inv.recycle()
        return third
    }

    fun toJpeg(bitmap: Bitmap, quality: Int = 88): ByteArray {
        val bos = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, quality, bos)
        return bos.toByteArray()
    }

    /** 解码 + 直接投给引擎。返回引擎的响应（可能为空）。 */
    fun decodeAndPush(bitmap: Bitmap): List<String> {
        val texts = decodeWithRetry(bitmap)
        for (t in texts) {
            EngineClient.io { EngineClient.feedQrText(t) }
        }
        if (texts.isEmpty()) {
            // 本地解不出来不代表引擎解不出来（引擎那边可能装了 zbar，对模糊图更强）
            val jpeg = toJpeg(bitmap)
            EngineClient.io { EngineClient.feedQrImage(jpeg) }
        }
        return texts
    }
}
