"""探测：老师发签到后，通知接口里有没有二维码图片（这是自动取码的最后一条路）。"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session  # noqa: E402

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")

URLS = [
    "https://notice.chaoxing.com/pc/notice/getNoticeList?pageSize=50&page=1",
    "https://notice.chaoxing.com/pc/notice/getNoticeList?pageSize=50&page=1&type=1",
]


def walk(obj, path="", out=None):
    """把 JSON 里所有字符串值展开成 (路径, 值)。"""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk(v, f"{path}.{k}" if path else k, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk(v, f"{path}[{i}]", out)
    elif isinstance(obj, str):
        out.append((path, obj))
    return out


def main() -> int:
    target_aids = sys.argv[1:]

    s = Session(cookie_file=COOKIE)
    print(f"uid={s.uid} fid={s.fid}")

    for url in URLS:
        st, body, _ = s.request(url)
        print("\n" + "=" * 74)
        print(f"{url}   HTTP {st}   {len(body)} 字节")
        print("=" * 74)
        if st != 200 or not body.startswith("{"):
            print("  非 JSON，跳过")
            continue

        try:
            data = json.loads(body)
        except Exception as e:
            print(f"  解析失败: {e}")
            continue

        flat = walk(data, "", [])
        print(f"  展平后 {len(flat)} 个字符串字段")

        # 1) 有没有提到 target activeId
        for aid in target_aids:
            hits = [(p, v) for p, v in flat if aid in v]
            print(f"\n  -- 提到 activeId {aid} 的字段：{len(hits)} 个 --")
            for p, v in hits[:8]:
                print(f"    {p} = {v[:220]}")

        # 2) 有没有跟签到有关的东西
        sign_hits = [(p, v) for p, v in flat
                     if "签到" in v or "sign" in v.lower() or "ewm" in v.lower()]
        print(f"\n  -- 含「签到/sign/ewm」的字段：{len(sign_hits)} 个 --")
        for p, v in sign_hits[:12]:
            print(f"    {p} = {v[:220]}")

        # 3) 有没有图片 URL（二维码常常以图片形式推送）
        img_hits = [(p, v) for p, v in flat
                    if re.search(r'https?://[^"\s]+\.(png|jpe?g|gif)', v, re.I)
                    and ("sign" in v.lower() or "ewm" in v.lower()
                         or "notice" in v.lower() or "p.ananas" in v)]
        print(f"\n  -- 图片 URL：{len(img_hits)} 个（前 12 条）--")
        for p, v in img_hits[:12]:
            print(f"    {p} = {v[:200]}")

        # 4) 附件结构（老师发签到会带 attachment）
        notices = data.get("notices") or {}
        lst = notices.get("list") or []
        print(f"\n  -- 通知条数 {len(lst)} --")
        for n in lst[:10]:
            title = n.get("title") or n.get("content") or ""
            att = n.get("attachment")
            print(f"    · {str(title)[:60]}")
            if att:
                print(f"      attachment: {str(att)[:300]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
