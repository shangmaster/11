"""HAR 里拿到了真实上传链路，先验证两件事：

1. /upload/v2 还受不受 IP 白名单限制？（老接口 /upload 是受限的）
   —— 这决定拍照签到能不能解。

2. signature 是不是能算出来？
   两条真实样本：
     crcStorageStatus  appid+crc+nonce+puid+timestamp -> dce9632df96c407f449df4a51e6c1b70
     upload            appid+nonce+puid+timestamp     -> c2279ffd324910b4a1d65335ecfb93f0
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session  # noqa: E402

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")
PHOTO = os.path.join(os.path.dirname(__file__), "..", "core", "data", "test_photo.jpg")

APPID = "B44F2B1D-03D0-47FF-A458-B734A9BF1FD2"


def probe_v2(s: Session) -> None:
    print("=" * 76)
    print("① /upload/v2 还受 IP 限制吗")
    print("=" * 76)
    if not os.path.exists(PHOTO):
        print("  没有测试图，跳过")
        return
    content = open(PHOTO, "rb").read()

    cases = [
        ({"appid": APPID, "puid": s.uid, "nonce": "1234567890",
          "timestamp": "1792561139371", "signature": "0" * 32}, "带假 signature"),
        ({"appid": APPID, "puid": s.uid}, "只带 appid+puid"),
        ({}, "什么都不带"),
    ]
    for fields, label in cases:
        st, text, _ = s.post_multipart(
            "https://pan-yz.chaoxing.com/upload/v2?_from=mobilelearn",
            fields, "file", "photo.jpg", content, "image/jpeg",
            headers={"Upload-Incomplete": "?0",
                     "Upload-Draft-Interop-Version": "3"},
        )
        print(f"\n  [{label}]  HTTP {st}")
        print(f"    {str(text)[:260]}")

    # 老接口对照
    st, text, _ = s.post_multipart(
        "https://pan-yz.chaoxing.com/upload",
        {"puid": s.uid}, "file", "photo.jpg", content, "image/jpeg")
    print(f"\n  [对照：老接口 /upload]  HTTP {st}")
    print(f"    {str(text)[:200]}")


def crack_sign() -> None:
    """试常见拼接方式，看能不能撞出真实 signature。"""
    print("\n" + "=" * 76)
    print("② signature 能不能算出来")
    print("=" * 76)

    samples = [
        # (label, 参数字典（不含 signature）, 真实 signature)
        ("crcStorageStatus",
         {"appid": APPID, "crc": "a5e757bdf25d873fca33f3a4e57314bc",
          "nonce": "2644296096", "puid": "342160628",
          "timestamp": "1792561139285"},
         "dce9632df96c407f449df4a51e6c1b70"),
        ("upload",
         {"appid": APPID, "nonce": "2951188970", "puid": "342160628",
          "timestamp": "1792561139371"},
         "c2279ffd324910b4a1d65335ecfb93f0"),
    ]

    for label, params, want in samples:
        print(f"\n  --- {label}  want={want}")
        keys_sorted = sorted(params)
        vals_sorted = [params[k] for k in keys_sorted]
        kvs_sorted = [f"{k}={params[k]}" for k in keys_sorted]
        kvs_orig = [f"{k}={params[k]}" for k in params]

        cands = {
            "values_sorted_连写": "".join(vals_sorted),
            "values_sorted_& 连": "&".join(vals_sorted),
            "k=v& 排序": "&".join(kvs_sorted),
            "k=v& 原序": "&".join(kvs_orig),
            "v 拼接(原序)": "".join(params[k] for k in params),
        }
        # 加盐变体
        salts = ["", "chaoxing", "cx", "pan", "yz", "panyz", "B44F2B1D-03D0-47FF-A458-B734A9BF1FD2"]
        found = False
        for name, base in cands.items():
            for salt in salts:
                for order in (0, 1):
                    plain = (base + salt) if order == 0 else (salt + base)
                    for algo in ("md5", "sha1", "sha256"):
                        h = hashlib.new(algo, plain.encode()).hexdigest()
                        for cand in (h, h[:32], h.upper()):
                            if cand.lower() == want.lower():
                                print(f"    ★★★ 命中！{name} salt={salt!r} "
                                      f"{'后置' if order==0 else '前置'} {algo}")
                                print(f"        plain = {plain}")
                                found = True
        if not found:
            print("    没命中常见组合 —— 大概率带服务端私钥")


def main() -> int:
    if os.path.exists(COOKIE):
        s = Session(cookie_file=COOKIE)
        print(f"uid={s.uid} fid={s.fid}\n")
        probe_v2(s)
    else:
        print("没有 cookie，跳过上传测试")
    crack_sign()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
