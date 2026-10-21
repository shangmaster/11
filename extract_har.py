"""从 HAR 里精确提取「拍照签到成功」那条链路的完整内容。"""

import json
import os
import re
import sys

HAR = (sys.argv[1] if len(sys.argv) > 1 else
       r"C:\Users\s\Documents\xwechat_files\wxid_3mokr2luok8422_6525\msg\file\2026-10\mmbiz.qpic.cn_2026_10_21_13_41_38.har")

WANT = [27, 30, 31, 20, 29, 22, 44, 45]


def body_text(obj) -> str:
    if not isinstance(obj, dict):
        return ""
    t = obj.get("text")
    return t if isinstance(t, str) else ""


def dump(e, idx):
    req = e.get("request") or {}
    res = e.get("response") or {}
    url = req.get("url", "")
    print("\n" + "=" * 78)
    print(f"#{idx}  {req.get('method')}  {res.get('status')}")
    print("=" * 78)
    print(f"URL: {url}")

    print("\n[请求头]")
    for h in (req.get("headers") or []):
        n, v = h.get("name", ""), h.get("value", "")
        if n.lower() in ("cookie",):
            print(f"  {n}: {v[:400]}")
        else:
            print(f"  {n}: {v[:300]}")

    qs = req.get("queryString") or []
    if qs:
        print("\n[查询参数]")
        for q in qs:
            print(f"  {q.get('name')} = {str(q.get('value'))[:300]}")

    pd = req.get("postData") or {}
    if pd:
        print(f"\n[请求体] mimeType={pd.get('mimeType')}")
        for p in (pd.get("params") or []):
            name = p.get("name")
            val = p.get("value")
            fn = p.get("fileName")
            if fn:
                print(f"  {name} = <文件 {fn}, "
                      f"{len(str(val or ''))} 字符>")
            else:
                print(f"  {name} = {str(val)[:400]}")
        raw = body_text(pd)
        if raw:
            print(f"\n[请求体原文 {len(raw)} 字符]")
            print("  " + raw[:2500].replace("\n", "\n  "))

    content = res.get("content") or {}
    rt = body_text(content)
    print(f"\n[响应] mimeType={content.get('mimeType')} size={content.get('size')}")
    if rt:
        enc = content.get("encoding")
        prefix = f"(base64, {len(rt)} 字符) " if enc == "base64" else ""
        print(f"  {prefix}{rt[:1500]}")
    # 响应头
    for h in (res.get("headers") or []):
        n = h.get("name", "").lower()
        if n in ("content-type", "set-cookie", "location"):
            print(f"  << {h.get('name')}: {str(h.get('value'))[:200]}")


def main() -> int:
    with open(HAR, "r", encoding="utf-8", errors="replace") as fh:
        data = json.load(fh)
    entries = (data.get("log") or {}).get("entries") or []
    print(f"HAR 条目 {len(entries)}")

    for i in WANT:
        if i < len(entries):
            dump(entries[i], i)

    # 再扫一遍：所有含 objectid / photoResult 的地方
    print("\n\n" + "#" * 78)
    print("# 全 HAR 扫描 objectid / photoResult / upload")
    print("#" * 78)
    for i, e in enumerate(entries):
        req = e.get("request") or {}
        res = e.get("response") or {}
        blob = json.dumps({"u": req.get("url"),
                           "q": req.get("queryString"),
                           "p": req.get("postData"),
                           "r": (res.get("content") or {}).get("text")},
                          ensure_ascii=False)
        for kw in ("photoResult", "objectid", "objectId", "upload"):
            if kw in blob:
                print(f"\n#{i} {req.get('method')} {req.get('url')[:100]}  <- {kw}")
                for m in re.finditer(r'.{80}' + kw + r'.{160}', blob, re.I):
                    print("   " + m.group(0)[:260].replace("\\n", " "))
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
