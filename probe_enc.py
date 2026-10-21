"""两个方向一起试：

A. enc 是不是算法算出来的？（用已知样本反推）
   已知样本来自公开抓包：
       activeId = 6000059680136
       enc      = 0DA06A4208CAAF0961A7EEC658E0EDF5
   关键线索：同一个活动里 c 从 251295 变到 206225，enc 一点没变。
   => enc 不依赖 c、不依赖时间。要么只依赖 activeId（可以算），
      要么是发布时生成并存库的随机值（算不出来）。

B. 有没有「生成/查看签到」的接口学生端能调到？（服务端探测）
   produceSignView / getSignInInfo / getSignList 一类。

用法：
    python tools/probe_enc.py
    python tools/probe_enc.py --active 2000176022454
"""

from __future__ import annotations

import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")

# ---- 已知样本（公开抓包，两个 c 不同但 enc 相同）----
SAMPLE_ID = "6000059680136"
SAMPLE_ENC = "0DA06A4208CAAF0961A7EEC658E0EDF5"


def md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def try_algo() -> list[str]:
    """穷举常见拼接方式，看能不能撞出已知 enc。"""
    aid = SAMPLE_ID
    want = SAMPLE_ENC.lower()

    salts = [
        "", "chaoxing", "chaoxing.com", "cx", "CX", "sign", "Sign", "SIGN",
        "ewm", "ewmSign", "signIn", "pptSign", "mobilelearn", "active",
        "activeId", "code", "qrcode", "qr", "2024", "2025", "1", "15",
        "0", "-1", "fid", "133138", "uid", "215505229",
    ]
    seps = ["", "|", "_", "-", ":", "&", "+", "."]

    hits: list[str] = []
    tried = 0

    def check(desc: str, plain: str) -> None:
        nonlocal tried
        tried += 1
        for name, digest in (
            ("md5", md5(plain)),
            ("md5upper", md5(plain).upper()),
            ("sha1_32", hashlib.sha1(plain.encode()).hexdigest()[:32]),
            ("sha256_32", hashlib.sha256(plain.encode()).hexdigest()[:32]),
        ):
            if digest.lower() == want:
                hits.append(f"★ 命中！{name}({desc}) = {digest}")

    # id 单独
    check(f'"{aid}"', aid)

    # id + 盐 / 盐 + id
    for s in salts:
        for sep in seps:
            check(f'"{aid}{sep}{s}"', f"{aid}{sep}{s}")
            check(f'"{s}{sep}{aid}"', f"{s}{sep}{aid}")

    # 换一种 id 表示（有些接口用 activePrimaryId / parentid）
    for other in ("6000059680136", "6000059680137", "201700001", "1"):
        check(f'"{other}"', other)

    print(f"  试了 {tried} 种明文，覆盖 md5/sha1/sha256 共 {tried * 4} 个摘要")
    return hits


def probe_endpoints(aids: list[str]) -> None:
    from cxsign.net import Session
    from cxsign.protocol import HOST_MOBILE

    s = Session(cookie_file=COOKIE)
    print(f"  uid={s.uid} fid={s.fid}")

    # 这些是官方客户端里出现过的、跟「生成/查看签到」有关的路径
    paths = [
        ("produceSignView", "/sign/produceSignView?tid={aid}&uid={uid}&appType=15"),
        ("produceSign", "/sign/produceSign?activeId={aid}&uid={uid}&appType=15"),
        ("getSignInInfo", "/pptSign/getSignInInfo?activeId={aid}"),
        ("getSignList", "/pptSign/getSignList?activeId={aid}"),
        ("getSignInfo", "/pptSign/getSignInfo?activeId={aid}"),
        ("preSignFull", "/pptSign/preSign?activeId={aid}&classId=&uid={uid}"
                        "&chatId=&general=&sys=1&ls=1&appType=15&ut=s"),
        ("activeInfoV1", "/v2/apis/active/getActiveInfo?activeId={aid}"),
        ("studentSign", "/newsign/studentSign?rcode=&uid={uid}"),
        ("signView", "/pptSign/sign?activeId={aid}"),
        ("widgetSign", "/widget/sign/index?activeId={aid}&enc="),
        ("getStuSign", "/v2/apis/active/getStuSign?activeId={aid}"),
    ]

    for aid in aids[:2]:
        print(f"\n  --- activeId {aid} ---")
        for name, tpl in paths:
            url = HOST_MOBILE + tpl.format(aid=aid, uid=s.uid)
            st, body, final = s.request(url)
            mark = ""
            low = body.lower()
            if st == 200 and ("enc" in low or "ewm" in low):
                mark = "  ★ 含 enc/ewm"
            snippet = ""
            if body:
                snippet = body[:110].replace("\n", " ").replace("\r", "")
            print(f"    {name:<16} HTTP {st:<4} {len(body):>6}B{mark}")
            if mark or (st == 200 and len(body) < 2000 and not body.lstrip().startswith("<!")):
                print(f"        {snippet}")


def main() -> int:
    print("=" * 70)
    print("A. enc 是不是算出来的？（用公开样本反推）")
    print("=" * 70)
    print(f"  已知: activeId={SAMPLE_ID}")
    print(f"        enc     ={SAMPLE_ENC}")
    hits = try_algo()
    if hits:
        for h in hits:
            print("  " + h)
        print("\n  => 能算！二维码签到可以全自动，不用图。")
    else:
        print("\n  没命中任何常见组合。")
        print("  => 更可能是发布时生成的随机值（存库里），或者带我们不知道的盐/私钥。")

    aids = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not os.path.exists(COOKIE):
        print("\n（没有 cookie，跳过接口探测）")
        return 0

    print("\n" + "=" * 70)
    print("B. 服务端接口探测：学生端能不能调到「生成签到」那一层")
    print("=" * 70)
    if not aids:
        aids = ["2000176022454"]
        print("  没给 activeId，用上次探到的那个二维码签到")
    probe_endpoints(aids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
