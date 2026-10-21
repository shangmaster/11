# 拍照签到 · 图片注入模块（LSPosed）

这是一个 **Xposed / LSPosed 模块**，专门解决一件事：

> 拍照签到时，用你相册里的图，而不是现场拍的。

它不改学习通的安装包、不伪造任何请求。它只做一件事：**在官方 App 打开相机的那一刻，替它"拍"一张你指定的图**。之后压缩、生成 `photoResult`、上传、提交，全部由官方 App 自己完成 —— 所以服务端认，`photoAuthError_PCR007` 不会出现。

---

## 为什么必须是这条路

拍照签到的服务端要 `photoResult`。它由官方 App 的原生桥在**真的调起相机之后**现场生成，带时间戳和来源信息。

- 网页端 / 自己写的 App → 造不出来，回 `photoAuthError_PCR007`
- 纯 HTTP 引擎 → 同上
- 换多少个界面都一样，因为卡在协议层

所以只有两种可能：
1. 这串东西其实是客户端拼的 → 我们自己算（先跑 `python run.py probe-photo` 判断）
2. 它是服务端签发 / 带签名 → 必须让官方 App 现场生成

**这个模块解决第 2 种。**

---

## 门槛

需要 **root + LSPosed**（或 EdXposed、KernelSU + Zygisk + LSPosed）。

免 root 的 VirtualXposed / 太极·阴 理论可行，但学习通对运行环境有检测，成功率不稳定，不推荐。

没有 root 的安卓、或者 iPhone，这条路走不通 —— 见文末。

---

## 装法

### 1. 编译

```bash
cd android-hook
./gradlew assembleDebug
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

没有 Android Studio 的话，把这个目录推到 GitHub，用 `.github/workflows/build-hook.yml` 自动构建。

### 2. 装模块

1. 装 APK（会显示成一个紫色相机图标，名叫「签到哨兵·图片注入」）
2. 打开 **LSPosed** → 模块 → 找到「签到哨兵·图片注入」→ **启用**
3. 点进去 → **作用域** → 只勾 **学习通**（`com.chaoxing.mobile`）
4. 强行停止学习通，再打开

### 3. 配图

1. 打开模块 App（紫色图标）
2. 点 **从相册选图** → 选一张（建议横构图、看得出是教室/宿舍/白纸都行）
3. 状态变成绿色的「当前：1600×1200 · 180 KB」就是存好了
4. 开关默认已经是「已开启」

### 4. 验证

打开学习通 → 找一个拍照签到 → 点拍照。

**相机不会打开**，直接返回，交上去的是你选的那张图。

如果相机还是打开了，说明 hook 没生效：
- LSPosed 里作用域勾了吗？
- 学习通强行停止过吗？
- LSPosed 日志里搜 `CxSignHook`，看有没有「已注入 com.chaoxing.mobile」

---

## 它是怎么工作的

两个 hook 点，第一个管用就够，第二个兜底：

```
Hook 1  Activity.startActivityForResult
        看到 Intent 的 action 是 IMAGE_CAPTURE
        -> 不启动相机
        -> 延迟 250ms 手动调 onActivityResult(RESULT_OK, 我们的图)
        -> 官方 App 以为用户拍完了，继续走自己的流程

Hook 2  Activity.onActivityResult   （兜底，应对自研相机的版本）
        拿到结果后，如果 extras["data"] 里有 Bitmap，换成我们的
        如果 EXTRA_OUTPUT 指向的文件太小，直接覆写
```

关键点：**我们只替换"相机返回了什么"，不碰它生成凭证的逻辑**。所以整条链路在服务端看来和真拍一次没有区别。

图片用 base64 存在模块的 SharedPreferences 里（压到 1600px / q85，约 150~250KB），hook 用 `XSharedPreferences` 跨进程读。

---

## 代码

```
android-hook/
└── app/src/main/
    ├── assets/xposed_init                    # 入口类名，Xposed 靠它加载
    ├── java/com/cxsign/hook/
    │   ├── HookEntry.kt                      # 核心：两个 hook 点
    │   └── MainActivity.kt                   # 选图 / 开关 / 预览
    └── AndroidManifest.xml                   # xposedmodule / xposedscope
```

`HookEntry.kt` 里每个 hook 都包在 try-catch 里，装不上只会打日志，不会让学习通崩。

---

## 已知限制

| 情况 | 结果 |
| --- | --- |
| 学习通某版本用自研相机（不走系统 Intent） | Hook 1 拦不到，靠 Hook 2 兜底；两个都失效就只能等适配 |
| 老师同时要求「人脸活体」 | 这个模块不管人脸，那是另一条链路 |
| 学习通检测 Xposed 环境 | 部分版本会。真遇到就换 KernelSU + Zygisk 隐藏 |
| 论文/考试监控模式 | 别在这类场景用，风险不一样 |

---

## 没有 root 怎么办

**安卓**：先跑 `python run.py probe-photo --text "<抓到的 photoResult>"`。
如果分析结果说「大概率是客户端拼装」，那就不用 hook —— 引擎直接生成，网页端也能签。

**iPhone**：不越狱做不到。iOS 的相机、相册、通知都是隔离的，第三方无法介入官方 App 的拍照流程。
唯一的替代是越狱后装 Frida，用类似思路 hook —— 门槛比安卓高得多，而且新系统越狱越来越难。

---

## 别做的事

- 别把这个模块的作用域勾到别的 App 上
- 别用它去做人脸签到（那需要真的活体）
- 别在同一次课里用同一张图签十几次（服务端存图，老师看得见）
