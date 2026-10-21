"""把 getPPTActiveInfo 里所有可能有用的字段值打出来（脱敏，不打印 cookie）。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session                        # noqa: E402
from cxsign.protocol import build_active_info_url     # noqa: E402

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")

WANT = [
    # 位置相关 —— 如果这些有值，位置签到就不用地理编码了
    "latitude", "longitude",
    "locationLatitude", "locationLongitude",
    "locationLatitude_gd", "locationLongitude_gd",
    "locationRange", "locationText", "ifopenAddress", "ifgetrange", "region",
    # 二维码相关
    "ewmRefreshTime", "ewnCtime1", "ewnCtime2", "ifrefreshewm", "viewPicPath",
    # 内容 / 配置 —— 可能内嵌二维码信息
    "content", "iphoneContent", "configJson", "editconfig",
    "jurl", "url", "dpurl",
    # 类型
    "activeSort", "otherId", "oldOtherId", "signCode", "numberCount",
    "status", "nowTime", "starttime", "endtime", "lateEndTime",
]


def main() -> int:
    aids = sys.argv[1:]
    if not aids:
        print("用法: probe_info.py <activeId> [activeId...]")
        return 2

    s = Session(cookie_file=COOKIE)
    for aid in aids:
        data, st, _ = s.get_json(build_active_info_url(aid))
        d = (data or {}).get("data") or {}
        print("=" * 74)
        print(f"activeId = {aid}    HTTP {st}    字段数 {len(d)}")
        print("=" * 74)
        for k in WANT:
            if k not in d:
                continue
            v = d[k]
            if v is None or v == "" or v == []:
                print(f"  {k:<22} = {v!r}  (空)")
                continue
            if isinstance(v, (dict, list)):
                txt = json.dumps(v, ensure_ascii=False)
                print(f"  {k:<22} = {txt[:400]}")
            else:
                sv = str(v)
                print(f"  {k:<22} = {sv[:400]}")

        # 扫一遍所有字段，看有没有哪个值里藏着 32 位 hex / 二维码链接
        print("\n  -- 全字段扫描（找 32 位 hex 和二维码链接）--")
        blob = json.dumps(d, ensure_ascii=False)
        import re
        for m in re.finditer(r'"(\w+)"\s*:\s*"([0-9A-F]{32})"', blob):
            print(f"    ★ {m.group(1)} = {m.group(2)}  (32 位 hex)")
        for m in re.finditer(r'(https?://[^"\s]*widget/sign[^"\s]*)', blob):
            print(f"    ★ 二维码链接: {m.group(1)[:160]}")
        if "widget/sign" not in blob and not re.search(r'"[0-9A-F]{32}"', blob):
            print("    没有")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
