# 文件清单 · 每一块是什么、怎么用

一份 zip 里有四个可运行的东西，按你想装在哪来挑。

---

## 先看这个

| 想干什么 | 打开 |
| --- | --- |
| 装到安卓手机上 | [android/termux/README.md](android/termux/README.md) ← **最省事，不用编译** |
| 装到 iPhone 上 | [ios/README.md](ios/README.md) |
| 在电脑上先跑通 | 本文档下面的「三分钟跑起来」 |
| 了解它怎么工作的 | [README.md](README.md) + [docs/](docs/) |
| 出问题了 | [INSTALL.md](INSTALL.md) 最后一张表 |

---

## 目录

```
cxsign-sentinel/
├── README.md              总览：能力边界、架构、配置项
├── INSTALL.md             安装手册：安卓 / iPhone / 电脑三条路
├── FILES.md               本文件
│
├── core/                  ★ 引擎（Python，零第三方依赖）
│   ├── run.py             命令行入口
│   ├── selfcheck.py       246 项离线自检（不联网）
│   ├── config.example.json
│   └── cxsign/
│       ├── protocol.py    纯函数：URL / 参数 / 类型判定 / 返回码
│       ├── net.py         会话、cookie、multipart、登录态探测
│       ├── engine.py      轮询状态机 + 五类执行器
│       ├── geo.py         坐标转换 + 抖动 + 地理编码
│       ├── qr.py          二维码解码（zxing-cpp / pyzbar / opencv / zbarimg）
│       ├── upload.py      图片校验 + 上传换 objectid
│       ├── uploadtest.py  upload-test 子命令的实现
│       ├── photoprobe.py  photoResult 结构分析器
│       ├── notify.py      Bark / ntfy / PushPlus / 企微
│       └── server.py      本地 HTTP API + SSE + 控制台页
│
├── web/
│   └── map.html           地图选点页（零依赖，高德瓦片，手机 WebView 直接用）
│
├── android/               ★ 安卓原生壳（需要构建）
│   ├── README.md          权限、构建、代码地图
│   ├── termux/            ★ 不用构建这条路
│   │   ├── README.md      一步一步的图文步骤
│   │   ├── install.sh     一键安装
│   │   └── start.sh       一键启动（带保活）
│   └── app/src/main/java/com/cxsign/sentinel/
│       ├── MainActivity.kt          状态 + 扫码 + 传图 + 设置
│       ├── MapActivity.kt           WebView 加载引擎的 /map
│       ├── SentinelService.kt       前台服务保活
│       ├── AutoScanService.kt       常驻摄像头找码
│       ├── QrNotificationWatcher.kt 通知栏取图 + 相册监听
│       ├── QrDecoder.kt             ML Kit 封装
│       ├── ShareReceiver.kt         分享收图
│       ├── EngineClient.kt          对引擎 HTTP API 的唯一出口
│       └── BootReceiver.kt          开机自启
│
├── android-hook/          LSPosed 模块（需要 root）
│   └── app/src/main/java/com/cxsign/hook/
│       ├── HookEntry.kt   核心：拦截相机 Intent，喂本地图
│       └── MainActivity.kt 选图 / 开关
│
├── ios/                   ★ iPhone（Scriptable）
│   ├── README.md          装法 + 快捷指令自动化
│   ├── CXSign.scriptable  ★ 直接导入这个
│   └── CXSign.js          同样的内容，纯 JS 版
│
├── docs/
│   ├── 01-协议速查.md       接口表 / 参数表 / 返回码
│   ├── 02-二维码取码链路.md  为什么 enc 只能看见、三条通道
│   ├── 03-位置签到与坐标系.md 三种坐标系 / 自动落点 / 抖动
│   ├── 04-拍照的硬边界.md    photoResult、PCR007、几条绕法
│   ├── 05-实测记录.md       ★ 哪些是实测的、哪些是猜的
│   └── architecture.png
│
├── tools/                 调试用的一次性脚本
│   ├── make_diagram.py    重新生成架构图
│   ├── probe_*.py         接口探测（二维码 / 上传 / 教师身份 / 通知）
│   ├── compare_endpoints.py  对比两个活动列表接口
│   ├── find_running.py    找进行中的活动
│   └── diag_courses.py    课程列表解析诊断
│
└── .github/workflows/
    ├── build-apk.yml      推 GitHub 自动构建安卓壳
    └── build-hook.yml     推 GitHub 自动构建 LSPosed 模块
```

---

## 三分钟跑起来（电脑上，验证协议通不通）

```bash
cd core
python run.py doctor                       # 环境自检
python run.py login --account 手机号 --password 密码
python run.py courses                      # 能列出课就通了
python run.py serve                        # 起服务
```

浏览器打开 `http://127.0.0.1:8848/`。

自检：

```bash
python selfcheck.py     # ✅ 全部 246 项通过
```

---

## 四个运行形态，选一个

| 形态 | 装什么 | 引擎在哪 | 需要 root | 需要编译 |
| --- | --- | --- | --- | --- |
| **A. 安卓 Termux** | Termux + 本 zip | 手机自己 | 否 | 否 |
| **B. 安卓 APK** | APK（`android/`） | 手机 Termux 或别的设备 | 否 | 是 |
| **C. iPhone** | Scriptable | 必须另找常开的设备 | 否 | 否 |
| **D. LSPosed 模块** | APK（`android-hook/`） | 不涉及 | **是** | 是 |

A 和 C 可以叠加用（手机装 Termux 跑引擎，iPhone 用 Scriptable 当遥控器）。

---

## 三端能力对照

| 能力 | Android（Termux + APK） | iOS（Scriptable） | 电脑 |
| --- | --- | --- | --- |
| 引擎常驻轮询 | ✅ 前台服务 | ❌ 平台不允许 | ✅ 一直开着 |
| 位置签到 | ✅ | ✅ | ✅ |
| 普通签到 | ✅ | ✅ | ✅ |
| 拍照签到 | ⚠️ 卡在上传 IP 白名单 | ⚠️ 同左 | ⚠️ 同左 |
| 二维码签到 | ⚠️ 码一出现能签，但码得有 | ⚠️ 同左 | ⚠️ 同左 |
| 通知栏自动取码 | ✅ | ❌ | ❌ |
| 地图选点 | ✅ WebView | ✅ WebView | ✅ 浏览器 |

---

## 隐私

- `core/data/cookie.json` 是你的登录凭证，别提交、别外发
- `.gitignore` 已经排除了 `core/data/`、`config.json`、`*.apk`
- 图片只会传到学习通自己的网盘，不进第三方
- 引擎默认只绑 `127.0.0.1`；要对外必须加 `--token`
