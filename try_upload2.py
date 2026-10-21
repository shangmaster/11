"""破解拍照签到的最后一环：找到能拿到 objectid 的上传通道。

已经确认的事实（从 newsign/preSign 页面的 JS 里读出来的）：
    PHOTO_RESULT = JSON.stringify({files:[{name, objectid, type}]})
    photoResult 不是签名凭证，就是上传结果的 JSON，客户端自己拼。
    图片访问前缀：https://p.cldisk.com/star3/312_412c/<objectid>.jpg
    原生桥上传参数：{"_from":"mobilelearn"}

所以只差「把图传上去换 objectid」这一步。挨个试。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session  # noqa: E402
from cxsign.protocol import HOST_MOBILE  # noqa: E402

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")
PHOTO = os.path.join(os.path.dirname(__file__), "..", "core", "data", "test_photo.jpg")
AID = "2000176267809"


def need_photo() -> None:
    if os.path.exists(PHOTO):
        return
    from PIL import Image, ImageDraw
    import random
    w, h = 900, 1200
    img = Image.new("RGB", (w, h), (208, 206, 198))
    d = ImageDraw.Draw(img)
    rnd = random.Random(7)
    for _ in range(600):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r = rnd.randrange(8, 60)
        g = rnd.randrange(180, 225)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(g, g - 4, g - 12))
    img.save(PHOTO, "JPEG", quality=88)


def try_upload(s: Session, url: str, fields: dict, name: str) -> str:
    """返回 objectid，失败返回空串。"""
    with open(PHOTO, "rb") as fh:
        content = fh.read()
    print(f"\n  POST {url}")
    print(f"       fields={fields}  file={len(content)}B")
    st, text, _ = s.post_multipart(url, fields, "file", "photo.jpg", content, "image/jpeg")
    head = (text or "")[:300].replace("\n", " ")
    print(f"       HTTP {st}  {head}")
    if st != 200:
        return ""
    try:
        d = json.loads(text)
    except Exception:
        return ""
    oid = ""
    for k in ("objectid", "objectId", "objectID"):
        if isinstance(d, dict) and d.get(k):
            oid = str(d[k])
            break
    if not oid and isinstance(d, dict):
        files = d.get("files")
        if isinstance(files, list) and files and isinstance(files[0], dict):
            oid = str(files[0].get("objectid") or "")
    if oid:
        print(f"       ★ objectid = {oid}")
    return oid


def main() -> int:
    need_photo()
    s = Session(cookie_file=COOKIE)
    uid = s.uid
    print(f"uid={uid} 照片={os.path.getsize(PHOTO)}B")

    print("\n" + "=" * 74)
    print("① pan-yz 直接 POST（跳过 token）")
    print("=" * 74)
    base = {"puid": uid, "_from": "mobilelearn"}
    combos = [
        ({"puid": uid}, "只有 puid"),
        ({"puid": uid, "_from": "mobilelearn"}, "puid + _from"),
        ({"puid": uid, "_token": ""}, "puid + 空 token"),
        ({"_from": "mobilelearn"}, "只有 _from"),
    ]
    for fields, label in combos:
        oid = try_upload(s, "https://pan-yz.chaoxing.com/upload", fields, label)
        if oid:
            return submit_with(s, oid)

    print("\n" + "=" * 74)
    print("② p.cldisk.com（页面里图片的真实域名）")
    print("=" * 74)
    for url in ("https://p.cldisk.com/upload",
                "https://p.cldisk.com/api/upload",
                "https://p.cldisk.com/star3/upload"):
        oid = try_upload(s, url, {"puid": uid, "_from": "mobilelearn"}, "")
        if oid:
            return submit_with(s, oid)

    print("\n" + "=" * 74)
    print("③ 换个思路：直接探 p.cldisk.com 是否可达")
    print("=" * 74)
    for u in ("https://p.cldisk.com/", "https://p.cldisk.com/star3/"):
        st, body, _ = s.request(u)
        print(f"  {u}  HTTP {st}  {len(body or '')}B  {(body or '')[:80]}")
    return 0


def submit_with(s: Session, oid: str) -> int:
    """拿到 objectid 就拼 photoResult 提交。"""
    from cxsign.engine import Engine, State, DEFAULT_CONFIG, deep_merge
    from cxsign.protocol import Activity, classify

    pr = json.dumps({"files": [{"name": "photo.jpg", "objectid": oid, "type": "jpg"}]},
                    ensure_ascii=False, separators=(",", ":"))
    print("\n" + "=" * 74)
    print("④ 拿 objectid 拼 photoResult 提交")
    print("=" * 74)
    print(f"  objectId    = {oid}")
    print(f"  photoResult = {pr}")

    eng = Engine(deep_merge(DEFAULT_CONFIG, {}), s, State(""), on_event=None)
    info = eng.fetch_info(AID)
    kind = classify(info)
    act = Activity(active_id=AID, status=1, name=(info.name if info else ""))
    if info:
        act.course_id = str(info.raw.get("courseId") or "")
        act.class_id = str(info.raw.get("clazzid") or "")

    rec = eng.submit(act, kind, object_id=oid, photo_result=pr)
    print(f"\n  state = {rec.state}")
    print(f"  message = {rec.message}")
    print(f"  服务端原话 = {rec.detail.get('response')!r}")
    if rec.state == "SIGNED":
        print("\n  ★★★ 拍照签到成功！photoResult 是客户端拼的，不需要原生桥。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
