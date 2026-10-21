# 签到哨兵 · 学习通自动签到（Android + iOS）

> 轮询发现签到 → 判定类型 → 自动提交。位置能在地图上随便点，二维码能自己抓，拍照能传本地图。

![架构](docs/architecture.png)

---

## 先说清楚一件事：为什么不是「改学习通 App」

点开 [chaoxing.com](https://www.chaoxing.com/) 只有一个 App 下载页 —— 官方没开放任何签到接口，也没有可用的第三方 SDK。

所以只有三条路：

| 路线 | 能不能走 | 原因 |
| --- | --- | --- |
| 改官方 APK 加自动化 | 安卓勉强，iOS 死路 | 改完签名变了，学习通的完整性校验会拦；iOS 根本没法侧载改过的包 |
| 用无障碍/自动化点屏幕 | 能，但极脆 | 官方 App 一更新界面就废；而且签到要在几秒内完成，点屏幕来不及 |
| **直接说 App 说的那套 HTTP 协议** | ✅ | 签到本质是几个 GET/POST。协议稳定、跨平台、耗电低 |

这个项目走第三条。**同一个协议引擎，安卓和 iOS 共用**，手机端只是遥控器。

---

## 能力对照

| 你要的 | 做到什么程度 | 怎么实现的 |
| --- | --- | --- |
| 时刻检测签到任务 | ✅ 5 秒一轮（有活动时）/ 12 秒（空闲退避） | 轮询所有课程的 `activelist`，只挑 `status=1` 进行中的 |
| 判断签到类型 | ✅ 9 种全覆盖 | 活动详情接口的 `activeSort` 是唯一可靠判据，其次 `otherId`，最后按活动名兜底 |
| 位置签到：地图任意选点 | ✅ 点哪算哪 | 内置零依赖高德瓦片地图（GCJ-02），选完直接写进引擎 |
| 位置签到：全自动 | ✅ 不需要人 | 老师填的 `locationText` 自动地理编码 + 几十米随机抖动 |
| 二维码：自动检测并签到 | ✅ 三条通道 | 通知栏取图 / 相册新图 / 分享导入，解码出 `enc` 直接提交 |
| 二维码：完全无需操作 | ⚠️ 看渠道 | 码发在超星通知里 → 全自动；只在微信群里 → 安卓通知栏能抓一部分，抓不到就分享一次 |
| 拍照签到：从本地交图 | ✅ | 图片传到学习通网盘换 `objectId` 再提交，支持多张轮换 |
| iOS + Android 都能用 | ✅ | 引擎跨平台（纯标准库）；安卓原生壳，iOS 走 Scriptable + 快捷指令 |

---

## 架构

```
                     ┌──────────────────────────────────────┐
                     │  core/  引擎（Python，零第三方依赖）    │
                     │                                      │
  学习通服务器 ◄──────►│  session    cookie 池 / 登录态探测     │
  mobilelearn         │  discovery  课程 → 活动列表 → 详情     │
  pan-yz              │  classify   activeSort → 9 种类型     │
  passport2           │  signer     位置 / 二维码 / 拍照 / 码   │
                     │  qr         图片 → enc（pyzbar/cv2）  │
                     │  geo        WGS84↔GCJ02↔BD09 + 编码   │
                     │  daemon     轮询状态机 + 去重          │
                     │  server     本地 HTTP API + 地图页     │
                     └───────────────┬──────────────────────┘
                          HTTP 127.0.0.1:8848 或 局域网
                     ┌───────────────┴──────────────────────┐
                     │                                      │
        ┌────────────▼────────────┐      ┌─────────────────▼────────┐
        │  android/  原生壳        │      │  ios/  Scriptable 面板    │
        │  · 前台服务保活          │      │  · 状态 / 地图 / 传图      │
        │  · 通知栏取图（ML Kit）  │      │  · 快捷指令自动化          │
        │  · 相册新图监听          │      │  · 分享扩展投码            │
        │  · 分享收图              │      │  · Bark 收推送            │
        │  · WebView 地图选点      │      │  · WebView 地图选点        │
        └─────────────────────────┘      └──────────────────────────┘
```

**为什么引擎和界面分开**：协议只有一份实现（`core/cxsign/`），三端共用。学习通改字段时只改一处。
iOS 更不能把引擎放手机里 —— 那边后台会被挂起，只能让引擎跑在常开的设备上，手机当显示器。

---

## 五分钟跑起来

> 只想装到手机上、不想看原理？直接跳 **[INSTALL.md](INSTALL.md)**（安卓 / iPhone 两套步骤，带界面路径）。
> 打包好的zip：**[cxsign-sentinel.zip](cxsign-sentinel.zip)**

### 1. 拿 cookie

浏览器登录 [i.chaoxing.com](https://i.chaoxing.com) → F12 → Network → 点任意请求 → 复制整行 `Cookie`。

### 2. 起引擎

```bash
cd core
python run.py doctor                          # 先看环境：解码器在不在、DNS 通不通
python run.py login --cookie "_uid=...; fid=...; _d=...; uf=..."
python run.py courses                         # 确认能列出课程
cp config.example.json config.json            # 按需改，见下方配置表
python run.py all                             # 轮询 + 本地 API（手机端连这个）
```

打开 `http://127.0.0.1:8848/` 就是控制台。

### 3. 装手机端

- **安卓**：`cd android && ./gradlew assembleDebug`，装 APK，给它通知使用权 + 电池白名单 → 详见 [android/README.md](android/README.md)
- **iOS**：装 Scriptable，粘 [ios/CXSign.js](ios/CXSign.js) → 详见 [ios/README.md](ios/README.md)

### 4. 配一下位置（只有位置签到需要）

`config.json`：

```json
{
  "location": {
    "mode": "auto",
    "amapKey": "你的高德 Web 服务 key"
  }
}
```

`mode: "auto"` 表示「老师填了地址，我自己解析坐标」。高德 key 免费申请，5 分钟，地址解析准得多；
不想申请就把 `mode` 改成 `"manual"`，第一次在地图页点一次，之后一直用它。

> 高德申请：开放平台 → 应用管理 → 创建应用 → 添加 Key → 服务平台选 **Web 服务**。

---

## 三类签到具体怎么处理

### 位置签到（`activeSort=4 / 5`）

签到接口吃的是**客户端上报的经纬度**，服务端只拿它算和老师设定点的距离。所以坐标是自己填的。

引擎的三级取点策略：

1. 地图上手动选的点（最高优先）
2. 配置里写死的 `location.point`
3. 老师的 `locationText` 自动地理编码

拿到 GCJ-02 坐标后，按 `jitterMeters` 在周围随机偏几十米再提交 —— 连续十几次签到都落在小数点后第 7 位一模一样的位置，在老师的签到明细里一眼就能看出来。

坐标系统一在 `cxsign/geo.py` 里转换：高德/腾讯 = GCJ-02，GPS = WGS-84，百度 = BD-09。地图页用的是高德瓦片，所以页面上显示什么坐标，提交的就是什么。

### 二维码签到（`activeSort=6 / 7 / 8`）

关键在于 `enc` —— 它只存在于老师那张码里，抓包拿不到，接口也不返回。所以只能从图里读。

三条并行的取码通道：

| 通道 | 触发条件 | 覆盖场景 |
| --- | --- | --- |
| 通知栏 | Android 通知使用权 | 学习通自己的签到推送、群里转发的二维码图 |
| 相册 | 新图片落盘 | 学委截图存相册 |
| 分享 | 长按图片 → 分享 → 签到哨兵 | 微信/QQ 群里的图（它们的通知不带缩略图） |

拿到码之后走 `parse_qr()`，三种载荷都认：

```
https://mobilelearn.chaoxing.com/widget/sign/e?id=<activeId>&enc=<enc>     H5 活码
https://mobilelearn.chaoxing.com/widget/sign/signIn?activeId=&ewnCode=     轮换码
SIGNIN:<payload>                                                          官方扫描器
```

然后 `GET/POST /pptSign/stuSignajax?...&enc=<enc>`，返回 `success` 就成。

> 活码的 `c` 参数每 10~30 秒变一次，但 `enc` 在活动期间不变 —— 所以抓到任意一帧就够，不用追着刷新。

### 拍照签到（`activeSort=3`）

```
本地图片 → GET  pan-yz.chaoxing.com/api/token?puid=<uid>
        → POST pan-yz.chaoxing.com/upload  (puid, _token, file)
        → 得到 objectid
        → 提交 stuSignajax 时带上 objectId
```

支持 `photo.album` 多图轮换 —— 每次都传同一张，服务端存下来的照片会有一串一模一样的，太显眼。

**硬边界**：老师如果勾了「现场拍摄凭证」，只传 `objectId` 会被回 `photoAuthError_PCR007`。
那个凭证（`photoResult`）由官方 App 原生桥生成。**换什么界面都没用** —— 网页、自己写的 App、这个引擎，走的都是同一套 HTTP，一样过不去。

两条路，按顺序试：

1. **先判断它是不是客户端拼的**
   `python run.py probe-photo --text "<抓到的 photoResult>"`
   如果它只是「时间戳 + 坐标 + 图 hash」，我们自己就能算，问题当场解决。
2. **算不出来就 hook**
   [android-hook/](android-hook/) 是一个 LSPosed 模块：在官方 App 打开相机的那一刻替它"拍"一张你相册里的图。凭证仍由官方 App 生成，所以服务端认。
   门槛：安卓 + root + LSPosed。iPhone 不越狱无解。

详见 [docs/04-拍照的硬边界.md](docs/04-拍照的硬边界.md)。

---

## 配置项

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `poll.activeSeconds` | 5 | 有进行中活动时的轮询间隔 |
| `poll.idleSeconds` | 12 | 没活动时退避（省电、少打扰服务端） |
| `sign.plain/location/qr` | true | 哪几类自动签 |
| `sign.code` | false | 签到码要老师屏幕上的数字，默认关 |
| `location.mode` | auto | `auto` 自动解析地址 / `fixed` 固定点 / `manual` 只认手选 |
| `location.amapKey` | 空 | 高德 Web 服务 key，填了地址解析才准 |
| `location.jitterMeters` | 30 | 落点随机偏移半径，0 = 关闭 |
| `photo.album` | [] | 多张照片轮流用 |
| `photo.photoResult` | 空 | 现场凭证，见 docs/04 |
| `qr.pendingMinutes` | 25 | 二维码签到挂起等码的时长 |
| `notify.bark/ntfy/pushplus/wecom` | 空 | 推送通道，任填其一 |

---

## 目录

```
cxsign-sentinel/
├── core/                       引擎（Python，标准库 + 可选解码器）
│   ├── cxsign/
│   │   ├── protocol.py         纯函数：URL / 参数 / 类型判定 / 返回码
│   │   ├── net.py              会话、cookie、multipart、登录态探测
│   │   ├── engine.py           轮询状态机 + 五类执行器
│   │   ├── geo.py              坐标转换 + 抖动 + 地理编码
│   │   ├── qr.py               二维码解码（pyzbar / opencv / zbarimg）
│   │   ├── upload.py           图片校验 + 网盘上传换 objectid
│   │   ├── notify.py           Bark / ntfy / PushPlus / 企微
│   │   └── server.py           本地 HTTP API + SSE + 控制台页
│   ├── run.py                  CLI：doctor/login/courses/watch/serve/qr/point/sign
│   ├── selfcheck.py            197 项离线自检（含真起 HTTP 服务打本机）
│   └── config.example.json
├── web/map.html                地图选点页（零依赖，高德瓦片，手机 WebView 直接用）
├── android/                    原生壳：前台服务 / 通知取图 / ML Kit / 地图
├── ios/                        Scriptable 面板 + 快捷指令
└── docs/
    ├── 01-协议速查.md              接口表 / 参数表 / 返回码 / 两个判定坑
    ├── 02-二维码取码链路.md        为什么 enc 只能从图里读、三条通道
    ├── 03-位置签到与坐标系.md      三种坐标系 / 自动落点 / 抖动
    └── 04-拍照的硬边界.md          photoResult、PCR007、三条绕法
```

跑测试：

```bash
cd core && python selfcheck.py
# ✅ 全部 197 项通过
```

---

## 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `run.py doctor` 说登录态无效 | cookie 过期。重新从浏览器复制；注意 `_uid` / `fid` 两个必须都在 |
| 位置签到一直不动 | `location.amapKey` 没填、或老师的 `locationText` 解析不出来。去地图页手动点一次 |
| 二维码签到一直「等码」 | 引擎没收到码。安卓查通知使用权有没有给；或者手动把图分享进来 |
| 返回 `validate` | 老师开了防作弊验证码。这条引擎不做，需要人工 |
| 返回 `photoAuthError_PCR007` | 要现场拍摄凭证，见 docs/04 |
| 返回「请先登录再进行签到」 | 登录态掉了，`run.py login` 重导 |
| 安卓服务活不过一小时 | 电池优化没关。小米/华为还要单独开「自启动」 |
| iOS 收不到推送 | `notify.bark` 没填，或 Bark 的 key 过期 |
| 地图一片灰 | 瓦片被网络拦了。换成 OSM 瓦片或直接手填坐标 |

---

## 边界

- **这是自动化，不是破解**。协议是学习通 App 自己在用的公开 HTTP 接口，登录用的是你自己的账号凭证。
- **签到本质是考勤**。改了位置、交了非现场照片，被发现是纪律问题，风险自己担。
- **服务端随时可能加校验**。设备指纹、签名、IP 归属地比对、照片现场性检测，任何一项上来都可能导致失效。当前实现已经尽量贴着官方客户端的行为（UA、`deviceCode`、`preSign` 预热、先 GET 后 POST 的区分）。
- **只在自己的账号上用**。替别人签到是另一回事，这个项目不做。
- **图片会上传到你的学习通网盘**（换 `objectId` 只能这样）。引擎不把图发给任何第三方。
- **引擎对外必须带 `--token`**，默认只绑 `127.0.0.1`。端口裸奔等于把签到权交出去。
