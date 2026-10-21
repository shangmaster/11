package com.cxsign.sentinel

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * 开机（或 App 更新）自动把监听服务拉起来。
 *
 * 用户的期待是「装完就不用管了」，所以默认开机自启。
 * 想关的话在系统设置里禁用这个 App 的自启动权限即可，代码不做开关。
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context?, intent: Intent?) {
        if (context == null) return
        when (intent?.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED -> {
                EngineClient.init(context)
                SentinelService.start(context)
            }
        }
    }
}
