package com.cxsign.sentinel

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONObject
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * 引擎 HTTP 客户端。
 *
 * 为什么不是把 Python 直接塞进来：引擎可能跑在这台手机上（Termux / Chaquopy），
 * 也可能跑在家里那台常开的旧手机或服务器上。App 只认 baseUrl，两种部署同一个 App。
 *
 * 所有调用都是阻塞的，调用方负责放到后台线程（见 [io]）。
 */
object EngineClient {

    private const val PREFS = "cxsign"
    private const val KEY_BASE = "baseUrl"
    private const val KEY_TOKEN = "token"

    /** 本机引擎默认地址；Termux 里跑 `python run.py serve --port 8848` 就是这个。 */
    const val DEFAULT_BASE = "http://127.0.0.1:8848"

    private val pool = Executors.newFixedThreadPool(3)

    @Volatile var baseUrl: String = DEFAULT_BASE
    @Volatile var token: String = ""

    fun init(ctx: Context) {
        val sp = prefs(ctx)
        baseUrl = sp.getString(KEY_BASE, DEFAULT_BASE) ?: DEFAULT_BASE
        token = sp.getString(KEY_TOKEN, "") ?: ""
    }

    fun save(ctx: Context, base: String, tok: String) {
        baseUrl = base.trimEnd('/')
        token = tok
        prefs(ctx).edit().putString(KEY_BASE, baseUrl).putString(KEY_TOKEN, tok).apply()
    }

    private fun prefs(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** 后台线程执行，回调在主线程之外 —— 调用方自己切回 UI。 */
    fun io(block: () -> Unit) {
        pool.execute {
            try {
                block()
            } catch (_: Throwable) {
            }
        }
    }

    // ---------------- 基础请求 ----------------

    private fun open(path: String, method: String): HttpURLConnection {
        val sep = if (path.contains('?')) '&' else '?'
        val url = URL(baseUrl + path + if (token.isNotEmpty()) "$sep" + "token=" + token else "")
        val c = url.openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 6000
        c.readTimeout = 20000
        c.setRequestProperty("Accept", "application/json")
        if (token.isNotEmpty()) c.setRequestProperty("X-Cx-Token", token)
        return c
    }

    fun getJson(path: String): JSONObject = try {
        val c = open(path, "GET")
        val body = c.inputStream.bufferedReader().use { it.readText() }
        c.disconnect()
        JSONObject(body)
    } catch (e: Throwable) {
        JSONObject().put("ok", false).put("error", e.message ?: "network")
    }

    fun postJson(path: String, body: JSONObject): JSONObject = try {
        val c = open(path, "POST")
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        c.outputStream.use { it.write(body.toString().toByteArray()) }
        val text = c.inputStream.bufferedReader().use { it.readText() }
        c.disconnect()
        JSONObject(text)
    } catch (e: Throwable) {
        JSONObject().put("ok", false).put("error", e.message ?: "network")
    }

    /** 把一张图（二维码 / 签到照片）原样丢给引擎，让引擎去解码 / 上传。 */
    fun postImage(path: String, bytes: ByteArray): JSONObject = try {
        val c = open(path, "POST")
        c.doOutput = true
        c.setRequestProperty("Content-Type", "image/jpeg")
        c.setFixedLengthStreamingMode(bytes.size)
        val out: OutputStream = c.outputStream
        out.use { it.write(bytes) }
        val text = c.inputStream.bufferedReader().use { it.readText() }
        c.disconnect()
        JSONObject(text)
    } catch (e: Throwable) {
        JSONObject().put("ok", false).put("error", e.message ?: "network")
    }

    // ---------------- 业务便捷方法 ----------------

    fun status(): JSONObject = getJson("/api/status")

    fun pollNow(): JSONObject = postJson("/api/poll", JSONObject())

    fun setPoint(lat: Double, lon: Double, datum: String = "gcj02"): JSONObject =
        postJson("/api/point", JSONObject().put("lat", lat).put("lon", lon).put("datum", datum))

    /** 投递二维码：文本（剪贴板/分享）或图片（通知/相册/相机）。 */
    fun feedQrText(text: String): JSONObject =
        postJson("/api/qr", JSONObject().put("text", text).put("source", "android"))

    fun feedQrImage(bytes: ByteArray): JSONObject = postImage("/api/qr", bytes)

    fun feedPhoto(bytes: ByteArray): JSONObject = postImage("/api/photo", bytes)
}
