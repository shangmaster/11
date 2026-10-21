package com.cxsign.hook

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import java.io.ByteArrayOutputStream

/**
 * 模块自己的界面：选一张图，开个开关。
 *
 * 图片用 base64 存进 SharedPreferences —— 因为 hook 跑在学习通的进程里，
 * 跨进程只能靠 XSharedPreferences 读字符串。压到 1600px / q85，
 * 大概 150~250KB，base64 后也不会让 prefs 太难看。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var preview: ImageView
    private lateinit var stateText: TextView
    private lateinit var toggle: Button

    private val prefs by lazy { getSharedPreferences(HookEntry.PREFS, MODE_PRIVATE) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildUi())
        render()
    }

    private fun buildUi(): ViewGroup {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(24), dp(20), dp(20))
            setBackgroundColor(Color.parseColor("#0d1117"))
        }

        root.addView(TextView(this).apply {
            text = "拍照签到 · 图片注入"
            textSize = 21f
            setTextColor(Color.parseColor("#e6edf3"))
        })
        root.addView(TextView(this).apply {
            text = "让学习通 App 的拍照签到时用你相册里的图。\n" +
                    "凭证仍由官方 App 生成，所以服务端认。"
            textSize = 12.5f
            setTextColor(Color.parseColor("#8b949e"))
            setPadding(0, dp(6), 0, dp(18))
        })

        preview = ImageView(this).apply {
            setBackgroundColor(Color.parseColor("#161b22"))
            scaleType = ImageView.ScaleType.CENTER_INSIDE
            adjustViewBounds = true
        }
        root.addView(preview, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(260)
        ).apply { bottomMargin = dp(14) })

        stateText = TextView(this).apply {
            textSize = 13f
            setTextColor(Color.parseColor("#c9d1d9"))
            setPadding(0, 0, 0, dp(14))
        }
        root.addView(stateText)

        root.addView(button("从相册选图") { pick() })
        toggle = button("") { toggleEnabled() }
        root.addView(toggle)

        root.addView(TextView(this).apply {
            text = "用法：装好后在 LSPosed 里启用本模块，作用域勾选「学习通」，" +
                    "然后强行停止学习通再打开。\n\n" +
                    "拍照签到时它会自动用这张图，相机不会真的打开。"
            textSize = 11.5f
            setTextColor(Color.parseColor("#6e7681"))
            setPadding(0, dp(18), 0, 0)
        })
        return root
    }

    private fun button(text: String, onClick: () -> Unit): Button =
        Button(this).apply {
            this.text = text
            isAllCaps = false
            textSize = 15f
            gravity = Gravity.CENTER
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48)
            ).apply { bottomMargin = dp(10) }
        }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    // ------------------------------------------------------------------

    private fun render() {
        val enabled = prefs.getBoolean(HookEntry.KEY_ENABLED, false)
        val b64 = prefs.getString(HookEntry.KEY_IMAGE, null)

        toggle.text = if (enabled) "已开启 · 点此关闭" else "已关闭 · 点此开启"

        if (b64.isNullOrBlank()) {
            preview.setImageDrawable(null)
            stateText.text = "还没有图。先选一张（建议横构图、看得出是教室/宿舍）"
            stateText.setTextColor(Color.parseColor("#d29922"))
            return
        }
        val bmp = runCatching {
            val bytes = Base64.decode(b64, Base64.NO_WRAP)
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        }.getOrNull()

        if (bmp == null) {
            stateText.text = "存的图读不出来了，重新选一张"
            stateText.setTextColor(Color.parseColor("#f85149"))
            return
        }
        preview.setImageBitmap(bmp)
        stateText.text = "当前：${bmp.width}×${bmp.height} · ${b64.length / 1024} KB(base64)"
        stateText.setTextColor(Color.parseColor("#3fb950"))
    }

    private fun toggleEnabled() {
        val next = !prefs.getBoolean(HookEntry.KEY_ENABLED, false)
        prefs.edit().putBoolean(HookEntry.KEY_ENABLED, next).apply()
        if (next && prefs.getString(HookEntry.KEY_IMAGE, null).isNullOrBlank()) {
            stateText.text = "开了但还没有图 —— 先选一张"
            stateText.setTextColor(Color.parseColor("#d29922"))
            prefs.edit().putBoolean(HookEntry.KEY_ENABLED, false).apply()
        }
        render()
    }

    private fun pick() {
        val i = Intent(Intent.ACTION_GET_CONTENT).apply { type = "image/*" }
        startActivityForResult(i, REQ_PICK)
    }

    @Deprecated("一张图不值得引 activity-ktx")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_PICK || resultCode != Activity.RESULT_OK) return
        val uri = data?.data ?: return
        val bmp = readScaled(uri) ?: run {
            stateText.text = "读不出这张图"
            stateText.setTextColor(Color.parseColor("#f85149"))
            return
        }
        val bos = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 85, bos)
        val b64 = Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP)
        prefs.edit()
            .putString(HookEntry.KEY_IMAGE, b64)
            .putBoolean(HookEntry.KEY_ENABLED, true)
            .apply()
        render()
    }

    /** 长边压到 1600，控制 prefs 体积；太小的图不放大。 */
    private fun readScaled(uri: Uri): Bitmap? = try {
        val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
        val long = maxOf(opts.outWidth, opts.outHeight)
        var sample = 1
        while (long / sample > 1600) sample *= 2
        val real = BitmapFactory.Options().apply { inSampleSize = sample }
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, real) }
    } catch (t: Throwable) {
        null
    }

    companion object {
        private const val REQ_PICK = 2001
    }
}
