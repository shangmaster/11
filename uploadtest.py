"""一条命令测上传通道：拍照签到能不能成，全看这一步。

用法：
    python run.py upload-test                     # 用内置测试图
    python run.py upload-test --file 你的照片.jpg
    python run.py upload-test --active 2000176267809   # 传成功后顺手签一次

为什么要单独一个命令：
    咔在「IP 白名单」的时候，报错信息会直接告诉你当前 IP 不在允许范围，
    而不是丢一个「上传失败」让人去猜是参数问题还是接口问题。
"""

from __future__ import annotations

import json
import os


def run(args, cfg, session) -> int:
    from cxsign.upload import upload_photo_file, validate_image
    from cxsign.upload import MAX_BYTES

    path = getattr(args, "file", "") or ""
    if not path or not os.path.exists(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "test_photo.jpg")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            print("没有照片，生成一张测试图…")
            try:
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
                img.save(path, "JPEG", quality=88)
            except Exception as e:
                print(f"生成测试图失败: {e}")
                return 1

    print(f"照片: {path}")
    ok, why, ext, mime = validate_image(path)
    print(f"校验: {'通过' if ok else '不通过'}  {why}")
    if not ok:
        return 1

    print(f"uid : {session.uid}")
    print("上传中（这一步会告诉你 IP 在不在白名单）…")
    up = upload_photo_file(session, session.uid, path)
    print()
    if up.ok:
        print(f"✅ 上传成功  objectid = {up.object_id}")
        from urllib.parse import quote
        print(f"   图片地址: https://p.cldisk.com/star3/312_412c/{quote(up.object_id)}.jpg")

        pr = json.dumps({"files": [{"name": os.path.basename(path),
                                    "objectid": up.object_id, "type": ext}]},
                        ensure_ascii=False, separators=(",", ":"))
        print(f"   photoResult（客户端自己拼的，不是签名）:")
        print(f"   {pr}")

        # 顺手签一次
        aid = getattr(args, "active", "") or ""
        if aid:
            print(f"\n带着这个 objectId 去签 {aid} …")
            from cxsign.engine import Engine, State, load_config
            from cxsign.protocol import Activity, classify
            cfg2 = cfg if cfg else load_config(os.path.join(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))), "config.json"))
            eng = Engine(cfg2, session, State(""), on_event=None)
            info = eng.fetch_info(aid)
            kind = classify(info)
            act = Activity(active_id=aid, status=1, name=(info.name if info else ""))
            if info:
                act.course_id = str(info.raw.get("courseId") or "")
                act.class_id = str(info.raw.get("clazzid") or "")
            rec = eng.submit(act, kind, object_id=up.object_id, photo_result=pr)
            print(f"   结果: {rec.state}  {rec.message}")
            print(f"   服务端原话: {rec.detail.get('response')!r}")
            if rec.state == "SIGNED":
                print("\n   ★ 拍照签到打通了")
        return 0

    print("❌ 上传失败")
    print(f"   {up.message}")
    if up.raw:
        print(f"   服务端原话: {up.raw[:300]}")
    if "IP 白名单" in up.message or "不被允许" in up.message:
        print()
        print("   这条不是参数问题，是网络限制。按顺序试：")
        print("   1) 手机开热点，电脑连热点再跑一次")
        print("   2) 用校园网 / 手机流量（不要用宽带的 NAT 出口）")
        print("   3) 换一个国内代理，出口 IP 挑非大陆云的住宅段")
    return 1
