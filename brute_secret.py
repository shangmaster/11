"""最后一张牌：拿 APK 里全部 448382 条字符串当 secret，暴力撞签名。

之前只用了 2429 个「看起来可疑」的候选，漏掉了没有关键词的普通字符串。
这一轮用全量，只试最可能的几种拼装，换 30 秒。
"""

import hashlib
import hmac
import os
import sys
import time

STRINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "core", "data", "apk_strings.txt")

APPID = "B44F2B1D-03D0-47FF-A458-B734A9BF1FD2"

# crcStorageStatus 那条（参数最多，最容易区分）
P = {"appid": APPID, "crc": "a5e757bdf25d873fca33f3a4e57314bc",
     "nonce": "2644296096", "puid": "342160628", "timestamp": "1792561139285"}
WANT = "dce9632df96c407f449df4a51e6c1b70"

# upload 那条，用于验证
P2 = {"appid": APPID, "nonce": "2951188970", "puid": "342160628",
      "timestamp": "1792561139371"}
WANT2 = "c2279ffd324910b4a1d65335ecfb93f0"


def plains_for(params: dict) -> dict[str, str]:
    ks = sorted(params)
    out = {
        "kv&排序": "&".join(f"{k}={params[k]}" for k in ks),
        "vals排序": "".join(params[k] for k in ks),
        "vals&排序": "&".join(params[k] for k in ks),
        "kv&原序": "&".join(f"{k}={params[k]}" for k in params),
        "vals原序": "".join(params[k] for k in params),
        "kv原序另序": "".join(f"{k}{params[k]}" for k in ks),
    }
    return out


def main() -> int:
    if not os.path.exists(STRINGS):
        print("没有 apk_strings.txt")
        return 1
    print("读取候选串…")
    cands: list[bytes] = []
    with open(STRINGS, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.rstrip("\n")
            if s:
                cands.append(s.encode("utf-8", "ignore"))
    print(f"候选 {len(cands)} 条")

    plains = plains_for(P)
    t0 = time.time()
    tried = 0
    hit = None

    for pname, plain in plains.items():
        pb = plain.encode()
        for i, c in enumerate(cands):
            tried += 1
            # 只试两种最常见的方向 + hmac
            if hashlib.md5(pb + c).hexdigest() == WANT:
                hit = (pname, "md5(plain+secret)", c); break
            if hashlib.md5(c + pb).hexdigest() == WANT:
                hit = (pname, "md5(secret+plain)", c); break
            if hmac.new(c or b"\x00", pb, hashlib.md5).hexdigest() == WANT:
                hit = (pname, "hmac_md5", c); break
        if hit:
            break
        print(f"  {pname} 试完（{time.time()-t0:.0f}s）")

    print(f"\n共试 {tried} 次，用时 {time.time()-t0:.0f}s")

    if not hit:
        print("全量字符串也没撞上。")
        print("=> secret 不在 dex 的字符串常量里，基本可以确定在 .so 或服务端。")
        return 0

    pname, algo, secret = hit
    print("\n★★★ 命中！")
    print(f"   拼装   : {pname}")
    print(f"   算法   : {algo}")
    print(f"   secret : {secret!r}")

    # 用另一条样本验证
    print("\n用 upload 那条样本验证…")
    ok = False
    for pn, pl in plains_for(P2).items():
        pb = pl.encode()
        tests = {
            "md5(plain+secret)": hashlib.md5(pb + secret).hexdigest(),
            "md5(secret+plain)": hashlib.md5(secret + pb).hexdigest(),
            "hmac_md5": hmac.new(secret or b"\x00", pb, hashlib.md5).hexdigest(),
        }
        for a, v in tests.items():
            if v == WANT2:
                print(f"   ★ 验证通过：{pn} / {a}")
                ok = True
    print("   验证结果:", "通过 —— 算法确定了" if ok else "只有第一条命中，可能是巧合")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
