package com.cxsign.sentinel

import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import org.json.JSONObject
import java.io.ByteArrayOutputStream

/**
 * 主界面：一个状态卡片 + 一排按钮。刻意不做花哨 UI —— 这 App 一天只用两次。
 *
 * 所有协议逻辑都在引擎里（Python），这里只做四件事：
 *   看状态 / 扫码 / 传图 / 地图选点
 */
class MainActivity : AppCompatActivity() {

    private lateinit var statusBox: TextView
    private lateinit var logBox: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        EngineClient.init(this)
        setContentView(buildUi())
        requestPerms()
        refresh()
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    // ---------------- UI ----------------

    private fun buildUi(): ViewGroup {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(18), dp(16), dp(16))
            setBackgroundColor(Color.parseColor("#0d1117"))
        }

        root.addView(TextView(this).apply {
            text = "签到哨兵"
            textSize = 21f
            setTextColor(Color.parseColor("#e6edf3"))
        })
        root.addView(TextView(this).apply {
            text = "引擎在后台跑，这里只是遥控器"
            textSize = 12.5f
            setTextColor(Color.parseColor("#8b949e"))
            setPadding(0, dp(2), 0, dp(14))
        })

        statusBox = TextView(this).apply {
            textSize = 13.5f
            setTextColor(Color.parseColor("#c9d1d9"))
            setBackgroundColor(Color.parseColor("#161b22"))
            setPadding(dp(14), dp(14), dp(14), dp(14))
            text = "连接中…"
        }
        root.addView(statusBox, lpMatch().apply { bottomMargin = dp(14) })

        root.addView(row(
            btn("地图选点") { openMap() },
            btn("扫二维码") { scan() }
        ))
        root.addView(row(
            btn("自动扫码") {
                AutoScanService.start(this)
                toastLike("摄像头已启动 —— 架着手机对着屏幕就行，不用人管")
                refresh()
            },
            btn("停止扫码") { AutoScanService.stop(this); toastLike("自动扫码已停"); refresh() }
        ))
        root.addView(row(
            btn("传签到照片") { pickPhoto() },
            btn("立刻轮询") { pollNow() }
        ))
        root.addView(row(
            btn("启动监听") { SentinelService.start(this); toastLike("已启动"); refresh() },
            btn("停止监听") { SentinelService.stop(this); toastLike("已停止"); refresh() }
        ))
        root.addView(row(
            btn("设置") { showSettings() },
            btn("签到记录") { showRecords() }
        ))

        logBox = TextView(this).apply {
            textSize = 12f
            setTextColor(Color.parseColor("#7d8590"))
            setPadding(0, dp(14), 0, 0)
            text = ""
        }
        val scroll = ScrollView(this).apply { addView(logBox) }
        root.addView(scroll, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
        ))
        return root
    }

    private fun row(vararg views: Button): LinearLayout =
        LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 0, 0, dp(8))
            views.forEach { v ->
                addView(v, LinearLayout.LayoutParams(0, dp(46), 1f).apply {
                    marginEnd = dp(8)
                })
            }
        }

    private fun btn(text: String, onClick: () -> Unit): Button = Button(this).apply {
        this.text = text
        textSize = 13.5f
        isAllCaps = false
        setOnClickListener { onClick() }
    }

    private fun lpMatch() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
    )

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    // ---------------- 动作 ----------------

    private fun refresh() {
        EngineClient.io {
            val st = EngineClient.status()
            val recs = EngineClient.getJson("/api/records")
            runOnUiThread { renderStatus(st, recs) }
        }
    }

    private fun renderStatus(st: JSONObject, recs: JSONObject) {
        if (!st.optBoolean("ok", false)) {
            statusBox.text = "⚠️ 引擎未连接\n" +
                    "地址：${EngineClient.baseUrl}\n" +
                    "· 本机跑：Termux 里执行 python run.py serve\n" +
                    "· 远程跑：在设置里改成服务器地址\n" +
                    (st.optString("error").takeIf { it.isNotBlank() }?.let { "错误：$it" } ?: "")
            logBox.text = ""
            return
        }
        val d = st.optJSONObject("data") ?: JSONObject()
        val login = d.optJSONObject("login")
        val stats = d.optJSONObject("stats")
        val pending = d.optJSONArray("pending")
        val point = d.optJSONArray("point")

        val sb = StringBuilder()
        sb.append("👤 ${login?.optString("uname").orEmpty().ifBlank { "已登录" }}")
        sb.append("  (uid ${login?.optString("uid").orEmpty()})\n")
        sb.append("📚 课程 ${d.optInt("courses")} 个   ✅ 已签 ${d.optInt("signed")} 次\n")
        sb.append("🔄 已轮询 ${stats?.optInt("polls") ?: 0} 轮   ")
        sb.append("发现 ${stats?.optInt("found") ?: 0} 个活动\n")
        if (pending != null && pending.length() > 0) {
            sb.append("⏳ ${pending.length()} 个签到在等二维码 —— 扫一下老师的码\n")
        }
        if (point != null && point.length() == 2) {
            sb.append("📍 ${"%.6f".format(point.optDouble(0))}, ${"%.6f".format(point.optDouble(1))}\n")
        }
        val photo = d.optString("photo")
        if (photo.isNotBlank()) sb.append("🖼 照片 ${photo.substringAfterLast('/')}\n")
        statusBox.text = sb.toString().trimEnd()

        val signedObj = recs.optJSONObject("signed")
        if (signedObj != null && signedObj.length() > 0) {
            val lines = signedObj.keys().asSequence().mapNotNull { k ->
                signedObj.optJSONObject(k)?.let {
                    val name = it.optString("name")
                    val msg = it.optString("message")
                    val kind = it.optString("kind")
                    "✅ $name [$kind] $msg"
                }
            }.take(20).toList()
            logBox.text = lines.joinToString("\n")
        }
    }

    private fun openMap() {
        startActivity(Intent(this, MapActivity::class.java))
    }

    private fun scan() {
        val client = GmsBarcodeScanning.getClient(this)
        client.startScan()
            .addOnSuccessListener { barcode ->
                val raw = barcode.rawValue ?: return@addOnSuccessListener
                EngineClient.io {
                    val r = EngineClient.feedQrText(raw)
                    runOnUiThread {
                        toastLike(if (r.optBoolean("ok")) "已投递二维码" else "投递失败")
                        refresh()
                    }
                }
            }
            .addOnFailureListener { e -> toastLike("扫码失败：${e.message}") }
    }

    private fun pickPhoto() {
        val intent = Intent(Intent.ACTION_GET_CONTENT).apply { type = "image/*" }
        startActivityForResult(intent, REQ_PHOTO)
    }

    @Deprecated("startActivityForResult 就够，不想为一张图引 activity-ktx")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_PHOTO || resultCode != RESULT_OK) return
        val uri: Uri = data?.data ?: return
        EngineClient.io {
            val bytes = readAll(uri) ?: return@io
            val r = EngineClient.feedPhoto(bytes)
            runOnUiThread {
                toastLike(if (r.optBoolean("ok")) "照片已设为签到图" else "上传失败")
                refresh()
            }
        }
    }

    private fun readAll(uri: Uri): ByteArray? = try {
        contentResolver.openInputStream(uri)?.use { input ->
            val out = ByteArrayOutputStream()
            input.copyTo(out)
            out.toByteArray()
        }
    } catch (_: Throwable) {
        null
    }

    private fun pollNow() {
        EngineClient.io {
            val r = EngineClient.pollNow()
            runOnUiThread {
                val n = r.optJSONArray("results")?.length() ?: 0
                toastLike("轮询完成，处理 $n 个")
                refresh()
            }
        }
    }

    private fun showSettings() {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(8), dp(20), 0)
        }
        val base = EditText(this).apply {
            hint = "引擎地址，例如 http://192.168.1.9:8848"
            setText(EngineClient.baseUrl)
            inputType = InputType.TYPE_TEXT_VARIATION_URI
        }
        val tok = EditText(this).apply {
            hint = "访问令牌（没设就留空）"
            setText(EngineClient.token)
        }
        box.addView(base)
        box.addView(tok)

        AlertDialog.Builder(this)
            .setTitle("连接设置")
            .setView(box)
            .setPositiveButton("保存") { _, _ ->
                EngineClient.save(this, base.text.toString(), tok.text.toString())
                refresh()
            }
            .setNeutralButton("导入 cookie") { _, _ -> importCookie() }
            .setNegativeButton("取消", null)
            .show()
    }

    /** 手机上最省事的登录方式：把浏览器里那段 cookie 粘进来。 */
    private fun importCookie() {
        val input = EditText(this).apply {
            hint = "_uid=...; fid=...; _d=...; uf=..."
            minLines = 3
            gravity = Gravity.TOP
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
        }
        AlertDialog.Builder(this)
            .setTitle("粘贴 cookie")
            .setMessage("浏览器登录 i.chaoxing.com → F12 → Network → 任意请求 → 复制 Cookie 整行")
            .setView(input)
            .setPositiveButton("导入") { _, _ ->
                EngineClient.io {
                    val r = EngineClient.postJson(
                        "/api/login", JSONObject().put("cookie", input.text.toString())
                    )
                    runOnUiThread {
                        toastLike(
                            if (r.optBoolean("ok")) "登录有效：${r.optString("message")}"
                            else "失败：${r.optString("message").ifBlank { r.optString("error") }}"
                        )
                        refresh()
                    }
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun showRecords() {
        EngineClient.io {
            val recs = EngineClient.getJson("/api/records")
            val signed = recs.optJSONObject("signed")
            val sb = StringBuilder()
            signed?.keys()?.forEach { k ->
                val o = signed.optJSONObject(k) ?: return@forEach
                sb.append("${o.optString("name")}  [${o.optString("kind")}]\n")
                sb.append("  ${o.optString("message")}\n")
                sb.append("  activeId $k\n\n")
            }
            runOnUiThread {
                AlertDialog.Builder(this)
                    .setTitle("签到记录")
                    .setMessage(sb.toString().ifBlank { "还没有记录" })
                    .setPositiveButton("好", null)
                    .show()
            }
        }
    }

    private fun toastLike(msg: String) {
        logBox.text = msg
    }

    private fun requestPerms() {
        val need = mutableListOf<String>()
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            need += "android.permission.POST_NOTIFICATIONS"
            need += "android.permission.READ_MEDIA_IMAGES"
        } else {
            need += "android.permission.READ_EXTERNAL_STORAGE"
        }
        val missing = need.filter {
            checkSelfPermission(it) != android.content.pm.PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)
    }

    companion object {
        private const val REQ_PHOTO = 1001
    }
}
