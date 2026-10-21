package com.cxsign.hook

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.util.Log
import de.robv.android.xposed.IXposedHookLoadPackage
import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XSharedPreferences
import de.robv.android.xposed.XposedBridge
import de.robv.android.xposed.XposedHelpers
import de.robv.android.xposed.callbacks.XC_LoadPackage
import java.io.File
import java.io.FileOutputStream

/**
 * LSPosed / Xposed 模块：让学习通的「拍照签到」用你相册里的图。
 *
 * 为什么必须走这条路：
 *   拍照签到的服务端要一个 `photoResult`，由官方 App 的原生桥在**真的调起相机之后**
 *   现场生成。纯 HTTP 客户端造不出来（回 photoAuthError_PCR007），
 *   所以在网页 / 自己写的 App 里怎么做都过不去。
 *
 *   这个模块不改学习通、不伪造请求。它只做一件事：
 *   在官方 App 打开相机的那一刻，**替它"拍"一张你指定的图**。
 *   后面生成 photoResult、压缩、上传、提交，全部由官方 App 自己完成 ——
 *   所以凭证是真的，服务端认。
 *
 * 使用门槛：需要 root + LSPosed（或 EdXposed）。免 root 的 VirtualXposed /
 * 太极·阴 理论可行，但学习通对运行环境有检测，成功率不稳定。
 */
class HookEntry : IXposedHookLoadPackage {

    companion object {
        const val TAG = "CxSignHook"
        const val TARGET = "com.chaoxing.mobile"

        /** 模块自己的包名 / SharedPreferences 名，和 MainActivity 保持一致 */
        const val MODULE_PKG = "com.cxsign.hook"
        const val PREFS = "cxsign_hook"
        const val KEY_ENABLED = "enabled"
        const val KEY_IMAGE = "image_b64"
    }

    override fun handleLoadPackage(lpparam: XC_LoadPackage.LoadPackageParam) {
        if (lpparam.packageName != TARGET) return
        XposedBridge.log("[$TAG] 已注入 ${lpparam.packageName}")
        try {
            install(lpparam)
            XposedBridge.log("[$TAG] hook 安装完成")
        } catch (t: Throwable) {
            XposedBridge.log("[$TAG] 安装失败: $t")
        }
    }

    private fun install(lpparam: XC_LoadPackage.LoadPackageParam) {
        val prefs = XSharedPreferences(MODULE_PKG, PREFS)
        prefs.reload()

        // ---------------------------------------------------------------
        // Hook 1：拦截系统相机 Intent
        //
        // 学习通拍照走的是 Intent(MediaStore.ACTION_IMAGE_CAPTURE) + startActivityForResult。
        // 在这里把它拦下来：不启动相机，延迟 250ms 后直接回调 onActivityResult，
        // 结果里塞我们自己的图。官方 App 以为用户拍完了，继续走它自己的流程。
        //
        // 这是最干净的一个点：不碰它的业务代码，只替换「相机返回了什么」。
        // ---------------------------------------------------------------
        try {
            XposedHelpers.findAndHookMethod(
                Activity::class.java, "startActivityForResult",
                Intent::class.java, Int::class.javaPrimitiveType,
                object : XC_MethodHook() {
                    override fun beforeHookedMethod(param: MethodHookParam) {
                        val intent = param.args[0] as? Intent ?: return
                        if (!isCaptureIntent(intent)) return
                        val activity = param.thisObject as? Activity ?: return

                        prefs.reload()
                        if (!prefs.getBoolean(KEY_ENABLED, false)) return
                        val bmp = loadBitmap(prefs) ?: run {
                            XposedBridge.log("[$TAG] 没配图，交给真相机")
                            return
                        }

                        val req = (param.args[1] as? Int) ?: return
                        param.result = null          // 不真的启动相机
                        XposedBridge.log("[$TAG] 拦截相机请求 req=$req，注入本地图")

                        Handler(Looper.getMainLooper()).postDelayed({
                            deliver(activity, intent, req, bmp)
                        }, 250)
                    }
                }
            )
            XposedBridge.log("[$TAG] Hook1 startActivityForResult OK")
        } catch (t: Throwable) {
            XposedBridge.log("[$TAG] Hook1 失败: $t")
        }

        // ---------------------------------------------------------------
        // Hook 2：兜底 —— 万一某个版本用了自研相机（不走系统 Intent），
        // 在 onActivityResult 拿到结果之后再替换一次。
        //
        // 这里只在 data 里确实有 bitmap 时才动手，避免影响别的 requestCode。
        // ---------------------------------------------------------------
        try {
            XposedHelpers.findAndHookMethod(
                Activity::class.java, "onActivityResult",
                Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, Intent::class.java,
                object : XC_MethodHook() {
                    override fun beforeHookedMethod(param: MethodHookParam) {
                        val resCode = (param.args[1] as? Int) ?: return
                        if (resCode != Activity.RESULT_OK) return
                        val data = param.args[2] as? Intent ?: return
                        val activity = param.thisObject as? Activity ?: return

                        prefs.reload()
                        if (!prefs.getBoolean(KEY_ENABLED, false)) return
                        val bmp = loadBitmap(prefs) ?: return

                        @Suppress("DEPRECATION")
                        val old = data.extras?.get("data") as? Bitmap
                        if (old != null) {
                            // 缩略图路径：直接换掉
                            data.putExtra("data", bmp)
                            param.args[2] = data
                            XposedBridge.log("[$TAG] Hook2 替换缩略图 ${old.width}x${old.height} -> ${bmp.width}x${bmp.height}")
                        }
                        // 文件路径（EXTRA_OUTPUT）：如果 App 写的文件太小，覆写它
                        overwriteOutputIfSmall(activity, data, bmp)
                    }
                }
            )
            XposedBridge.log("[$TAG] Hook2 onActivityResult OK")
        } catch (t: Throwable) {
            XposedBridge.log("[$TAG] Hook2 失败: $t")
        }
    }

