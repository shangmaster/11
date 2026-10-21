# Android 壳 · 签到哨兵

这个目录是**遥控器 + 取码器**，不是签到逻辑本身。签到逻辑在 `../core`（Python）。

## 两种部署，选一个

| 形态 | 引擎在哪 | 适合谁 | 代价 |
| --- | --- | --- | --- |
| **A. 本机一体** | 同一个手机的 Termux 里 | 只有一台手机、想少折腾 | 要装 Termux；App 切后台时靠前台服务保活 |
| **B. 远程引擎**（推荐） | 家里常开的旧手机/树莓派/NAS/小服务器 | 主力机不想装一堆东西 | 多一台常开的设备（一台淘汰的安卓就够） |

两种形态装的是**同一个 APK**，只是「设置」里的地址不同：

- A：`http://127.0.0.1:8848`
- B：`http://192.168.x.x:8848`（同一局域网）或 `https://你的域名`（有公网就套一层 HTTPS）

## A 形态：Termux 里跑引擎

```bash
# 1) 装 Termux（F-Droid 版，别用 Play 商店那个停更的）
pkg update && pkg install python zbar libjpeg-turbo
pip install pyzbar pillow

# 2) 把 core/ 整个目录拷进手机（U 盘 / adb push / git clone 都行）
cd ~/cxsign-sentinel/core

# 3) 导入 cookie（见主 README「登录」一节）
python run.py login --cookie "_uid=...; fid=...; _d=...; uf=..."

# 4) 起引擎 + 本地 API
python run.py all --port 8848

# 5) 可选：让 Termux 在后台不被杀
termux-wake-lock
```

Termux 要关掉电池优化：
`设置 → 应用 → Termux → 电池 → 不受限制`

## B 形态：远程引擎

引擎那台设备上：

```bash
python run.py all --host 0.0.0.0 --port 8848 --token 你自己编一串
```

> 对外必须带 `--token`。引擎没有任何鉴权以外的防线，端口暴露出去等于把签到权交出去。

App 里「设置」→ 地址填 `http://那台设备的IP:8848`，令牌填同一串。

---

## 权限：三个必须手动开

装完 App 后，去系统设置里把这几个给上，否则「自动」这两个字不成立：

| 权限 | 路径 | 不给了会怎样 |
| --- | --- | --- |
| **通知使用权** | 设置 → 通知与状态栏 → 通知使用权 → 签到哨兵 | 抓不到 QQ/微信/学习通通知里的二维码图（通道 1 失效） |
| **电池优化白名单** | 设置 → 应用 → 签到哨兵 → 电池 → 不受限制 | 后台服务几分钟就被杀，轮询停摆 |
| **相册读取** | 首次运行会弹，或 设置 → 应用 → 权限 | 相册通道失效（通道 2） |
| 通知权限 | 首次运行会弹 | 前台服务通知不显示，服务也活不长 |

国产 ROM 额外要开：**自启动**（小米/华为/OPPO/vivo 都有独立开关）、**后台弹出界面**、**锁屏显示**。

## 二维码是怎么「自动」抓到的

三条通道并行，任意一条命中就签到：

```
通道 1  通知栏        NotificationListenerService 读 Notification.EXTRA_PICTURE
                     → ML Kit 解码 → POST /api/qr
                     覆盖：学习通推送、群里转发的二维码图

通道 2  相册          ContentObserver 监听 MediaStore 新增图片
                     → 解码 → POST /api/qr
                     覆盖：学委截图存相册的码

通道 3  分享          ACTION_SEND 收图/收文本 → POST /api/qr
                     覆盖：微信里长按图片 → 分享 → 签到哨兵（半自动，但最准）
```

三条都解不出来时，会把**整张图**丢给引擎（引擎那边装着 zbar，对模糊/反光的码更强）。

## 构建

```bash
cd android
# 用 Android Studio 打开这个目录，或者：
./gradlew assembleDebug
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

要求：Android Studio Ladybug+ / JDK 17 / compileSdk 34。
`minSdk 24`（Android 7.0）。

## 代码地图

```
app/src/main/java/com/cxsign/sentinel/
├── MainActivity.kt          状态卡片 + 扫码 + 传图 + 设置 + cookie 导入
├── MapActivity.kt           WebView 加载引擎的 /map（地图选点）
├── SentinelService.kt       前台服务：保活 + 挂相册监听 + 状态通知
├── QrNotificationWatcher.kt 通道 1 通知栏取图 + QrDecoder 解码
│                            同文件下半部是 MediaObserver（通道 2 相册）
├── QrDecoder.kt             ML Kit 封装：放大重试 + 反色重试 + 回退给引擎
├── ShareReceiver.kt         通道 3 分享收图
├── EngineClient.kt          对引擎 HTTP API 的唯一出口
└── BootReceiver.kt          开机自启
```

## 已知边界

- **微信/QQ 的图片消息通知大多不带缩略图**。通道 1 对这两个 App 命中率不高，主力还是通道 2/3。
- **安卓 13+ 的 `READ_MEDIA_IMAGES` 只给"照片"权限**，读不到部分 App 私有目录里的图，这是系统限制。
- **国产 ROM 会杀前台服务**。给电池白名单是这个方案能不能用的分水岭。
- App 本身**不做签到协议**。引擎连不上时，App 只是个状态显示器 —— 这是刻意的：协议逻辑只有一份，改起来只有一处。
