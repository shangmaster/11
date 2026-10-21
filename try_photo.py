"""拿真实活动试一次拍照签到，看清它到底卡在哪。

步骤：
  1. 打详情：activeSort / ifphoto / activeType
  2. 不带图直接提交（看看服务端第一句话说什么）
  3. 上传一张本地图换 objectId，再提交
  4. 如果还拒绝，看是不是 photoAuthError_PCR007
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.engine import Engine, State, DEFAULT_CONFIG, deep_merge   # noqa: E402
from cxsign.net import Session                                        # noqa: E402
from cxsign.protocol import Activity, build_active_info_url, classify  # noqa: E402
from cxsign.upload import upload_photo_file, validate_image           # noqa: E402

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")
AID = sys.argv[1] if len(sys.argv) > 1 else "2000176267809"
PHOTO = sys.argv[2] if len(sys.argv) > 2 else ""


def make_test_photo(path: str) -> str:
    """生成一张看起来像随手拍的测试图（有纹理，不是纯色）。"""
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
    for y in range(0, h, 40):
        d.line([(0, y), (w, y)], fill=(196, 194, 186), width=1)
    img.save(path, "JPEG", quality=88)
    return path


def main() -> int:
    s = Session(cookie_file=COOKIE)
    eng = Engine(deep_merge(DEFAULT_CONFIG, {}), s, State(""), on_event=None)

    data, st, _ = s.get_json(build_active_info_url(AID))
    d = (data or {}).get("data") or {}
    print("=" * 70)
    print(f"activeId = {AID}")
    print("=" * 70)
    for k in ("activeType", "activeSort", "otherId", "ifphoto", "ifNeedVCode",
              "openCheckFaceFlag", "openPreventCheatFlag", "name", "status",
              "starttime", "endtime", "puid", "createuid"):
        if k in d:
            print(f"  {k:<22} = {d[k]}")

    info = eng.fetch_info(AID)
    kind = classify(info)
    print(f"\n  判定: {kind.key}  is_sign={kind.is_sign}  {kind.describe()}")
    print(f"  needs_photo = {kind.needs_photo}")

    act = Activity(active_id=AID, status=1, name=(info.name if info else ""))
    if info:
        act.course_id = str(info.raw.get("courseId") or "")
        act.class_id = str(info.raw.get("clazzid") or "")

    # ---------- 1. 不带图 ----------
    print("\n" + "-" * 70)
    print("① 不带 objectId 直接提交")
    print("-" * 70)
    rec = eng.submit(act, kind)
    print(f"   state={rec.state}  message={rec.message}")
    print(f"   服务端原话: {rec.detail.get('response')!r}")
    if rec.state == "SIGNED":
        print("\n  ✅ 这个拍照签到不需要凭证，直接过了")
        return 0

    # ---------- 2. 带本地图 ----------
    photo = PHOTO
    if not photo or not os.path.exists(photo):
        photo = os.path.join(os.path.dirname(__file__), "..", "core", "data", "test_photo.jpg")
        make_test_photo(photo)
        print(f"\n  （没有指定照片，生成了一张测试图：{photo}）")

    ok, why, ext, mime = validate_image(photo)
    print(f"\n  照片校验: {ok} {why}")

    print("\n" + "-" * 70)
    print("② 上传本地图换 objectId，再提交")
    print("-" * 70)
    up = upload_photo_file(s, s.uid, photo)
    print(f"   上传: ok={up.ok} objectId={up.object_id or '-'}  {up.message}")

    if up.ok:
        # 用 submit 的 object_id 参数，避免它自己再传一次
        rec2 = eng.submit(act, kind, object_id=up.object_id)
        print(f"   state={rec2.state}  message={rec2.message}")
        print(f"   服务端原话: {rec2.detail.get('response')!r}")
        print(f"   提交的参数:")
        for k, v in (rec2.detail.get("params") or {}).items():
            print(f"      {k:<18} = {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
