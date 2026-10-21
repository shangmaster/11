"""解析 Reqable 导出的 HAR：先给概览，再深挖关键请求。"""

import json
import os
import re
import sys
from collections import Counter

HAR = (sys.argv[1] if len(sys.argv) > 1 else
       r"C:\Users\s\Documents\xwechat_files\wxid_3mokr2luok8422_6525\msg\file\2026-10\mmbiz.qpic.cn_2026_10_21_13_41_38.har")

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core", "data", "har")
os.makedirs(OUT_DIR, exist_ok=True)


def load():
    with open(HAR, "r", encoding="utf-8", errors="replace") as fh:
        return json.load(fh)


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else url


def body_text(obj) -> str:
    if not isinstance(obj, dict):
        return ""
    t = obj.get("text")
    if isinstance(t, str):
        return t
    return ""


def main() -> int:
    data = load()
    entries = (data.get("log") or {}).get("entries") or []
    print(f"HAR 条目数: {len(entries)}\n")

    hosts = Counter(host_of(e.get("request", {}).get("url", "")) for e in entries)
    print("按域名统计：")
    for h, n in hosts.most_common(30):
        print(f"  {n:>4}  {h}")

    print("\n" + "=" * 80)
    print("全部请求一览（method status size host/path）")
    print("=" * 80)
    for i, e in enumerate(entries):
        req = e.get("request") or {}
        res = e.get("response") or {}
        url = req.get("url", "")
        path = re.sub(r"https?://[^/]+", "", url)
        size = (res.get("content") or {}).get("size") or 0
        print(f"  #{i:<4} {req.get('method',''):<7} {res.get('status','')} "
              f"{size:>8}  {host_of(url)}{path[:96]}")

    # ---------- 关键请求 ----------
    keys = ("upload", "stuSignajax", "objectid", "photoResult", "signajax",
            "ac_event", "sign/qrcode", "preSign", "newsign")
    print("\n" + "=" * 80)
    print("命中的关键请求")
    print("=" * 80)
    for i, e in enumerate(entries):
        req = e.get("request") or {}
        res = e.get("response") or {}
        url = req.get("url", "")
        req_body = body_text(req.get("postData"))
        res_body = body_text(res.get("content"))
        blob = (url + "\n" + req_body + "\n" + res_body).lower()
        hits = [k for k in keys if k.lower() in blob]
        if not hits:
            continue
        print(f"\n{'='*80}")
        print(f"#{i}  {req.get('method')} {res.get('status')}  hits={hits}")
        print(f"URL: {url}")
        print(f"--- 请求头 ---")
        for h in (req.get("headers") or []):
            n = (h.get("name") or "")
            if n.lower() in ("cookie", "content-type", "user-agent", "referer",
                             "authorization", "x-requested-with", "token"):
                v = (h.get("value") or "")
                print(f"  {n}: {v[:200]}")
        if req_body:
            print(f"--- 请求体 ({len(req_body)} 字符) ---")
            print("  " + req_body[:1200].replace("\n", "\n  "))
        if res_body:
            print(f"--- 响应体 ({len(res_body)} 字符) ---")
            print("  " + res_body[:1200].replace("\n", "\n  "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
