"""从官方 APK 里挖上传签名用的 secret。

为什么走这条路：/upload/v2 需要 signature，算法带私钥，纯穷举试不出来
（45540 个组合全试过）。但安卓 APK 没加密，dex 里的字符串常量是明文，
secret 只要硬编码就一定能捞到。

流程：
  1. 下载 APK（248MB，只下一次）
  2. 从 zip 里只取 classes*.dex（不落盘整个解压）
  3. 扫 dex 里的 UTF-8 字符串
  4. 挑出可疑的：32 位 hex / UUID / 含 sign、secret、appkey 的
  5. 用找到的候选去撞已知的 signature 样本
"""

import hashlib
import hmac
import json
import os
import re
import sys
import zipfile

APK_URL = "https://x.ananas.chaoxing.com/apk/release/study_7.0.4_09161103.apk"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core", "data")
APK = os.path.join(DATA, "chaoxing.apk")
STRINGS = os.path.join(DATA, "apk_strings.txt")

APPID = "B44F2B1D-03D0-47FF-A458-B734A9BF1FD2"
SAMPLES = [
    ({"appid": APPID, "crc": "a5e757bdf25d873fca33f3a4e57314bc",
      "nonce": "2644296096", "puid": "342160628", "timestamp": "1792561139285"},
     "dce9632df96c407f449df4a51e6c1b70"),
    ({"appid": APPID, "nonce": "2951188970", "puid": "342160628",
      "timestamp": "1792561139371"},
     "c2279ffd324910b4a1d65335ecfb93f0"),
]


def download() -> bool:
    if os.path.exists(APK) and os.path.getsize(APK) > 200_000_000:
        print(f"APK 已存在 {os.path.getsize(APK)/1e6:.0f}MB")
        return True
    import urllib.request
    os.makedirs(DATA, exist_ok=True)
    print(f"下载 {APK_URL}")
    req = urllib.request.Request(
        APK_URL, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 13)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(APK, "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            last = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if total and got - last > 20_000_000:
                    last = got
                    print(f"  {got/1e6:.0f}/{total/1e6:.0f} MB")
    except Exception as e:
        print(f"下载失败: {e}")
        return False
    print(f"完成 {os.path.getsize(APK)/1e6:.0f}MB")
    return True


PRINTABLE = re.compile(rb"[\x20-\x7e]{6,}")


def extract_strings() -> set[str]:
    out: set[str] = set()
    with zipfile.ZipFile(APK) as z:
        dexes = [n for n in z.namelist() if re.match(r"classes\d*\.dex$", n)]
        print(f"dex 文件 {len(dexes)} 个: {dexes}")
        for name in dexes:
            data = z.read(name)
            print(f"  {name}: {len(data)/1e6:.1f}MB")
            for m in PRINTABLE.finditer(data):
                s = m.group(0).decode("ascii", "ignore")
                if 6 <= len(s) <= 200:
                    out.add(s)
    print(f"提取到 {len(out)} 条字符串")
    return out


def suspicious(strings: set[str]) -> list[str]:
    """挑出可能是 secret 的。"""
    picked: list[str] = []

    # 1) 32 位 hex / UUID
    for s in strings:
        if re.fullmatch(r"[0-9a-fA-F]{32}", s) or \
           re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                        r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", s):
            picked.append(s)

    # 2) 名字里带 sign / secret / appkey 的串
    kw = re.compile(r"(sign|secret|appkey|app_key|salt|hmac|token)", re.I)
    for s in strings:
        if kw.search(s) and len(s) <= 120:
            picked.append(s)

    # 3) 跟 upload/v2、appid 出现在同一批的短串
    for s in strings:
        if "upload/v2" in s or "crcStorageStatus" in s:
            picked.append(s)

    return list(dict.fromkeys(picked))


def try_crack(cands: list[str]) -> bool:
    print(f"\n用 {len(cands)} 个候选撞签名…")
    plains_cache = []
    for params, _ in SAMPLES:
        keys = sorted(params)
        sets = {
            "kv&": "&".join(f"{k}={params[k]}" for k in keys),
            "vals": "".join(params[k] for k in keys),
            "vals&": "&".join(params[k] for k in keys),
            "kv原序": "&".join(f"{k}={params[k]}" for k in params),
        }
        plains_cache.append((params, sets))

    hit = False
    for (params, sets), (_, want) in zip(plains_cache, SAMPLES):
        for pname, plain in sets.items():
            pb = plain.encode()
            for c in cands:
                cb = c.encode()
                tests = {
                    "md5(s+p)": hashlib.md5(cb + pb).hexdigest(),
                    "md5(p+s)": hashlib.md5(pb + cb).hexdigest(),
                    "hmac_md5": hmac.new(cb, pb, hashlib.md5).hexdigest(),
                    "sha256_32": hashlib.sha256(pb + cb).hexdigest()[:32],
                }
                for algo, val in tests.items():
                    if val.lower() == want.lower():
                        print("\n★★★ 命中！")
                        print(f"   拼装   : {pname}")
                        print(f"   算法   : {algo}")
                        print(f"   secret : {c!r}")
                        print(f"   明文   : {plain}")
                        print(f"   期望   : {want}")
                        hit = True
    if not hit:
        print("候选池里没有能撞上的 —— 可能 secret 在 .so 里，或者算法更复杂")
    return hit


def main() -> int:
    if not download():
        return 1
    strings = extract_strings()
    with open(STRINGS, "w", encoding="utf-8", errors="replace") as fh:
        for s in sorted(strings):
            fh.write(s + "\n")
    print(f"字符串已保存 {STRINGS}")

    cands = suspicious(strings)
    print(f"可疑候选 {len(cands)} 个，前 20:")
    for c in cands[:20]:
        print("   ", c[:100])
    try_crack(cands)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