    // ------------------------------------------------------------------

    private fun isCaptureIntent(intent: Intent): Boolean {
        val action = intent.action ?: return false
        if (action == "android.media.action.IMAGE_CAPTURE") return true
        if (action == "android.media.action.IMAGE_CAPTURE_SECURE") return true
        // 有些版本用 chooser 包一层
        @Suppress("DEPRECATION")
        val inner = intent.getParcelableExtra<Intent>("android.intent.extra.INTENT")
        if (inner != null) return isCaptureIntent(inner)
        return false
    }

    /** 按相机 Intent 的两种形态回填结果。 */
    private fun deliver(activity: Activity, intent: Intent, req: Int, bmp: Bitmap) {
        try {
            val output: Uri? = intent.getParcelableExtra("output")
            if (output != null) {
                // 相机被要求把图写到这个 Uri —— 我们直接写文件
                activity.contentResolver.openOutputStream(output)?.use { out ->
                    bmp.compress(Bitmap.CompressFormat.JPEG, 92, out)
                }
                XposedHelpers.callMethod(
                    activity, "onActivityResult", req, Activity.RESULT_OK, null
                )
                XposedBridge.log("[$TAG] 已写入 $output 并回调")
            } else {
                // 没有 output：按约定把 bitmap 放在 extras["data"]
                val data = Intent().putExtra("data", bmp)
                XposedHelpers.callMethod(
                    activity, "onActivityResult", req, Activity.RESULT_OK, data
                )
                XposedBridge.log("[$TAG] 已用 extras[data] 回调")
            }
        } catch (t: Throwable) {
            XposedBridge.log("[$TAG] 回调失败: $t")
        }
    }

    /** 某些实现会先写一个小图到文件，再用它当照片 —— 尺寸明显偏小就覆盖。 */
    private fun overwriteOutputIfSmall(ctx: Context, data: Intent, bmp: Bitmap) {
        try {
            val output: Uri = data.getParcelableExtra("output") ?: return
            val path = output.path ?: return
            val f = File(path)
            if (!f.exists()) return
            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(path, opts)
            if (opts.outWidth in 1..600) {
                FileOutputStream(f).use { bmp.compress(Bitmap.CompressFormat.JPEG, 92, it) }
                XposedBridge.log("[$TAG] 覆盖小图 ${opts.outWidth}x${opts.outHeight}")
            }
        } catch (t: Throwable) {
            Log.w(TAG, "overwriteOutputIfSmall: $t")
        }
    }

    /** 从 prefs 里取 base64 图片。图压到 ~150KB，跨进程传不成问题。 */
    private fun loadBitmap(prefs: XSharedPreferences): Bitmap? = try {
        val b64 = prefs.getString(KEY_IMAGE, null)
        if (b64.isNullOrBlank()) null
        else {
            val bytes = Base64.decode(b64, Base64.NO_WRAP)
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        }
    } catch (t: Throwable) {
        XposedBridge.log("[$TAG] 读图失败: $t")
        null
    }
}
