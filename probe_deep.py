"""深挖两条线索：

1. /widget/sign/index?activeId=X 返回了 16.5KB —— 这是什么页面？里面有没有 enc？
2. /sign/produceSignView 返回「签到活动不存在」（业务错误，不是 500）
   => 接口本身可用，只是 tid 传错了。活动详情里有 pActiveId / parentid /
      realActiveId / id 几个候选，逐个试。
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session                        # noqa: E402
from cxsign.protocol import HOST_MOBILE, build_active_info_url  # noqa: E402

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")
OUT = os.path.join(os.path.dirname(__file__), "..", "core", "data", "widget_sign.html")


def dump_page(body: str, label: str) -> None:
    print(f"\n  ---- {label}  {len(body)} 字节 ----")
    low = body.lower()

    # 关键词分布
    for kw in ("enc", "ewm", "signin", "activeid", "二维码", "签到", "已结束", "失败"):
        n = low.count(kw.lower())
        if n:
            print(f"    '{kw}' 出现 {n} 次")

    # JS 变量
    print("    -- JS 变量 --")
    found_var = False
    for m in re.finditer(
        r"(?:var|let|const)\s+(\w+)\s*=\s*(?:['\"]([^'\"]{0,120})['\"]|([-\d.]+|true|false))",
        body,
    ):
        name = m.group(1)
        val = m.group(2) if m.group(2) is not None else m.group(3)
        if name.lower() in ("enc", "activeid", "uid", "fid", "apptype") or "enc" in name.lower():
            print(f"      ★ {name} = {val}")
            found_var = True
    if not found_var:
        print("      （没有 enc 相关的）")

    # 32 位 hex
    hexes = set(re.findall(r"\b[0-9A-F]{32}\b", body))
    if hexes:
        print(f"    -- 32 位 hex: {list(hexes)[:6]}")
    else:
        print("    -- 没有 32 位 hex")

    # 页面标题 / 关键文案
    for pat in (r"<title[^>]*>(.*?)</title>", r"class=\"[^\"]*tips?[^\"]*\"[^>]*>([^<]{2,60})<"):
        for m in re.finditer(pat, body, re.S | re.I):
            txt = re.sub(r"\s+", " ", m.group(1)).strip()
            if txt:
                print(f"    文案: {txt[:80]}")

    # 首屏片段
    text = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    print(f"    可见文字: {text[:260]}")


def main() -> int:
    aids = [a for a in sys.argv[1:] if not a.startswith("-")] or ["2000176022454"]
    s = Session(cookie_file=COOKIE)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    for aid in aids:
        print("=" * 74)
        print(f"activeId = {aid}")
        print("=" * 74)

        # ---------- 1. widget/sign/index ----------
        for path in (f"/widget/sign/index?activeId={aid}&enc=",
                     f"/widget/sign/index?activeId={aid}"):
            st, body, final = s.request(HOST_MOBILE + path)
            print(f"\n[1] {path}  HTTP {st}  {len(body)}B  最终 {final[:80]}")
            if st == 200 and body:
                with open(OUT, "w", encoding="utf-8") as fh:
                    fh.write(body)
                print(f"    已存到 {OUT}")
                dump_page(body, "widget/sign/index")

        # ---------- 2. produceSignView 换各种 tid ----------
        data, st2, _ = s.get_json(build_active_info_url(aid))
        d = (data or {}).get("data") or {}
        cands = {
            "activeId": aid,
            "id": d.get("id"),
            "pActiveId": d.get("pActiveId"),
            "parentid": d.get("parentid"),
            "realActiveId": d.get("realActiveId"),
            "oldActiveId": d.get("oldActiveId"),
            "pptPlanId": d.get("pptPlanId"),
            "zhjsid": d.get("zhjsid"),
        }
        print("\n[2] produceSignView 逐个试 tid")
        for label, tid in cands.items():
            if tid in (None, "", 0, "0"):
                continue
            url = (f"{HOST_MOBILE}/sign/produceSignView?tid={tid}&uid={s.uid}"
                   f"&appType=15")
            st3, body3, _ = s.request(url)
            txt = re.sub(r"\s+", " ", body3)[:150]
            flag = ""
            if "enc" in body3.lower() or re.search(r"\b[0-9A-F]{32}\b", body3):
                flag = "  ★★★ 含 enc/hex！"
            print(f"    tid({label})={tid:<16} HTTP {st3:<4} {len(body3):>6}B{flag}")
            if st3 == 200 and body3 and not body3.lstrip().startswith("<!"):
                print(f"        {txt}")
            if flag:
                with open(os.path.join(os.path.dirname(OUT), f"produce_{label}.txt"),
                          "w", encoding="utf-8") as fh:
                    fh.write(body3)
                print(f"        已保存 produce_{label}.txt")

        # ---------- 3. 详情里其它可疑 id 字段 ----------
        print("\n[3] 详情里的 id 类字段")
        for k, v in d.items():
            if v in (None, "", 0, "0"):
                continue
            if re.search(r"(id|Id|ID)$", k) and str(v).isdigit() and len(str(v)) >= 6:
                print(f"    {k} = {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
