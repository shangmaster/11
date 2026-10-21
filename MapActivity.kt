package com.cxsign.sentinel

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.GeolocationPermissions
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

/**
 * 地图选点页。
 *
 * 不重写一套地图：直接加载引擎自带的 web/map.html（高德瓦片，零 key、零依赖）。
 * 页面里点一下「设为签到点」就直接写到引擎的运行时状态里，返回就能用。
 *
 * 好处是一个地图实现，Android、iOS、桌面浏览器三端共用，改一处全生效。
 */
class MapActivity : AppCompatActivity() {

    private var web: WebView? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        EngineClient.init(this)

        val wv = WebView(this)
        web = wv
        wv.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            setGeolocationEnabled(true)
            useWideViewPort = true
            loadWithOverviewMode = true
            builtInZoomControls = false
        }
        wv.webViewClient = WebViewClient()
        wv.webChromeClient = object : WebChromeClient() {
            // 「用当前定位」按钮需要网页拿到定位权限
            override fun onGeolocationPermissionsShowPrompt(
                origin: String?,
                callback: GeolocationPermissions.Callback?
            ) {
                callback?.invoke(origin, true, false)
            }
        }

        val url = buildString {
            append(EngineClient.baseUrl.trimEnd('/'))
            append("/map")
            if (EngineClient.token.isNotEmpty()) {
                append("?token=")
                append(EngineClient.token)
            }
        }
        wv.loadUrl(url)
        setContentView(wv)
    }

    override fun onDestroy() {
        web?.let {
            it.loadUrl("about:blank")
            it.destroy()
        }
        web = null
        super.onDestroy()
    }

    @Deprecated("老 API 就够用，physical back 直接结束这个 Activity")
    override fun onBackPressed() {
        finish()
    }
}
