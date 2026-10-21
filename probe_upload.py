"""探测学习通网盘上传的真实入口。

现在的实现是：
    GET  https://pan-yz.chaoxing.com/api/token?puid=<uid>
    POST https://pan-yz.chaoxing.com/upload
但实测 token 那一步返回 404，说明路径变了。挨个试。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session  # noqa: E402

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")


def main() -> int:
    s = Session(cookie_file=COOKIE)
    uid = s.uid
    print(f"uid={uid} fid={s.fid}\n")

    # ---------- token ----------
    print("=" * 74)
    print("① 找 token 接口")
    print("=" * 74)
    token_urls = [
        f"https://pan-yz.chaoxing.com/api/token?puid={uid}",
        f"https://pan-yz.chaoxing.com/api/getToken?puid={uid}",
        f"https://pan-yz.chaoxing.com/token?puid={uid}",
        f"https://pan-yz.chaoxing.com/api/upload/token?puid={uid}",
        f"https://pan-yz.chaoxing.com/upload/token?puid={uid}",
        f"https://pan-yz.chaoxing.com/api/file/token?puid={uid}",
        f"https://pan-yz.chaoxing.com/",
        f"https://pan-yz.chaoxing.com/api/",
    ]
    for u in token_urls:
        st, body, final = s.request(u)
        head = (body or "")[:120].replace("\n", " ")
        print(f"  {u[:62]:<64} HTTP {st:<4} {len(body or '')}B")
        if st == 200 and body:
            print(f"      {head}")

    # ---------- 上传入口 ----------
    print("\n" + "=" * 74)
    print("② 找上传入口（先只看 GET 是否可达，不发文件）")
    print("=" * 74)
    ups = [
        "https://pan-yz.chaoxing.com/upload",
        "https://pan-yz.chaoxing.com/api/upload",
        "https://pan-yz.chaoxing.com/api/upload/file",
        "https://mooc1-api.chaoxing.com/upload",
        "https://upload.chaoxing.com/upload",
        f"https://pan-yz.chaoxing.com/upload?_token=&puid={uid}",
    ]
    for u in ups:
        st, body, _ = s.request(u)
        head = (body or "")[:100].replace("\n", " ")
        print(f"  {u[:62]:<64} HTTP {st:<4} {len(body or '')}B  {head}")

    # ---------- 参考：上传照片的地方可能是别的域名 ----------
    print("\n" + "=" * 74)
    print("③ 活动详情里有没有现成可用的上传/图片地址线索")
    print("=" * 74)
    from cxsign.protocol import build_active_info_url
    d, _, _ = s.get_json(build_active_info_url("2000176267809"))
    info = (d or {}).get("data") or {}
    for k, v in info.items():
        if isinstance(v, str) and ("pan" in v or "upload" in v.lower() or "img" in v.lower()):
            print(f"  {k} = {v[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
