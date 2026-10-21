# iOS 壳 · 签到哨兵

## 先说清楚 iOS 能做到什么、做不到什么

iOS 的沙盒比 Android 严得多。这不是技术选择，是平台规则：

| 能力 | Android | iOS | iOS 上的替代 |
| --- | --- | --- | --- |
| 后台常驻轮询 | ✅ 前台服务 | ❌ | **引擎跑在别的设备上**，手机只收推送 |
| 读别的 App 的通知内容 | ✅ 通知使用权 | ❌ 完全不行 | 无 |
| 后台读相册新图 | ✅ ContentObserver | ❌ | 分享扩展（手动一次） |
| 后台自动提交 HTTP | ✅ | ❌ 后台会被挂起 | 服务端干，手机不管 |

结论：**iOS 上「无人值守」要靠把引擎搬到一台常开的设备上**（旧安卓手机、树莓派、NAS、云服务器都行，成本几十块到几块一个月）。
手机端负责：看一眼状态、地图选点、传张照片、投一次码。真正的轮询和签到在引擎那边 7×24 跑。

这样做反而比 Android 本机跑更省电、更稳。

## 装

1. App Store 搜 **Scriptable**（免费）装上
2. 打开 Scriptable → `+` → 把 `CXSign.js` 全文粘进去 → 命名「签到哨兵」
3. 脚本目录里点它运行，第一次会让你填**引擎地址**
   - 局域网：`http://192.168.1.9:8848`
   - 有公网/内网穿透：`https://你的域名`（建议加 Cloudflare Access 或 basic auth）

填完会立刻测一次连接，成功会提示「已签 N 次」。

## 面板能干什么

| 项 | 说明 |
| --- | --- |
| 🗺 地图选点 | 打开引擎自带的地图页（高德瓦片，GCJ-02），点哪算哪，一键设为签到点 |
| 📷 投一张二维码 | 相册选图 / 粘贴文本 / 粘贴链接，三种都行 |
| 🖼 设置签到照片 | 从相册选一张，之后所有拍照签到都用它（服务端存的是这张） |
| 🔄 立刻轮询 | 不等定时器，马上查一遍所有课程 |
| 📋 签到记录 | 已签的活动 + 服务端返回的原始结论 |
| ⚙️ 地址 / 令牌 | 改引擎地址，改完立刻测连通 |

## 让它更「自动」：快捷指令

Scriptable 脚本支持 URL 参数，所以快捷指令能直接驱动它。

### 1）分享一张图就投码（最常用）

新建快捷指令「投签到码」：

```
接收 图像 类型的输入
  ↓
Base64 编码（输入：快捷指令输入）
  ↓
获取 URL 内容
    URL: http://192.168.1.9:8848/api/qr?token=你的令牌
    方法: POST
    请求头: Content-Type = image/jpeg
    请求体: JSON  →  其实用「文件」更直接：把 Base64 解码回文件塞进请求体
  ↓
显示结果
```

更省事的写法：**用 Scriptable 脚本处理**

```
接收 图像 输入
  ↓
运行脚本「签到哨兵」  (参数：qr 走不了图片，所以这里改成)
  ↓
其实用这一段更靠谱：
  在快捷指令里选「运行 JavaScript」不行（iOS 没这个动作）
  正确做法：新建一个专门的 Scriptable 脚本 CXPush.js，内容只有 20 行 ↓
```

`CXPush.js`（另存一个脚本，专门给分享扩展用）：

```js
// 接收分享进来的图片，直接投给引擎
const cfg = (() => {
  const fm = FileManager.local();
  const p = fm.joinPath(fm.documentsDirectory(), "cxsign-config.json");
  try { return JSON.parse(fm.readString(p)); } catch (e) {
    return { baseUrl: "http://192.168.1.9:8848", token: "" };
  }
})();

const img = await Photos.fromLibrary().catch(() => null) ||
            (args.images && args.images[0]);
if (!img) { Script.complete(); return; }

const r = new Request(cfg.baseUrl + "/api/qr?token=" + encodeURIComponent(cfg.token || ""));
r.method = "POST";
r.headers = { "Content-Type": "image/png" };
r.body = Data.fromPNG(img);
const j = await r.loadJSON().catch(() => ({ ok: false }));
const n = (j.results || []).length;
Pasteboard.copy(j.ok ? `已投递，触发 ${n} 次签到` : "投递失败");
Script.complete();
```

然后在「照片」App 里：长按二维码图 → 分享 → 投签到码。**两步**。

### 2）打开学习通时自动轮询一次

快捷指令 → 自动化 → `App` → 选「学习通」→「已打开」→ 关闭「运行前询问」→ 动作：`获取 URL 内容`（`POST/API/poll`）。

效果：你每次切到学习通，引擎就立刻查一遍，比等定时器快。

### 3）定时轮询兜底

自动化 → `时间` → 每小时 → `POST /api/poll?token=...`。
（iOS 的时间自动化不能太频繁，系统会合并。）

## 收结果：Bark

引擎签完会推送到手机。iOS 上最省事的是 **Bark**：

1. App Store 装 Bark，拿到形如 `https://api.day.app/xxxxxxxx` 的地址
2. 写进引擎的 `config.json`：

```json
{ "notify": { "bark": "https://api.day.app/xxxxxxxx" } }
```

之后签到成功/失败都会弹一条，点开直接跳回 App。

## 已知边界

- **iOS 拿不到别的 App 的通知图片**。这条通道只有 Android 有。
- **后台不会跑脚本**。所有「自动」都发生在引擎那台设备上，手机只是个显示器。
- **Scriptable 的 WebView 里的定位权限**取决于系统弹窗，第一次要允许。
- 如果引擎放在公网，**务必带 token 并套 HTTPS**，否则等于把账号签到权公开。
