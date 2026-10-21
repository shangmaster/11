"""signature 破解，第二轮：HMAC。

第一轮试了 md5/sha1/sha256 的常见拼接，没中。这一轮补：
  · HMAC-MD5 / HMAC-SHA1 / HMAC-SHA256（signature 最常见就是 HMAC）
  · 更多 secret 候选（含从 HAR 里挖到的所有 UUID / 32 位 hex）
  · 更多参数排列和分隔符
"""

import hashlib
import hmac
import itertools
import json
import os
import re
import sys

HAR = (sys.argv[1] if len(sys.argv) > 1 else
       r"C:\Users\s\Documents\xwechat_files\wxid_3mokr2luok8422_6525\msg\file\2026-10"
       r"\mmbiz.qpic.cn_2026_10_21_13_41_38.har")

APPID = "B44F2B1D-03D0-47FF-A458-B734A9BF1FD2"

SAMPLES = [
    ("crcStorageStatus",
     {"appid": APPID, "crc": "a5e757bdf25d873fca33f3a4e57314bc",
      "nonce": "2644296096", "puid": "342160628", "timestamp": "1792561139285"},
     "dce9632df96c407f449df4a51e6c1b70"),
    ("upload",
     {"appid": APPID, "nonce": "2951188970", "puid": "342160628",
      "timestamp": "1792561139371"},
     "c2279ffd324910b4a1d65335ecfb93f0"),
]

# ---------------------------------------------------------------- secret 候选

BASE_SECRETS = [
    "", APPID, APPID.lower(), APPID.replace("-", ""),
    "chaoxing", "chaoXing", "CHAOXING", "cx", "CX", "cldisk", "CLDISK",
    "panyz", "pan-yz", "yz", "xiaoya", "xxt", "study", "mobilelearn",
    "B44F2B1D", "44F2B1D", "b44f2b1d",
    "chaoxing.com", "pan-yz.chaoxing.com", "p.cldisk.com",
    "mobilelearn", "upload", "uploadv2", "sign", "signature",
    "2024", "2025", "2026", "1234567890",
]


def collect_from_har() -> list[str]:
    """从 HAR 里捞所有像 secret 的串（UUID / 32 位 hex / 长串）。"""
    if not os.path.exists(HAR):
        return []
    try:
        with open(HAR, "r", encoding="utf-8", errors="replace") as fh:
            blob = fh.read()
    except Exception:
        return []
    out: set[str] = set()
    for m in re.finditer(r"\b[0-9a-fA-F]{32}\b", blob):
        out.add(m.group(0))
    for m in re.finditer(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"
                         r"-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b", blob):
        out.add(m.group(0))
    for m in re.finditer(r'"(?:secret|key|appSecret|app_secret|signKey)"\s*:\s*"([^"]{4,64})"',
                         blob, re.I):
        out.add(m.group(1))
    # 去重、限制数量（32 位 hex 可能很多，采样）
    return list(out)[:300]


# ---------------------------------------------------------------- 拼装方式

def build_plain_sets(params: dict) -> dict[str, str]:
    """生成多种「待签串」。"""
    keys_sorted = sorted(params)
    vals_s = [params[k] for k in keys_sorted]
    kvs_s = [f"{k}={params[k]}" for k in keys_sorted]
    kvs_o = [f"{k}={params[k]}" for k in params]

    sets: dict[str, str] = {}
    for sep in ("", "&", "|", ",", ";"):
        sets[f"sorted_vals sep={sep!r}"] = sep.join(vals_s)
        sets[f"sorted_kv   sep={sep!r}"] = sep.join(kvs_s)
        sets[f"orig_kv     sep={sep!r}"] = sep.join(kvs_o)
    # 只用 timestamp / nonce 之类的小组合
    for combo in (("nonce", "timestamp"), ("appid", "nonce", "timestamp"),
                  ("puid", "timestamp"), ("appid", "puid", "timestamp")):
        if all(k in params for k in combo):
            sets[f"only {combo}"] = "".join(params[k] for k in combo)
            sets[f"only {combo} &"] = "&".join(params[k] for k in combo)
    return sets


def main() -> int:
    secrets = BASE_SECRETS + collect_from_har()
    print(f"secret 候选 {len(secrets)} 个（含从 HAR 里挖的）\n")

    total = 0
    for label, params, want in SAMPLES:
        print("=" * 74)
        print(f"{label}   want={want}")
        print("=" * 74)
        plains = build_plain_sets(params)
        hit = False
        for pname, plain in plains.items():
            pb = plain.encode()
            for sec in secrets:
                sb = sec.encode()
                cands = {
                    "md5(m+s)": hashlib.md5(pb + sb).hexdigest(),
                    "md5(s+m)": hashlib.md5(sb + pb).hexdigest(),
                    "hmac_md5": hmac.new(sb or b"\x00", pb, hashlib.md5).hexdigest(),
                    "hmac_sha1_32": hmac.new(sb or b"\x00", pb,
                                             hashlib.sha1).hexdigest()[:32],
                    "sha256_32": hashlib.sha256(pb + sb).hexdigest()[:32],
                }
                total += len(cands)
                for cname, val in cands.items():
                    if val.lower() == want.lower():
                        print(f"\n  ★★★ 命中！")
                        print(f"      拼装: {pname}")
                        print(f"      算法: {cname}")
                        print(f"      secret: {sec!r}")
                        print(f"      明文: {plain}")
                        print(f"      结果: {val}")
                        hit = True
        print(f"  {'命中' if hit else '这一组没中'}")
    print(f"\n共试了 {total} 个组合")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
