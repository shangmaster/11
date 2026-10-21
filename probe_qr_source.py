"""探测：二维码签到的 enc 到底能不能从接口拿到。

背景：
  二维码里的内容是 https://mobilelearn.chaoxing.com/widget/sign/e?id=<activeId>&enc=<密钥>
  enc 由教师发布签到时服务端生成。学生端一直被认为是「拿不到，只能看图」。

  但值得逐个试一遍 —— 如果某个接口的响应里带着 enc，二维码签到就能全自动，
  连图都不用给。

探测顺序（从最可能有戏到最不可能）：
  1. getPPTActiveInfo 的完整原始响应（我只提取了部分字段，raw 里可能有别的）
  2. widget/sign/e 不带 enc 直接请求，看服务端会不会把 enc 渲染进 HTML
  3. newsign/preSign 学生签到页
  4. widget/sign/signIn 轮换码页面
  5. 通知接口（老师发签到时推给全班的那条）
  6. H5 页面里的 JS 变量

用法：
    python tools/probe_qr_source.py [activeId ...]
不给 activeId 就自动从进行中的活动里找二维码类。
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session                                        # noqa: E402
from cxsign.protocol import (                                        # noqa: E402
    HOST_MOBILE, build_active_info_url, build_active_list_url,
    extract_activities, normalize_active_info,
)

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")

# 32 位 hex 是 enc 的典型样子（实测 0DA06A4208CAAF0961A7EEC658E0EDF5）
RE_ENC32 = re.compile(r"\b[0-9A-F]{32}\b")
# base64 里可能藏 enc
RE_ENC_JSON = re.compile(r'"enc"\s*:\s*"([0-9A-Fa-f]{16,64})"')


def scan_for_enc(label: str, text: str, depth: int = 0) -> list[str]:
    """在一段响应里找像 enc 的东西。"""
    hits: list[str] = []

    for m in RE_ENC_JSON.finditer(text):
        hits.append(f"json.enc={m.group(1)}")
    # 原始 32 位 hex
    for m in RE_ENC32.finditer(text):
        hits.append(f"hex32={m.group(0)}")
    # URL 里带 enc=
    for m in re.finditer(r"[?&]enc=([0-9A-Fa-f]{16,64})", text):
        hits.append(f"url.enc={m.group(1)}")

    # 去重保序
    seen: set[str] = set()
    out = []
    for h in hits:
        if h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out[:12]


def probe(s: Session, aid: str) -> None:
    print("\n" + "=" * 70)
    print(f"activeId = {aid}")
    print("=" * 70)

    # ---- 1. 活动详情完整原始响应 ----
    url = build_active_info_url(aid)
    data, st, _ = s.get_json(url)
    print(f"\n[1] getPPTActiveInfo  HTTP {st}")
    if isinstance(data, dict):
        d = data.get("data") or {}
        print(f"    字段: {sorted(d.keys())}")
        info = normalize_active_info(data)
        print(f"    activeSort={info.active_sort}  name={info.name}")
        raw_text = json.dumps(data, ensure_ascii=False)
        hits = scan_for_enc("info", raw_text)
        print(f"    含 enc 特征: {hits if hits else '没有'}")
        # 显式检查几个可能的字段名
        for k in ("enc", "signEnc", "qrCode", "qrcode", "signCode", "code", "url", "signUrl"):
            if k in d:
                print(f"    ★ 字段 {k} = {str(d[k])[:120]}")
    else:
        print(f"    非 JSON: {str(data)[:120]}")

    # ---- 2. widget/sign/e 不带 enc ----
    for path in (
        f"/widget/sign/e?id={aid}",
        f"/widget/sign/e?id={aid}&enc=",
        f"/widget/sign/e?id={aid}&c=1&enc=",
    ):
        st2, body, final = s.request(HOST_MOBILE + path)
        print(f"\n[2] {path}  HTTP {st2}  {len(body)} 字节")
        if st2 == 200 and body:
            low = body.lower()
            if "<html" in low or "<script" in low:
                hits = scan_for_enc("html", body)
                print(f"    HTML 页面，含 enc 特征: {hits if hits else '没有'}")
                # 抓页面里的 JS 变量
                for m in re.finditer(r"(?:var|let|const)\s+(\w*enc\w*)\s*=\s*['\"]([^'\"]{8,80})['\"]",
                                     body, re.I):
                    print(f"    ★ JS 变量 {m.group(1)} = {m.group(2)}")
                for m in re.finditer(r"(?:var|let|const)\s+(\w*(?:activeId|signId)\w*)\s*=\s*['\"]?(\d{6,})",
                                     body, re.I):
                    print(f"      JS {m.group(1)} = {m.group(2)}")
                # 页面首 300 字，判断是不是"要扫码"的拒绝页
                snippet = re.sub(r"\s+", " ", body[:300])
                print(f"    开头: {snippet[:200]}")
            else:
                print(f"    非 HTML: {body[:200]}")

    # ---- 3. newsign/preSign ----
    path = f"/newsign/preSign?activeId={aid}&appType=15&uid={s.uid}&fid={s.fid}"
    st3, body3, final3 = s.request(HOST_MOBILE + path)
    print(f"\n[3] newsign/preSign  HTTP {st3}  {len(body3)} 字节  最终 {final3[:90]}")
    if body3:
        hits = scan_for_enc("presign", body3)
        print(f"    含 enc 特征: {hits if hits else '没有'}")
        for m in re.finditer(r"(?:var|let|const)\s+(\w*enc\w*)\s*=\s*['\"]([^'\"]{8,80})['\"]",
                             body3, re.I):
            print(f"    ★ JS 变量 {m.group(1)} = {m.group(2)}")
        snippet = re.sub(r"\s+", " ", body3[:400])
        print(f"    开头: {snippet[:260]}")

    # ---- 4. widget/sign/signIn（轮换码） ----
    path = f"/widget/sign/signIn?activeId={aid}&appType=15"
    st4, body4, _ = s.request(HOST_MOBILE + path)
    print(f"\n[4] widget/sign/signIn  HTTP {st4}  {len(body4)} 字节")
    if body4:
        hits = scan_for_enc("signin", body4)
        print(f"    含 enc 特征: {hits if hits else '没有'}")
        snippet = re.sub(r"\s+", " ", body4[:300])
        print(f"    开头: {snippet[:200]}")

    # ---- 5. 通知接口 ----
    for u in (
        "https://notice.chaoxing.com/pc/notice/getNoticeList?pageSize=20&page=1",
        f"{HOST_MOBILE}/v2/apis/active/getStuSignList?activeId={aid}",
    ):
        st5, body5, _ = s.request(u)
        print(f"\n[5] {u[:80]}  HTTP {st5}  {len(body5)} 字节")
        if body5:
            hits = scan_for_enc("notice", body5)
            print(f"    含 enc 特征: {hits if hits else '没有'}")
            print(f"    开头: {re.sub(chr(10), ' ', body5[:200])}")


def find_qr_activities(s: Session) -> list[str]:
    """从进行中的活动里挑二维码类的。"""
    from cxsign.protocol import HOST_MOOC, build_course_list_url, parse_courses
    data, st, _ = s.get_json(build_course_list_url(HOST_MOOC))
    courses = parse_courses(data)
    found: list[str] = []
    for c in courses[:60]:
        url = build_active_list_url(c.course_id, c.class_id, s.fid or "")
        if not url:
            continue
        d, st2, _ = s.get_json(url)
        for a in extract_activities(d):
            if a.status != 1:
                continue
            found.append(a.active_id)
    # 去重
    return list(dict.fromkeys(found))


def main() -> int:
    if not os.path.exists(COOKIE):
        print("没有 cookie.json，先 python run.py login")
        return 1
    s = Session(cookie_file=COOKIE)
    print(f"uid={s.uid} fid={s.fid}")

    aids = sys.argv[1:]
    if not aids:
        print("扫描进行中的活动…")
        aids = find_qr_activities(s)
        print(f"找到 {len(aids)} 个进行中的活动")

    if not aids:
        print("没有进行中的活动，没法探测。等老师发一个签到，或者手动传 activeId。")
        return 2

    for aid in aids[:4]:
        try:
            probe(s, aid)
        except Exception as e:                       # noqa: BLE001
            print(f"  探测 {aid} 出错: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
