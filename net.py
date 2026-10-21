"""HTTP 会话层：只用标准库，手机端（Termux / 打包成 APK 的后端进程）也能直接跑。

为什么不用 requests：
  · Termux 上 pip 装 requests 要编译（慢、容易失败）
  · 手机壳里跑的是同一个脚本，依赖越少越稳
  · 需要的功能只有 cookie 持久化 + multipart，标准库够
"""

from __future__ import annotations

import base64
import http.cookiejar as cookiejar
import json
import mimetypes
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .protocol import (
    APP_UA, HOST_MOOC, HOST_PASSPORT,
    build_course_list_url,
)

# --------------------------------------------------------------------------
# Cookie
# --------------------------------------------------------------------------

COOKIE_KEYS_OF_INTEREST = ("_uid", "fid", "_d", "UID", "uf", "_uf", "p_auth_token", "cx_p_token")


class Session:
    """一个学习通账号的会话。

    cookie 可以从三种途径进来：
      · CookieJar 文件（save/load）
      · 浏览器导出的 `name=value; name=value` 字符串
      · 直接构造 dict
    """

    def __init__(self, cookie_file: str | None = None, proxy: str | None = None,
                 timeout: float = 15.0, ua: str = APP_UA, verify_tls: bool = True):
        self.timeout = timeout
        self.ua = ua
        self.jar = cookiejar.CookieJar()
        self.cookie_file = cookie_file
        self.proxy = proxy
        self._extra_headers: dict[str, str] = {}
        self.uid = ""
        self.fid = ""
        self.uname = ""
        self._fid_name = ""

        handlers: list[urllib.request.BaseHandler] = [
            urllib.request.HTTPCookieProcessor(self.jar),
        ]
        ctx = None if verify_tls else ssl._create_unverified_context()  # noqa: SLF001
        if ctx is not None:
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*handlers)

        if cookie_file and os.path.exists(cookie_file):
            self.load(cookie_file)

    # ---------------- cookie 读写 ----------------

    def load(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return False
        if isinstance(data, dict) and "cookies" in data:
            self.uid = str(data.get("uid") or "")
            self.fid = str(data.get("fid") or "")
            self.uname = str(data.get("uname") or "")
            rows = data.get("cookies") or []
        else:
            rows = data if isinstance(data, list) else []
        for row in rows:
            try:
                c = cookiejar.Cookie(
                    version=0, name=row["name"], value=row.get("value", ""),
                    port=None, port_specified=False,
                    domain=row.get("domain", ".chaoxing.com"), domain_specified=True,
                    domain_initial_dot=True, path=row.get("path", "/"),
                    path_specified=True, secure=bool(row.get("secure", True)),
                    expires=row.get("expires") or None, discard=False,
                    comment=None, comment_url=None, rest={}, rfc2109=False,
                )
                self.jar.set_cookie(c)
            except Exception:
                continue
        self._sync_ids_from_jar()
        return bool(rows)

    def save(self, path: str | None = None) -> str:
        path = path or self.cookie_file
        if not path:
            return ""
        rows = []
        for c in self.jar:
            rows.append({
                "name": c.name, "value": c.value,
                "domain": c.domain, "path": c.path,
                "secure": c.secure, "expires": c.expires,
            })
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"uid": self.uid, "fid": self.fid, "uname": self.uname,
                       "savedAt": int(time.time()), "cookies": rows}, fh,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return path

    def cookie_string(self) -> str:
        return "; ".join(f"{c.name}={c.value}" for c in self.jar)

    def set_cookies(self, raw: str | dict) -> int:
        """从浏览器导出的 cookie 字符串导入。返回导入条数。"""
        if isinstance(raw, dict):
            items = list(raw.items())
        else:
            items = []
            for part in str(raw).replace("\n", ";").split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                k, v = part.split("=", 1)
                items.append((k.strip(), v.strip()))
        n = 0
        for k, v in items:
            if not k:
                continue
            for domain in (".chaoxing.com", ".edu.cn"):
                try:
                    c = cookiejar.Cookie(
                        version=0, name=k, value=v, port=None, port_specified=False,
                        domain=domain, domain_specified=True, domain_initial_dot=True,
                        path="/", path_specified=True, secure=True, expires=None,
                        discard=False, comment=None, comment_url=None, rest={},
                        rfc2109=False,
                    )
                    self.jar.set_cookie(c)
                    n += 1
                    break
                except Exception:
                    continue
        self._sync_ids_from_jar()
        return n

    def _sync_ids_from_jar(self) -> None:
        vals = {c.name: c.value for c in self.jar}
        if not self.uid:
            self.uid = vals.get("_uid") or vals.get("UID") or ""
        if not self.fid:
            self.fid = vals.get("fid") or vals.get("FID") or ""
        # 部分账号只有 uf 里带 uid（形如 `xxx_姓名`），剥出来
        if not self.uid and vals.get("uf"):
            self.uid = vals["uf"].split("_", 1)[0]
        # cookie 里 fid 常跟在 _uid 后面，也可能是独立域名的 cookie

    # ---------------- 请求 ----------------

    def headers(self, extra: dict | None = None) -> dict:
        h = {
            "User-Agent": self.ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "com.chaoxing.mobile",
        }
        h.update(self._extra_headers)
        if extra:
            h.update(extra)
        return h

    def request(self, url: str, method: str = "GET", data: bytes | None = None,
                headers: dict | None = None, follow: bool = True) -> tuple[int, str, str]:
        """返回 (status, text, final_url)。never raises —— 网络错误折成 status=0。"""
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=self.headers(headers))
        opener = self.opener
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                body = resp.read()
                return resp.status, _decode(body, resp.headers), resp.geturl()
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            return e.code, _decode(body, e.headers), url
        except Exception as e:                       # noqa: BLE001
            return 0, f"__network_error__:{e}", url

    def get_json(self, url: str, headers: dict | None = None) -> tuple[Any, int, str]:
        status, text, final = self.request(url, headers=headers)
        return _maybe_json(text), status, final

    def request_bytes(self, url: str, method: str = "GET", data: bytes | None = None,
                      headers: dict | None = None) -> tuple[int, bytes, str]:
        """要二进制的时候用这个（图片 / 二维码 / 附件）。

        request() 会把响应体按文本解码，拿二进制会直接坏掉 —— 下载
        /sign/qrcode 的二维码图片时踩过这个坑，jpg 被解成乱码。
        """
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=self.headers(headers))
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.status, resp.read(), resp.geturl()
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            return e.code, body, url
        except Exception as e:                       # noqa: BLE001
            return 0, str(e).encode(), url

    def post_form(self, url: str, fields: dict[str, str],
                  headers: dict | None = None) -> tuple[int, str, str]:
        body = urllib.parse.urlencode(fields).encode()
        h = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if headers:
            h.update(headers)
        return self.request(url, method="POST", data=body, headers=h)

    def post_multipart(self, url: str, fields: dict[str, str], file_field: str,
                       filename: str, content: bytes,
                       content_type: str | None = None,
                       headers: dict | None = None) -> tuple[int, str, str]:
        boundary = "----CxSign" + uuid.uuid4().hex
        ctype = content_type or (mimetypes.guess_type(filename)[0] or "image/jpeg")
        chunks: list[bytes] = []
        for k, v in fields.items():
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
            chunks.append(str(v).encode("utf-8"))
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode()
        )
        chunks.append(f"Content-Type: {ctype}\r\n\r\n".encode())
        chunks.append(content)
        chunks.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        h = {"Content-Type": f"multipart/form-data; boundary={boundary}",
             "Content-Length": str(len(body))}
        if headers:
            h.update(headers)
        return self.request(url, method="POST", data=body, headers=h)

    # ---------------- 登录态 ----------------

    def probe_login(self) -> tuple[bool, str]:
        """校验收登录是否还有效。返回 (ok, 说明)。

        判据：课程列表接口要么返回 result=1 的 JSON，要么 302 到 passport 登录页。
        不用 i.chaoxing.com/base，因为那个页面未登录也可能 200。
        """
        url = build_course_list_url(HOST_MOOC)
        status, text, final = self.request(url)
        if status == 0:
            return False, f"网络不可达: {text[:80]}"
        if "passport" in (final or "") or "/mlogin" in (final or ""):
            return False, "被重定向到登录页，cookie 已失效"
        data = _maybe_json(text)
        if isinstance(data, dict) and data.get("result") == 1:
            self._sync_ids_from_jar()
            return True, "登录有效"
        if isinstance(data, dict) and data.get("result") is False:
            return False, str(data.get("msg") or "服务端拒绝（可能 cookie 不全）")
        head = (text or "").strip()
        # 没登录时有些接口会直接甩一坨 HTML 403 页面回来，别把它当错误信息展示
        if head.startswith("<"):
            return False, "服务端返回了网页而不是数据 —— cookie 是空的或已失效"
        if status == 403:
            return False, "HTTP 403：cookie 无效，服务端直接拒绝"
        return False, f"未拿到课程列表: {head[:100].replace(chr(10), ' ')}"


