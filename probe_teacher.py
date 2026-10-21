"""验证「教师身份能不能拿到 enc」。

思路（用户提的）：
  如果账号在某门课里有教师权限，那教师端「查看签到二维码」的接口
  可能就会返回真 enc —— 学生身份被抹成 null 只是因为权限不够。

三步：
  1. 查每门课的角色（backclazzdata 里的 content.roletype）
  2. 对**进行中**的签到重试 produceSignView 的各种参数
  3. 对同一个活动，带上教师相关参数重试 /sign/qrcode
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session                                        # noqa: E402
from cxsign.protocol import (                                         # noqa: E402
    HOST_MOBILE, HOST_MOOC, build_active_info_url, build_course_list_url,
)

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")
AID = "2000176267779"      # 进行中的二维码签到


def role_map(s: Session) -> dict:
    """courseId -> roletype / teacherfactor"""
    data, _, _ = s.get_json(build_course_list_url(HOST_MOOC))
    out = {}
    for ch in (data or {}).get("channelList") or []:
        content = ch.get("content") or {}
        cid = str(content.get("id") or "")
        course = content.get("course") or {}
        rows = course.get("data") or []
        row = rows[0] if rows else {}
        out[cid] = {
            "classId": cid,
            "className": content.get("name"),
            "courseId": str(row.get("id") or ""),
            "courseName": row.get("name"),
            "roletype": content.get("roletype"),
            "teacherfactor": row.get("teacherfactor"),
            "studentcount": content.get("studentcount"),
        }
    return out


def main() -> int:
    s = Session(cookie_file=COOKIE)
    print(f"uid={s.uid} fid={s.fid}\n")

    # ---------- 1. 角色 ----------
    rm = role_map(s)
    print(f"班级数 {len(rm)}，roletype 取值分布：")
    dist = {}
    for v in rm.values():
        dist[v["roletype"]] = dist.get(v["roletype"], 0) + 1
    for k, v in sorted(dist.items(), key=lambda x: str(x[0])):
        print(f"   roletype={k!r}: {v} 个")

    print("\n课程 268194985（你刚发签到的那个）的角色：")
    hit = [v for v in rm.values() if v["courseId"] == "268194985"]
    for v in hit:
        print(f"   {json.dumps(v, ensure_ascii=False)}")
    if not hit:
        print("   没找到")

    # ---------- 2. 活动详情里的身份字段 ----------
    info, _, _ = s.get_json(build_active_info_url(AID))
    d = (info or {}).get("data") or {}
    print("\n活动详情里的身份相关字段：")
    for k in ("puid", "createuid", "createxxuid", "stuid", "userName",
              "attendNum", "releaseNum", "activeSort", "otherId", "status"):
        if k in d:
            print(f"   {k:<14} = {d[k]}")

    # ---------- 3. produceSignView 换参数重试 ----------
    print("\n=== produceSignView（进行中的活动）===")
    tids = {
        "activeId": AID,
        "parentid": d.get("parentid"),
        "pptPlanId": d.get("pptPlanId"),
        "realActiveId": d.get("realActiveId"),
        "oldActiveId": d.get("oldActiveId"),
        "chartid": d.get("chartid"),
    }
    for label, tid in tids.items():
        if tid in (None, "", 0):
            continue
        for extra in ("", "&bbsid=&groupId=", "&signType=1", "&teacher=1", "&role=1"):
            url = f"{HOST_MOBILE}/sign/produceSignView?tid={tid}&uid={s.uid}&appType=15{extra}"
            st, body, _ = s.request(url)
            hexes = re.findall(r"\b[0-9A-F]{32}\b", body)
            txt = re.sub(r"\s+", " ", body)[:90]
            mark = "  ★★★ 含 32 位 hex" if hexes else ""
            print(f"   tid({label})={tid} {extra or '(无)'}")
            print(f"      HTTP {st} {len(body)}B{mark}  {txt}")
            if hexes:
                print(f"      hex: {hexes[:4]}")
                open(os.path.join(os.path.dirname(__file__), "..", "core", "data",
                                  f"psv_{label}.txt"), "w", encoding="utf-8").write(body)

    # ---------- 4. /sign/qrcode 带教师参数 ----------
    print("\n=== /sign/qrcode 换参数 ===")
    for extra in ("", "&uid=" + s.uid, "&role=1", "&teacher=1", "&signType=1",
                  "&appType=15", "&fid=" + s.fid, "&t=1&type=1"):
        url = f"{HOST_MOBILE}/sign/qrcode?activeId={AID}{extra}"
        st, body, _ = s.request_bytes(url)
        if body[:3] == b"\xff\xd8\xff":
            from cxsign.qr import decode_bytes
            r = decode_bytes(body)
            print(f"   {extra or '(无)'}  -> 图片 {len(body)}B  内容={r.first!r}")
        else:
            print(f"   {extra or '(无)'}  -> HTTP {st} {len(body)}B "
                  f"{body[:60].decode('utf-8','replace')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
