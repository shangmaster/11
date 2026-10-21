"""本地 HTTP API：手机壳（Android 原生 / iOS Scriptable）跟引擎说话的唯一入口。

为什么用本地 HTTP 而不是直接嵌 Python：
  · Android 壳是 Kotlin，iOS 壳是 JavaScript，两边只会 HTTP
  · 引擎可以同一份代码跑在手机里（Termux）或跑在服务器上，App 只换 baseURL
  · 调试简单：浏览器打开 http://127.0.0.1:8848/ 就能看到状态

默认只绑 127.0.0.1，除非显式 --host 0.0.0.0 并且设了 token。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import Engine
from .protocol import KIND_LABELS

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "web"))


class EventBus:
    """极简发布订阅：SSE 长连接和最近事件列表共用。"""

    def __init__(self, size: int = 300):
        self.items: deque[dict] = deque(maxlen=size)
        self.lock = threading.Condition()
        self.seq = 0

    def push(self, ev: dict) -> None:
        with self.lock:
            self.seq += 1
            ev = dict(ev)
            ev["id"] = self.seq
            self.items.append(ev)
            self.lock.notify_all()

    def tail(self, n: int = 100) -> list[dict]:
        with self.lock:
            return list(self.items)[-n:]

    def wait_after(self, seq: int, timeout: float = 20.0) -> list[dict]:
        with self.lock:
            if self.seq <= seq:
                self.lock.wait(timeout)
            return [e for e in self.items if e["id"] > seq]


class Api:
    def __init__(self, engine: Engine, bus: EventBus, token: str = ""):
        self.engine = engine
        self.bus = bus
        self.token = token


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CxSignSentinel/1.0"
        protocol_version = "HTTP/1.1"

        # ---------------- 基础 ----------------

        def log_message(self, fmt, *args):    # 静音默认访问日志
            return

        def _authed(self) -> bool:
            if not api.token:
                return True
            q = urllib.parse.urlparse(self.path).query
            tok = urllib.parse.parse_qs(q).get("token", [""])[0]
            tok = tok or self.headers.get("X-Cx-Token", "")
            return tok == api.token

        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8",
                  extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Cx-Token")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n > 0 else b""

        def _body_json(self) -> dict:
            raw = self._body()
            if not raw:
                return {}
            try:
                d = json.loads(raw)
                return d if isinstance(d, dict) else {}
            except Exception:
                return {}

        # ---------------- 路由 ----------------

        def do_OPTIONS(self):
            self._send(204, b"")

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index.html"):
                html = _INDEX_HTML.replace("__TOKEN__", api.token)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if path.startswith("/map"):
                return self._serve_static("map.html")
            if path in ("/api/status",):
                if not self._authed():
                    return self._json({"ok": False, "error": "token"}, 403)
                return self._json({"ok": True, "data": api.engine.status(),
                                   "kinds": KIND_LABELS})
            if path == "/api/records":
                if not self._authed():
                    return self._json({"ok": False, "error": "token"}, 403)
                return self._json({"ok": True,
                                   "signed": api.engine.state.data.get("signed") or {},
                                   "pending": api.engine.state.pending()})
            if path == "/api/events":
                return self._sse()
            if path == "/api/qr/backends":
                from . import qr as qrdecode
                return self._json({"ok": True, "backends": qrdecode.backends(),
                                   "available": qrdecode.available()})
            if path == "/api/geocode":
                return self._geocode()
            if path == "/api/hints":
                if not self._authed():
                    return self._json({"ok": False, "error": "token"}, 403)
                return self._json({"ok": True, "hints": api.engine.location_hints()})
            if path == "/api/courses":
                if not self._authed():
                    return self._json({"ok": False, "error": "token"}, 403)
                return self._json({"ok": True, "data": api.engine.refresh_courses()})
            return self._json({"ok": False, "error": "not found"}, 404)

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if not self._authed():
                return self._json({"ok": False, "error": "token"}, 403)

            if path == "/api/point":
                d = self._body_json()
                try:
                    lat = float(d.get("lat"))
                    lon = float(d.get("lon"))
                except (TypeError, ValueError):
                    return self._json({"ok": False, "error": "lat/lon 必填"}, 400)
                api.engine.set_point(lat, lon, str(d.get("datum") or "gcj02"))
                return self._json({"ok": True, "point": api.engine._point})   # noqa: SLF001

            if path == "/api/point/clear":
                api.engine.clear_point()
                return self._json({"ok": True})

            if path == "/api/photo":
                ctype = self.headers.get("Content-Type", "")
                if ctype.startswith("image/") or ctype == "application/octet-stream":
                    data = self._body()
                    tmp = os.path.join(_tmpdir(), f"upload_{int(time.time()*1000)}.jpg")
                    with open(tmp, "wb") as fh:
                        fh.write(data)
                    ok = api.engine.set_photo(tmp)
                    return self._json({"ok": ok, "path": tmp if ok else ""})
                d = self._body_json()
                ok = api.engine.set_photo(str(d.get("path") or ""))
                return self._json({"ok": ok, "path": d.get("path")})

            if path == "/api/qr":
                ctype = self.headers.get("Content-Type", "")
                if ctype.startswith("image/"):
                    recs = api.engine.feed_qr(self._body(), source="http-image")
                    return self._json({"ok": True,
                                       "results": [r.to_dict() for r in recs]})
                d = self._body_json()
                text = str(d.get("text") or "")
                if not text:
                    raw = self._body()
                    text = raw.decode("utf-8", "replace")
                    if not text and raw:
                        recs = api.engine.feed_qr(raw, source="http-bytes")
                        return self._json({"ok": True,
                                           "results": [r.to_dict() for r in recs]})
                recs = api.engine.feed_qr(text, source=str(d.get("source") or "http"))
                return self._json({"ok": True, "results": [r.to_dict() for r in recs]})

            if path == "/api/poll":
                recs = api.engine.poll_once()
                return self._json({"ok": True, "results": [r.to_dict() for r in recs]})

            if path == "/api/sign":
                d = self._body_json()
                aid = str(d.get("activeId") or "")
                if not aid:
                    return self._json({"ok": False, "error": "activeId 必填"}, 400)
                return self._json({"ok": True, "data": _sign_by_id(api.engine, aid,
                                                                  str(d.get("kind") or ""))})

            if path == "/api/login":
                d = self._body_json()
                raw = str(d.get("cookie") or "")
                if not raw.strip():
                    return self._json({"ok": False, "error": "cookie 必填"}, 400)
                cookie = extract_cookie(raw)
                if not cookie:
                    return self._json({
                        "ok": False,
                        "error": "这段内容里没有 cookie。多半是复制到了一条静态资源请求"
                                 "（CDN / .js / 图片都不带 cookie）。"
                                 "请挑一条 chaoxing.com 的接口请求，最好是含 "
                                 "backclazzdata 或 mobilelearn 的",
                    }, 400)
                n = api.engine.s.set_cookies(cookie)
                if n == 0:
                    return self._json({
                        "ok": False,
                        "error": "解析出 0 条 cookie，确认复制的是 chaoxing.com 的请求",
                    }, 400)
                ok, why = api.engine.s.probe_login()
                if ok:
                    api.engine.s.save()
                    api.engine.refresh_courses()
                return self._json({"ok": ok, "message": why, "imported": n,
                                   "uid": api.engine.s.uid, "fid": api.engine.s.fid})

            return self._json({"ok": False, "error": "not found"}, 404)

        # ---------------- 地理编码 ----------------

        def _geocode(self):
            """正/逆地理编码。地图页用，避免把高德 key 暴露在网页里。"""
            if not self._authed():
                return self._json({"ok": False, "error": "token"}, 403)
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if qs.get("q"):
                return self._json(_geocode_forward(qs["q"][0], api.engine))
            if qs.get("lat") and qs.get("lon"):
                try:
                    lat = float(qs["lat"][0])
                    lon = float(qs["lon"][0])
                except ValueError:
                    return self._json({"ok": False, "error": "坐标格式错误"}, 400)
                return self._json(_geocode_reverse(lat, lon, api.engine))
            return self._json({"ok": False, "error": "需要 q 或 lat/lon"}, 400)

        # ---------------- SSE ----------------

        def _sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            seq = 0
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if qs.get("since"):
                try:
                    seq = int(qs["since"][0])
                except ValueError:
                    seq = 0
            deadline = time.time() + 1800     # 半小时后自然断开，客户端重连
            try:
                for ev in api.bus.tail(30):
                    self._sse_write(ev)
                    seq = max(seq, int(ev.get("id") or 0))
                while time.time() < deadline:
                    batch = api.bus.wait_after(seq, timeout=15)
                    if not batch:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    for ev in batch:
                        self._sse_write(ev)
                        seq = max(seq, int(ev.get("id") or 0))
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def _sse_write(self, ev: dict) -> None:
            payload = json.dumps(ev, ensure_ascii=False)
            self.wfile.write(f"id: {ev.get('id')}\ndata: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()

        # ---------------- 静态 ----------------

        def _serve_static(self, name: str):
            path = os.path.join(WEB_DIR, name)
            if not os.path.exists(path):
                return self._json({"ok": False, "error": "web/map.html 不存在"}, 404)
            with open(path, "rb") as fh:
                body = fh.read()
            return self._send(200, body, "text/html; charset=utf-8")

    return Handler


def extract_cookie(raw: str) -> str:
    """从用户贴进来的东西里把 cookie 抠出来。三种都认：

      1) 纯 cookie 串   `_uid=215505229; fid=133138; _d=...`
      2) cURL 命令       `curl 'https://...' -H 'cookie: _uid=...' -b '...'`
      3) 整段请求头      `Cookie: _uid=215505229; fid=133138`

    为什么做这个：DevTools 里「Copy as cURL」比手挑那一行 Cookie 容易得多，
    很多人复制完直接粘过来，那就该能直接用。
    """
    s = (raw or "").strip()
    if not s:
        return ""

    # 1) cURL 的 -b / --cookie
    m = re.search(r"(?:^|\s)(?:-b|--cookie)\s+(['\"])(.+?)\1", s, re.S)
    if m:
        return m.group(2).strip()

    # 2) cURL 的 -H 'cookie: ...' / --header 'Cookie:...'
    m = re.search(r"(?:-H|--header)\s+(['\"])cookie\s*:\s*(.+?)\1", s, re.I | re.S)
    if m:
        return m.group(2).strip()

    # 3) 整段请求头文本里的 Cookie 行
    m = re.search(r"^[ \t]*cookie[ \t]*:[ \t]*(.+)$", s, re.I | re.M)
    if m:
        return m.group(1).strip()

    # 4) 看起来就是 cookie 串本身
    #    判据要严：必须是 k=v;k=v 的形态。否则用户随手复制一条别的 cURL
    #    （比如静态资源、CDN 的 js），URL 里的 ?t=20240131 也带等号，
    #    会被误当成 cookie 塞进请求，然后服务端回一坨 403 HTML，很难排查。
    if "://" in s or re.match(r"^\s*(curl|wget|GET|POST|https?)\b", s, re.I):
        return ""
    if "<" in s or ">" in s:
        return ""
    parts = [p.strip() for p in s.split(";") if "=" in p]
    if parts and all(re.match(r"^[A-Za-z0-9_.\-]+\s*=", p) for p in parts):
        return s
    return ""


def _fetcher(engine: Engine):
    def _f(url: str, headers: dict | None = None):
        st, body, _ = engine.s.request(url, headers=headers or {})
        return st, body
    return _f


def _geocode_forward(text: str, engine: Engine) -> dict:
    """地址 -> GCJ-02 坐标。有高德 key 用高德（准），否则退 Nominatim。"""
    from . import geo
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "地址为空"}
    f = _fetcher(engine)
    key = str(engine.cfg.get("location", {}).get("amapKey") or "")
    if key:
        pt = geo.geocode_amap(text, key, f)
        if pt:
            return {"ok": True, "lat": pt[0], "lon": pt[1], "name": text,
                    "source": "amap", "zoom": 17}
    pt = geo.geocode_osm(text, f)
    if pt:
        g = geo.wgs84_to_gcj02(pt[0], pt[1])
        return {"ok": True, "lat": g[0], "lon": g[1], "name": text,
                "source": "osm", "zoom": 17}
    return {"ok": False, "error": "没找到这个地址"}


def _geocode_reverse(lat: float, lon: float, engine: Engine) -> dict:
    """GCJ-02 坐标 -> 地址文本。"""
    from . import geo
    f = _fetcher(engine)
    key = str(engine.cfg.get("location", {}).get("amapKey") or "")
    if key:
        from urllib.parse import quote as _q
        url = (f"https://restapi.amap.com/v3/geocode/regeo?output=json&key={_q(key)}"
               f"&location={lon:.6f},{lat:.6f}")
        st, body = f(url)
        if st == 200:
            try:
                d = json.loads(body)
                name = str(((d.get("regeocode") or {}).get("formatted_address")) or "")
                if name:
                    return {"ok": True, "name": name, "source": "amap"}
            except Exception:
                pass
    # OSM 只认 WGS-84，先转
    w = geo.gcj02_to_wgs84(lat, lon)
    from urllib.parse import quote as _q
    url = (f"https://nominatim.openstreetmap.org/reverse?format=json&zoom=18"
           f"&lat={w[0]:.6f}&lon={w[1]:.6f}")
    st, body = f(url, {"User-Agent": "cxsign-sentinel/1.0"})
    if st == 200:
        try:
            d = json.loads(body)
            name = str(d.get("display_name") or "")
            if name:
                return {"ok": True, "name": name, "source": "osm"}
        except Exception:
            pass
    return {"ok": False, "error": "地址解析不可用（配一个高德 key 会更准）"}


def _sign_by_id(engine: Engine, active_id: str, kind_key: str = "") -> dict:
    """手动点名签某个活动（面板上的「立即签到」）。"""
    from .protocol import Activity, Kind, classify
    info = engine.fetch_info(active_id)
    act = Activity(active_id=active_id, status=1)
    if info:
        act.course_id = str(info.raw.get("courseId") or "")
        act.class_id = str(info.raw.get("classId") or "")
        act.name = info.name or ""
    kind = classify(info) if info else Kind(key=kind_key or "plain")
    if kind_key:
        kind.key = kind_key
    rec = engine.submit(act, kind)
    return rec.to_dict()


def _tmpdir() -> str:
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "cxsign")
    os.makedirs(d, exist_ok=True)
    return d


class _QuietServer(ThreadingHTTPServer):
    """SSE 长连接一断开就抛 ConnectionResetError，那是正常的，别把日志刷满。"""

    daemon_threads = True

    def handle_error(self, request, client_address):
        import sys as _sys
        exc = _sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve(engine: Engine, bus: EventBus, host: str = "127.0.0.1", port: int = 8848,
          token: str = "") -> ThreadingHTTPServer:
    api = Api(engine, bus, token)
    httpd = _QuietServer((host, port), make_handler(api))
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, name="cxsign-http", daemon=True)
    t.start()
    return httpd


_INDEX_HTML = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>签到哨兵</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#0d1117;color:#e6edf3;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}
.wrap{max-width:640px;margin:0 auto;padding:18px}
h1{font-size:19px;margin:0 0 4px}
.sub{color:#8b949e;font-size:13px;margin-bottom:16px}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px;margin-bottom:12px}
.kv{display:flex;justify-content:space-between;padding:4px 0;font-size:14px}
.kv span:first-child{color:#8b949e}
a.btn{display:inline-block;background:#238636;color:#fff;text-decoration:none;padding:9px 16px;border-radius:8px;font-size:14px;margin-right:8px}
button.btn{display:inline-block;background:#238636;color:#fff;padding:9px 16px;border-radius:8px;font-size:14px;cursor:pointer}
button.btn:active{filter:brightness(1.2)}
textarea{width:100%;box-sizing:border-box;min-height:66px;background:#0d1117;border:1px solid #30363d;
  border-radius:8px;color:#e6edf3;padding:8px 10px;font:12px/1.5 ui-monospace,Menlo,monospace;
  resize:vertical;outline:none}
textarea:focus{border-color:#2f81f7}
#qrDrop{border:2px dashed #30363d;border-radius:10px;padding:18px;text-align:center;
  color:#8b949e;font-size:12.5px;cursor:pointer;transition:border-color .15s}
#qrDrop:hover,#qrDrop:active{border-color:#2f81f7;color:#c9d1d9}
#qrText{flex:1;min-width:0;background:#0d1117;border:1px solid #30363d;border-radius:8px;
  color:#e6edf3;padding:9px 10px;font-size:13px;outline:none}
#qrText:focus{border-color:#2f81f7}
#log{font:12px/1.5 ui-monospace,Menlo,monospace;max-height:280px;overflow:auto;color:#9da7b3;white-space:pre-wrap}
.ok{color:#3fb950}.err{color:#f85149}.warn{color:#d29922}
</style>
<div class="wrap">
<h1>签到哨兵 · 本地控制台</h1>
<div class="sub">引擎在后台轮询，这个页面只是观察窗。</div>
<div class="card" id="status">读取中…</div>
<div class="card" id="loginCard">
  <div style="color:#8b949e;font-size:13px;margin-bottom:6px">登录 —— 贴 Cookie 那一行，或者直接贴「Copy as cURL」的整段命令，都认</div>
  <div style="color:#6e7681;font-size:11.5px;margin-bottom:8px;line-height:1.6">
    ⚠️ 一定要挑 <b style="color:#8b949e">chaoxing.com</b> 的接口请求（域名是 <code>mooc1-api</code> /
    <code>mobilelearn</code> / <code>i.chaoxing.com</code>）。<br>
    静态资源、CDN（xuexi365.com）、.js / .png 都不带 cookie，复制那些没用。
  </div>
  <textarea id="ck" placeholder="_uid=215505229; fid=133138; _d=...; uf=...&#10;或者 curl 'https://mooc1-api.chaoxing.com/...' -H 'cookie: _uid=...'"></textarea>
  <div style="display:flex;gap:8px;margin-top:8px">
    <button class="btn" id="loginBtn" style="border:0">导入并验证</button>
    <button class="btn" id="pollBtn" style="border:0;background:#21262d">立刻轮询一轮</button>
  </div>
  <div id="loginMsg" style="font-size:12.5px;color:#8b949e;margin-top:8px;word-break:break-all"></div>
</div>
<div class="card"><a class="btn" href="/map">地图选点</a><a class="btn" href="/api/records">签到记录</a></div>
<div class="card" id="qrCard">
  <div style="color:#8b949e;font-size:13px;margin-bottom:6px">二维码签到 —— 把老师那张码交给引擎</div>
  <div id="pendingList" style="margin-bottom:8px"></div>
  <div id="qrDrop">点这里选图片 &nbsp;·&nbsp; 或把图片拖进来 &nbsp;·&nbsp; 或 Ctrl+V 粘贴</div>
  <input type="file" id="qrFile" accept="image/*" hidden>
  <div style="display:flex;gap:8px;margin-top:8px">
    <input id="qrText" placeholder="也可以直接粘二维码里的链接 / SIGNIN: 文本">
    <button class="btn" id="qrSend" style="flex:none">提交文本</button>
  </div>
  <div id="qrMsg" style="font-size:12.5px;color:#8b949e;margin-top:8px;word-break:break-all"></div>
</div>
<div class="card"><div style="color:#8b949e;font-size:13px;margin-bottom:6px">实时事件</div><div id="log"></div></div>
</div>
<script>
const $=s=>document.querySelector(s);
const TOKEN="__TOKEN__";
const TQ=(p)=>(TOKEN?p+(p.includes('?')?'&':'?')+'token='+encodeURIComponent(TOKEN):p);
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function status(){
  try{
    const r=await fetch(TQ('/api/status'));const j=await r.json();
    const d=j.data||{};
    $('#status').innerHTML=[
      ['登录 uid',d.login?.uid||'-'],['学校 fid',d.login?.fid||'-'],
      ['课程/班级',d.courses],['已签到',d.signed],
      ['待取码',(d.pending||[]).length],['轮询轮次',d.stats?.polls],
      ['选点',d.point?d.point.map(x=>x.toFixed(6)).join(', '):'未设置'],
      ['照片',d.photo?d.photo.split(/[\\\\/]/).pop():'未设置']
    ].map(([k,v])=>`<div class="kv"><span>${k}</span><span>${esc(v)}</span></div>`).join('');
  }catch(e){$('#status').textContent='引擎无响应'}
}
status();setInterval(status,4000);

async function doLogin(){
  const ck=document.getElementById('ck').value.trim();
  const m=document.getElementById('loginMsg');
  if(!ck){m.textContent='先把 cookie 贴进来';return;}
  m.textContent='验证中…';
  try{
    const r=await fetch(TQ('/api/login'),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({cookie:ck})});
    const j=await r.json();
    m.textContent = j.ok
      ? '✅ '+j.message+'  uid='+(j.uid||'-')+'  fid='+(j.fid||'-')+'  导入'+j.imported+'条'
      : '❌ '+(j.message||j.error||'失败');
    status();
  }catch(e){m.textContent='❌ 引擎无响应';}
}
async function doPoll(){
  const m=document.getElementById('loginMsg');
  m.textContent='轮询中…';
  try{
    const r=await fetch(TQ('/api/poll'),{method:'POST'});
    const j=await r.json();
    m.textContent='轮询完成，本轮处理 '+(j.results||[]).length+' 个';
    status();
  }catch(e){m.textContent='❌ 引擎无响应';}
}
document.getElementById('loginBtn').onclick=doLogin;
document.getElementById('pollBtn').onclick=doPoll;

/* ---------------- 投二维码 ---------------- */
const qrMsg=document.getElementById('qrMsg');
const qrDrop=document.getElementById('qrDrop');

function qrSay(t,cls){qrMsg.textContent=t;qrMsg.className=cls||'';}

async function sendQrImage(file){
  qrSay('解码中…');
  try{
    const buf=await file.arrayBuffer();
    const r=await fetch(TQ('/api/qr'),{method:'POST',headers:{'Content-Type':'image/*'},body:buf});
    const j=await r.json();
    if(!j.ok){qrSay('❌ '+(j.error||'失败'),'err');return;}
    const n=(j.results||[]).length;
    if(n===0){qrSay('图片里没解出能用的码（或者这张码已经签过了）','warn');}
    else{
      const r0=j.results[0];
      qrSay((r0.state==='SIGNED'?'✅ ':'❌ ')+(r0.name||'')+' · '+(r0.message||''),
            r0.state==='SIGNED'?'ok':'err');
    }
    refreshPending();status();
  }catch(e){qrSay('❌ 上传失败：'+e,'err');}
}

async function sendQrText(){
  const t=document.getElementById('qrText').value.trim();
  if(!t){qrSay('先粘点东西进来');return;}
  qrSay('提交中…');
  try{
    const r=await fetch(TQ('/api/qr'),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:t})});
    const j=await r.json();
    const n=(j.results||[]).length;
    if(n===0){qrSay('没匹配到进行中的签到（可能已签过或码不对）','warn');}
    else{const r0=j.results[0];
      qrSay((r0.state==='SIGNED'?'✅ ':'❌ ')+(r0.name||'')+' · '+(r0.message||''),
            r0.state==='SIGNED'?'ok':'err');}
    refreshPending();status();
  }catch(e){qrSay('❌ '+e,'err');}
}

qrDrop.onclick=()=>document.getElementById('qrFile').click();
document.getElementById('qrFile').onchange=e=>{
  const f=e.target.files&&e.target.files[0]; if(f) sendQrImage(f);
};
qrDrop.ondragover=e=>{e.preventDefault();qrDrop.style.borderColor='#2f81f7';};
qrDrop.ondragleave=()=>{qrDrop.style.borderColor='#30363d';};
qrDrop.ondrop=e=>{
  e.preventDefault();qrDrop.style.borderColor='#30363d';
  const f=e.dataTransfer.files&&e.dataTransfer.files[0]; if(f) sendQrImage(f);
};
document.addEventListener('paste',e=>{
  const items=(e.clipboardData&&e.clipboardData.items)||[];
  for(const it of items){
    if(it.type && it.type.indexOf('image')===0){
      const f=it.getAsFile(); if(f){sendQrImage(f);e.preventDefault();return;}
    }
  }
});
document.getElementById('qrSend').onclick=sendQrText;

/* 等码列表：让用户知道引擎在等哪几个活动 */
async function refreshPending(){
  try{
    const r=await fetch(TQ('/api/records'));
    const j=await r.json();
    const p=j.pending||{};
    const keys=Object.keys(p);
    const box=document.getElementById('pendingList');
    if(!keys.length){box.innerHTML='<span style="font-size:12px;color:#6e7681">当前没有等码的签到</span>';return;}
    box.innerHTML=keys.map(k=>{
      const o=p[k]||{};
      return `<div style="font-size:12px;color:#d29922;padding:3px 0">⏳ ${esc(o.name||k)} · activeId ${k}</div>`;
    }).join('');
  }catch(e){}
}
refreshPending();setInterval(refreshPending,8000);

const es=new EventSource(TQ('/api/events'));
function add(ev){
  const cls=ev.level==='ok'?'ok':ev.level==='error'?'err':ev.level==='warn'?'warn':'';
  const t=new Date((ev.ts||0)*1000).toLocaleTimeString();
  const el=document.createElement('div');el.className=cls;
  el.textContent=`${t}  ${ev.title||''}`;
  $('#log').appendChild(el);$('#log').scrollTop=1e9;
}
es.onmessage=e=>{try{add(JSON.parse(e.data))}catch(_){}};
</script>
"""


__all__ = ["serve", "EventBus", "Api", "make_handler"]