# --------------------------------------------------------------------------
# 密码登录（可选；手机上更推荐直接导入 cookie）
# --------------------------------------------------------------------------

def password_login(session: Session, uname: str, password: str,
                   fid: str = "", refer: str = "https://i.chaoxing.com") -> tuple[bool, str]:
    """passport2 明文登录。若账号开了二次验证会失败，这时走 cookie 导入。"""
    url = f"{HOST_PASSPORT}/fanyalogin"
    fields = {
        "fid": fid or "-1",
        "uname": uname,
        "password": password,
        "refer": refer,
        "t": str(int(time.time() * 1000)),
        "forbidotherlogin": "1",
        "validate": "",
        "doubleFactorLogin": "0",
        "independentId": "0",
    }
    status, text, _ = session.post_form(url, fields)
    if status == 0:
        return False, f"网络不可达: {text[:80]}"
    data = _maybe_json(text)
    if not isinstance(data, dict):
        return False, f"登录响应不是 JSON: {text[:120]}"
    if data.get("status") is True:
        session._sync_ids_from_jar()   # noqa: SLF001
        if not session.uname:
            session.uname = uname
        return True, "登录成功"
    msg = str(data.get("msg") or data.get("message") or "登录失败")
    if "验证码" in msg or "captcha" in msg.lower():
        return False, f"{msg}（需要在官方页面登录一次后导出 cookie）"
    return False, msg


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

def _decode(body: bytes, headers) -> str:
    charset = "utf-8"
    try:
        charset = headers.get_content_charset() or "utf-8"
    except Exception:
        pass
    for enc in (charset, "utf-8", "gbk"):
        try:
            return body.decode(enc, "replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def _maybe_json(text: str):
    s = (text or "").strip()
    if not s or s[0] not in "{[":
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


__all__ = ["Session", "password_login", "COOKIE_KEYS_OF_INTEREST", "b64"]
