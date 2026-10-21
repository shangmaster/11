// 签到哨兵 · iOS 控制面板（Scriptable）
//
// 装法：
//   1. App Store 装 Scriptable
//   2. 新建脚本，把本文件内容整个粘进去，命名「签到哨兵」
//   3. 首次运行会让你填引擎地址（例如 http://192.168.1.9:8848）
//
// 为什么 iOS 只能做「遥控器」而不是像 Android 那样常驻：
//   · 第三方 App 不能后台常驻轮询
//   · 读不到别的 App 的通知内容和图片
//   所以真正干活的是引擎（跑在家里常开的设备或服务器上），
//   这个脚本负责：看状态 / 地图选点 / 传图 / 投码 / 收推送。
//
// 配合快捷指令可以做到「分享一张图就签到」，见同目录 README。

const CFG_FILE = "cxsign-config.json";

// ---------------------------------------------------------------- 配置存取

function loadCfg() {
  const fm = FileManager.local();
  const p = fm.joinPath(fm.documentsDirectory(), CFG_FILE);
  if (fm.fileExists(p)) {
    try { return JSON.parse(fm.readString(p)); } catch (e) { /* 掉下去用默认 */ }
  }
  return { baseUrl: "http://192.168.1.9:8848", token: "" };
}

function saveCfg(cfg) {
  const fm = FileManager.local();
  fm.writeString(fm.joinPath(fm.documentsDirectory(), CFG_FILE), JSON.stringify(cfg));
}

// ---------------------------------------------------------------- HTTP

function apiUrl(cfg, path) {
  const sep = path.includes("?") ? "&" : "?";
  const t = cfg.token ? sep + "token=" + encodeURIComponent(cfg.token) : "";
  return cfg.baseUrl.replace(/\/+$/, "") + path + t;
}

async function apiGet(cfg, path) {
  const r = new Request(apiUrl(cfg, path));
  r.timeoutInterval = 8;
  if (cfg.token) r.headers = { "X-Cx-Token": cfg.token };
  try { return await r.loadJSON(); }
  catch (e) { return { ok: false, error: String(e) }; }
}

async function apiPost(cfg, path, obj) {
  const r = new Request(apiUrl(cfg, path));
  r.method = "POST";
  r.timeoutInterval = 25;
  r.headers = { "Content-Type": "application/json" };
  if (cfg.token) r.headers["X-Cx-Token"] = cfg.token;
  r.body = JSON.stringify(obj || {});
  try { return await r.loadJSON(); }
  catch (e) { return { ok: false, error: String(e) }; }
}

async function apiImage(cfg, path, data, mime) {
  const r = new Request(apiUrl(cfg, path));
  r.method = "POST";
  r.timeoutInterval = 40;
  r.headers = { "Content-Type": mime || "image/jpeg" };
  if (cfg.token) r.headers["X-Cx-Token"] = cfg.token;
  r.body = data;
  try { return await r.loadJSON(); }
  catch (e) { return { ok: false, error: String(e) }; }
}

// ---------------------------------------------------------------- 视图

function row(t, sub) {
  const r = new UITableRow();
  const c = r.addText(t, sub || "");
  c.titleFont = Font.boldSystemFont(15);
  if (sub) c.subtitleFont = Font.systemFont(11);
  r.dismissOnSelect = true;
  return r;
}

function divider(t) {
  const r = new UITableRow();
  r.addText(t, "");
  r.dismissOnSelect = false;
  return r;
}

async function showMenu(cfg) {
  const t = new UITable();
  const st = await apiGet(cfg, "/api/status");

  // 状态区
  const head = new UITableRow();
  head.dismissOnSelect = false;
  if (st && st.ok) {
    const d = st.data || {};
    const login = d.login || {};
    const stats = d.stats || {};
    const pending = (d.pending || []).length;
    head.addText(
      pending > 0 ? `⏳ 等码 ${pending} 个` : `监听中 · 已签 ${d.signed || 0} 次`,
      `uid ${login.uid || "-"} · 课程 ${d.courses || 0} · 轮询 ${stats.polls || 0} 轮`
    );
  } else {
    head.addText("⚠️ 引擎未连接", (st && st.error) || "检查地址设置");
  }
  t.addRow(head);

  // 地图
  const mapRow = row("🗺 地图选点", "在地图上随便点一个位置当签到点");
  mapRow.onSelect = () => { presentMap(cfg); };
  t.addRow(mapRow);

  // 投二维码
  const qrRow = row("📷 投一张二维码", "从相册选图 / 粘贴文本 / 手动输入链接");
  qrRow.onSelect = () => { pickQrSource(cfg); };
  t.addRow(qrRow);

  // 传照片
  const photoRow = row("🖼 设置签到照片", "从相册选一张，之后拍照签到都用它");
  photoRow.onSelect = () => { pickPhoto(cfg); };
  t.addRow(photoRow);

  // 立刻轮询
  const pollRow = row("🔄 立刻轮询一轮", "不等引擎的定时器");
  pollRow.onSelect = async () => {
    const r = await apiPost(cfg, "/api/poll", {});
    const n = (r && r.results) ? r.results.length : 0;
    pasteboardSafe(`轮询完成，处理 ${n} 个`);
  };
  t.addRow(pollRow);

  // 记录
  const recRow = row("📋 签到记录", "");
  recRow.onSelect = () => { showRecords(cfg); };
  t.addRow(recRow);

  // 设置
  const setRow = row("⚙️ 引擎地址 / 令牌", cfg.baseUrl);
  setRow.onSelect = () => { editConfig(cfg); };
  t.addRow(setRow);

  await t.present();
}

