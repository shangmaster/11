"""推送：签到结果要能在手机上弹出来，引擎跑在后台时才有人知道。

支持四个都免费、都不需要备案的通道：
  · Bark      iOS 首选（App Store 装 Bark，拿 key）
  · ntfy      安卓/桌面都能用，支持自建
  · PushPlus  微信推送
  · 企业微信机器人 webhook
任填其一即可，全空就是只写日志。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

UA = "cxsign-sentinel/1.0"


def _post(url: str, data: bytes | None = None, headers: dict | None = None,
          timeout: float = 8.0) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:300]
    except Exception as e:                          # noqa: BLE001
        return 0, str(e)[:200]


class Notifier:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        self.enabled = any(self.cfg.get(k) for k in ("bark", "ntfy", "pushplus", "wecom"))
        self._last: dict[str, float] = {}

    def send(self, title: str, body: str = "", level: str = "info", url: str = "") -> list[str]:
        """返回每条通道的结果说明。level: info / ok / error。"""
        if not self.enabled:
            return []
        # 同类消息 3 秒内合并，避免轮询把手机轰爆
        key = f"{level}:{title}"
        now = time.time()
        if now - self._last.get(key, 0) < 3:
            return []
        self._last[key] = now

        results: list[str] = []
        if self.cfg.get("bark"):
            results.append("bark:" + self._bark(title, body, level, url))
        if self.cfg.get("ntfy"):
            results.append("ntfy:" + self._ntfy(title, body, level, url))
        if self.cfg.get("pushplus"):
            results.append("pushplus:" + self._pushplus(title, body))
        if self.cfg.get("wecom"):
            results.append("wecom:" + self._wecom(title, body, url))
        return results

    # ---------------- 各通道 ----------------

    def _bark(self, title: str, body: str, level: str, url: str) -> str:
        base = str(self.cfg["bark"]).rstrip("/")
        icon = {"ok": "✅", "error": "❌"}.get(level, "ℹ️")
        path = f"{base}/{urllib.parse.quote(icon + title)}/{urllib.parse.quote(body or ' ')}"
        qs = {"group": "签到哨兵", "isArchive": "1"}
        if level == "error":
            qs["level"] = "timeSensitive"
        if url:
            qs["url"] = url
        status, text = _post(path + "?" + urllib.parse.urlencode(qs))
        return f"{status}"

    def _ntfy(self, title: str, body: str, level: str, url: str) -> str:
        topic_url = str(self.cfg["ntfy"]).rstrip("/")
        if not topic_url.startswith("http"):
            topic_url = "https://ntfy.sh/" + topic_url
        headers = {
            "Title": _ascii_header(title),
            "Priority": "high" if level == "error" else "default",
            "Tags": {"ok": "white_check_mark", "error": "x"}.get(level, "information_source"),
        }
        if url:
            headers["Click"] = url
        status, _ = _post(topic_url, (body or title).encode("utf-8"), headers)
        return f"{status}"

    def _pushplus(self, title: str, body: str) -> str:
        payload = json.dumps({
            "token": self.cfg["pushplus"], "title": title,
            "content": body or title, "template": "txt",
        }).encode()
        status, _ = _post("https://www.pushplus.plus/send", payload,
                          {"Content-Type": "application/json"})
        return f"{status}"

    def _wecom(self, title: str, body: str, url: str) -> str:
        text = f"**{title}**\n{body}"
        if url:
            text += f"\n[打开]({url})"
        payload = json.dumps({"msgtype": "markdown",
                              "markdown": {"content": text}}).encode()
        status, _ = _post(str(self.cfg["wecom"]), payload,
                          {"Content-Type": "application/json"})
        return f"{status}"


def _ascii_header(s: str) -> str:
    """ntfy 的 header 只能是 ASCII（RFC 7230），中文标题退化处理。"""
    try:
        s.encode("ascii")
        return s
    except UnicodeEncodeError:
        return urllib.parse.quote(s)


__all__ = ["Notifier"]