function presentMap(cfg) {
  const wv = new WebView();
  const url = apiUrl(cfg, "/map");
  wv.loadURL(url);
  wv.present(true);
}

function showRecords(cfg) {
  (async () => {
    const recs = await apiGet(cfg, "/api/records");
    const t = new UITable();
    if (!recs || !recs.ok) {
      t.addRow(row("读取失败", (recs && recs.error) || ""));
    } else {
      const signed = recs.signed || {};
      const keys = Object.keys(signed);
      if (!keys.length) t.addRow(row("还没有记录", ""));
      for (const k of keys.slice(-30).reverse()) {
        const o = signed[k];
        t.addRow(row(`${o.name || k} [${o.kind || "?"}]`, o.message || ""));
      }
    }
    await t.present();
  })();
}

async function pickQrSource(cfg) {
  const a = new Alert();
  a.title = "投递二维码";
  a.message = "选一种方式把老师的码交给引擎";
  a.addAction("从相册选图");
  a.addAction("粘贴文本/链接");
  a.addDestructiveAction("取消");
  const i = await a.presentSheet();

  if (i === 0) {
    try {
      const img = await Photos.fromLibrary();
      const data = Data.fromPNG(img);
      const r = await apiImage(cfg, "/api/qr", data, "image/png");
      const n = (r && r.results) ? r.results.length : 0;
      pasteboardSafe(r && r.ok ? `已投递，触发 ${n} 次签到` : `失败：${r && r.error}`);
    } catch (e) {
      pasteboardSafe("取消或读取相册失败");
    }
    return;
  }
  if (i === 1) {
    let text = "";
    try { text = Pasteboard.paste() || ""; } catch (e) { /* 空剪贴板 */ }
    const a2 = new Alert();
    a2.title = "二维码内容";
    a2.addTextField("粘贴二维码文本或分享链接", text);
    a2.addAction("提交");
    a2.addCancelAction("取消");
    const j = await a2.present();
    if (j < 0) return;
    const r = await apiPost(cfg, "/api/qr", { text: a2.textFieldValue(0) });
    const n = (r && r.results) ? r.results.length : 0;
    pasteboardSafe(r && r.ok ? `已提交，触发 ${n} 次签到` : `失败：${r && r.error}`);
  }
}

async function pickPhoto(cfg) {
  try {
    const img = await Photos.fromLibrary();
    const data = Data.fromPNG(img);
    const r = await apiImage(cfg, "/api/photo", data, "image/png");
    pasteboardSafe(r && r.ok ? "✅ 照片已设为签到图" : `失败：${r && r.error}`);
  } catch (e) {
    pasteboardSafe("取消");
  }
}

async function editConfig(cfg) {
  const a = new Alert();
  a.title = "引擎地址";
  a.message = "填 http://IP:端口，本机不给后台常驻，建议放常开的设备或服务器";
  a.addTextField("http://192.168.1.9:8848", cfg.baseUrl);
  a.addTextField("访问令牌（没设留空）", cfg.token || "");
  a.addAction("保存并测试");
  a.addCancelAction("取消");
  const i = await a.present();
  if (i < 0) return;
  const next = { baseUrl: a.textFieldValue(0).trim(), token: a.textFieldValue(1).trim() };
  saveCfg(next);
  const st = await apiGet(next, "/api/status");
  const text = st && st.ok
    ? `连接成功：已签 ${(st.data || {}).signed || 0} 次`
    : `连不上：${(st && st.error) || "检查地址/防火墙"}`;
  pasteboardSafe(text);
}

function pasteboardSafe(s) {
  try { Pasteboard.copy(String(s)); } catch (e) { /* 忽略 */ }
  const a = new Alert();
  a.title = "签到哨兵";
  a.message = String(s);
  a.addAction("好");
  a.present();
}

// ---------------------------------------------------------------- 入口

// 从快捷指令调用时可以传参：?qr=<文本> 直接把码投进去
const params = args.queryParameters || {};
const cfg = loadCfg();

if (params.qr) {
  apiPost(cfg, "/api/qr", { text: params.qr, source: "shortcut" })
    .then(r => {
      const n = (r && r.results) ? r.results.length : 0;
      pasteboardSafe(r && r.ok ? `已投递，触发 ${n} 次签到` : `失败：${r && r.error}`);
    });
} else if (params.action === "poll") {
  apiPost(cfg, "/api/poll", {}).then(r => {
    pasteboardSafe(`轮询完成，处理 ${(r && r.results) ? r.results.length : 0} 个`);
  });
} else {
  await showMenu(cfg);
}

Script.complete();
