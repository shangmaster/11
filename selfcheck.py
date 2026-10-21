#!/usr/bin/env python3
"""离线自检：不联网，把所有解析/判定/组装逻辑跑一遍。

    python selfcheck.py

为什么值得写：签到这种一次性操作，失败一次就没有第二次机会。
所有「看起来只是字符串拼接」的地方，都是踩过坑的——这里把每个坑钉成一条断言。
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

from cxsign import geo, protocol as P, upload as U  # noqa: E402
from cxsign.engine import DEFAULT_CONFIG, Record, State, deep_merge, load_config  # noqa: E402

PASS = 0
FAIL: list[str] = []


def ok(cond, name: str, detail: str = "") -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(f"{name} {detail}".strip())


def eq(got, want, name: str) -> None:
    ok(got == want, name, f"(got={got!r} want={want!r})")


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 52 - len(title)))


# --------------------------------------------------------------------------
section("类型判定：activeSort 全表")
for sort, want in [(1, "plain"), (2, "plain"), (3, "plain"), (4, "location"),
                   (5, "location"), (6, "qr"), (7, "qr"), (8, "qr"),
                   (9, "code"), (16, "gesture")]:
    info = P.ActiveInfo(active_sort=sort)
    eq(P.classify(info).key, want, f"activeSort={sort}")

section("类型判定：otherId 全表")
for oid, want in [(0, "plain"), (1, "plain"), (2, "plain"), (3, "gesture"),
                  (4, "location"), (5, "code"), (6, "qr"), (7, "qr"), (8, "qr")]:
    info = P.ActiveInfo(other_id=oid)
    eq(P.classify(info).key, want, f"otherId={oid}")

section("类型判定：优先级与坑")
# activeSort 比 otherId 权威
info = P.ActiveInfo(active_sort=4, other_id=1)
eq(P.classify(info).key, "location", "activeSort 盖过 otherId")

# ifphoto 不是类型！普通签到 + 要求拍照 仍然是 plain
info = P.ActiveInfo(active_sort=3, if_photo=True)
k = P.classify(info)
eq(k.key, "plain", "activeSort=3 判成普通")
ok(k.needs_photo, "activeSort=3 标出要拍照")

# ifrefreshewm 单独出现不能把活动判成二维码
info = P.ActiveInfo(active_sort=1, if_refresh_ewm=1)
eq(P.classify(info).key, "plain", "ifrefreshewm 不改变类型")

# 没有服务端字段时按名字兜底
act = P.Activity(active_id="600000000001", name="二维码签到")
k = P.classify(None, act)
eq(k.key, "qr", "名字兜底=二维码")
ok(k.from_name, "标记为名字推断")
eq(P.classify(None, P.Activity(active_id="1", name="手势签到")).key, "gesture", "名字兜底=手势")
eq(P.classify(None, P.Activity(active_id="1", name="普通签到")).key, "plain", "名字兜底=普通")
eq(P.classify(None, P.Activity(active_id="1", name="随便写写")).key, "unknown", "认不出=unknown")

# 人脸 / 验证码是附加标记
k = P.classify(P.ActiveInfo(active_sort=5, open_check_face=1))
eq(k.key, "location", "位置+人脸仍归位置")
ok(k.needs_face, "标出要人脸")
ok(P.classify(P.ActiveInfo(active_sort=2, if_need_vcode=True)).needs_vcode, "标出要验证码")

# 描述里带依据，方便面板排查
d = P.classify(P.ActiveInfo(active_sort=4, other_id=4)).describe()
ok("类型=位置" in d and "activeSort=4" in d, "describe 含类型和依据", d)


section("类型判定：activeType 闸门（问卷/作业不能被当成签到）")
# 实测：问卷活动 activeType=14，activeSort=6 —— 照签到的表查会被误判成二维码
survey = P.ActiveInfo(active_id="2000146542704", active_type=14, active_sort=6,
                      other_id=2000024683117, name="问卷",
                      view_pic_path=".../ppt_wq.png")
k = P.classify(survey)
ok(not k.is_sign, "问卷 activeType=14 判为非签到")
eq(k.evidence.get("activeType"), 14, "证据里带 activeType")

# 签到：activeType=2
sign = P.ActiveInfo(active_id="2000176022454", active_type=2, active_sort=8,
                    other_id=2, name="二维码签到",
                    view_pic_path=".../ppt_ewm.png")
k = P.classify(sign)
ok(k.is_sign, "activeType=2 判为签到")
eq(k.key, "qr", "activeSort=8 -> 二维码")

# activeSort=11：实测的「二维码签到」，otherId=2 会误导成普通
info = P.ActiveInfo(active_sort=11, other_id=2, name="二维码签到")
k = P.classify(info)
eq(k.key, "qr", "activeSort=11 判成二维码")
ok(k.is_sign, "仍是签到")

# activeSort 未知 + 名字看不出 -> 才允许用 otherId
k = P.classify(P.ActiveInfo(active_sort=99, other_id=1, name="随手起的名字"))
eq(k.key, "plain", "名字看不出时才回退 otherId")

# activeType 缺失时不能误杀（老接口可能不返回）
k = P.classify(P.ActiveInfo(active_sort=4))
ok(k.is_sign, "activeType 缺失时不拦截")
eq(k.key, "location", "仍然按 activeSort 判定")

section("老师设定的签到点")
# locationLatitude_gd / locationLongitude_gd 是老师在地图上点的位置
info = P.ActiveInfo(location_lat_gd="30.541234", location_lon_gd="114.361234")
eq(P.active_point(info), (30.541234, 114.361234), "高德字段优先")

# 只有原始字段也能用
info = P.ActiveInfo(location_lat="30.5", location_lon="114.3")
eq(P.active_point(info), (30.5, 114.3), "回落原始字段")

# 经纬度写反了要能纠正
info = P.ActiveInfo(location_lat_gd="114.361234", location_lon_gd="30.541234")
eq(P.active_point(info), (30.541234, 114.361234), "经纬颠倒自动纠正")

# 老师没设点：服务端给 -1 / 空
eq(P.active_point(P.ActiveInfo(location_lat="-1.0", location_lon="-1.0")), None,
   "-1 视为没设点")
eq(P.active_point(P.ActiveInfo()), None, "空字段返回 None")
eq(P.active_point(None), None, "None 不炸")

# 高德字段是空的，但原始字段有值 -> 用原始
info = P.ActiveInfo(location_lat="30.5", location_lon="114.3",
                    location_lat_gd="", location_lon_gd="")
eq(P.active_point(info), (30.5, 114.3), "高德为空时回落原始")


# --------------------------------------------------------------------------
section("活动列表解析")
payload = {"result": 1, "data": {"activeList": [
    {"id": 6000059680136, "status": 1, "otherId": 4, "nameOne": "位置签到",
     "startTime": "2026-03-01 10:00"},
    {"activePrimaryId": "6000059680137", "activeStatus": 2, "otherId": 1, "nameOne": "已结束"},
    {"activeId": "123", "nameOne": "编号太短被丢掉"},
    {"activeId": "6000059680138", "status": "1", "activeSort": "9", "name": "<p>签到码</p>"},
]}}
acts = P.extract_activities(payload)
eq(len(acts), 3, "丢掉非法编号")
eq(acts[0].active_id, "6000059680136", "id 字段映射")
eq(acts[0].status, 1, "status 进行中")
ok(acts[0].running, "running 属性")
eq(acts[1].status, 2, "activeStatus 优先于 status")
eq(acts[2].name, "签到码", "去掉 HTML 标签")
eq(acts[2].active_sort, 9, "字符串 activeSort 转 int")

# 三种外层结构都要能吃
eq(len(P.extract_activities({"activeList": [{"id": "600000000001"}]})), 1, "顶层 activeList")
eq(len(P.extract_activities([{"id": "600000000001"}])), 1, "裸数组")
eq(len(P.extract_activities({"data": [{"id": "600000000001"}]})), 1, "data 是数组")
eq(len(P.extract_activities({"data": {"data": {"activeList": [{"id": "600000000001"}]}}})), 1,
   "嵌套 data.data.activeList")
eq(len(P.extract_activities(None)), 0, "None 不炸")
eq(len(P.extract_activities({"data": {"activeList": "notalist"}})), 0, "脏数据不炸")


# --------------------------------------------------------------------------
section("活动详情归一化")
info = P.normalize_active_info({"result": 1, "data": {
    "activeId": "6000059680136", "activeSort": 4, "otherId": 4,
    "ifphoto": 0, "ifNeedVCode": 0, "openCheckFaceFlag": 0, "ifrefreshewm": 1,
    "ifopenAddress": 1, "locationText": "中国湖北省武汉市武昌区珞珈山",
    "locationRange": "500", "name": "位置签到", "status": 1,
    "starttime": 1700000000000, "endtime": 1700003600000,
}})
eq(info.active_id, "6000059680136", "activeId")
eq(info.active_sort, 4, "activeSort")
eq(info.location_text, "中国湖北省武汉市武昌区珞珈山", "locationText")
eq(info.location_range, "500", "locationRange")
ok(info.if_photo is False, "ifphoto=0 归一成 False")
eq(info.start_time, 1700000000000, "starttime")

eq(P.normalize_active_info({"data": {"data": {"activeSort": 6}}}).active_sort, 6, "双层 data")
eq(P.normalize_active_info({}).active_sort, None, "空对象不炸")


# --------------------------------------------------------------------------
section("签到参数组装")

# 纯普通：GET，带 useragent，不含 address
pairs = P.build_sign_params(active_id="600001", uid="215505229", fid="133138", kind="plain",
                            name="张三")
d = dict(pairs)
eq(d["activeId"], "600001", "plain activeId")
eq(d["uid"], "215505229", "plain uid")
ok("useragent" in d, "plain 带 useragent（GET 页面行为）")
eq(d["latitude"], "-1.000000", "plain 坐标 -1")
ok("address" not in d, "plain 不带 address")
ok("objectId" not in d, "plain 不带 objectId")
ok("enc" not in d, "plain 不带 enc")
eq(d["appType"], "15", "appType=15")
ok(not P.sign_uses_post("plain"), "plain 用 GET")

# 位置：POST，带 address/ifTiJiao/vp*，不带 useragent
pairs = P.build_sign_params(active_id="600002", uid="1", fid="2", kind="location",
                            lat=30.541234, lon=114.361234, address="武汉大学")
d = dict(pairs)
eq(d["latitude"], "30.541234", "位置纬度 6 位")
eq(d["longitude"], "114.361234", "位置经度 6 位")
eq(d["address"], "武汉大学", "位置地址")
eq(d["ifTiJiao"], "1", "ifTiJiao=1")
ok("vpProbability" in d and "ifCFP" in d, "位置带采集状态位")
ok("useragent" not in d, "位置 POST 不带 useragent")
ok(P.sign_uses_post("location"), "位置用 POST")

# 拍照：POST，带 objectId，不带坐标以外的位置字段
pairs = P.build_sign_params(active_id="600003", uid="1", fid="2", kind="photo",
                            object_id="abcdef123456", photo_result="")
d = dict(pairs)
eq(d["objectId"], "abcdef123456", "拍照 objectId")
ok("address" not in d, "拍照不带 address")
ok("photoResult" not in d, "空 photoResult 不发送（服务端区分没传和传空）")
eq(d["latitude"], "-1.000000", "拍照默认 -1 坐标")

# 二维码：带 enc
pairs = P.build_sign_params(active_id="600004", uid="1", fid="2", kind="qr",
                            enc="0DA06A4208CAAF0961A7EEC658E0EDF5")
d = dict(pairs)
eq(d["enc"], "0DA06A4208CAAF0961A7EEC658E0EDF5", "二维码 enc")
ok(P.sign_uses_post("qr"), "二维码用 POST")

# 签到码
d = dict(P.build_sign_params(active_id="600005", uid="1", fid="2", kind="code",
                             sign_code="2580"))
eq(d["signCode"], "2580", "签到码")

# 二维码 + 指定地点（activeSort=8）：enc 和坐标要同时带
d = dict(P.build_sign_params(active_id="600008", uid="1", fid="2", kind="qr",
                             enc="AABBCCDD", lat=30.5, lon=114.3, address="武汉大学",
                             force_location=True))
eq(d["enc"], "AABBCCDD", "activeSort=8 保留 enc")
eq(d["address"], "武汉大学", "activeSort=8 同时带位置地址")
eq(d["latitude"], "30.500000", "activeSort=8 同时带坐标")
ok("ifTiJiao" in d, "activeSort=8 带 ifTiJiao")

# 空字符串的可选字段要整条不出现（服务端区分「没传」和「传空」）
d = dict(P.build_sign_params(active_id="600006", uid="1", fid="2", kind="plain",
                             device_code="", validate="", object_id=""))
for k in ("deviceCode", "validate", "objectId"):
    ok(k not in d, f"空 {k} 不发送")

# GET url 拼装
url = P.build_sign_url(P.build_sign_params(active_id="600007", uid="1", fid="2"))
ok(url.startswith("https://mobilelearn.chaoxing.com/pptSign/stuSignajax?activeId=600007"),
   "sign url 前缀", url[:90])


# --------------------------------------------------------------------------
section("返回码翻译")
for raw, want_ok in [("success", True), ("success2", True), ("SUCCESS", True),
                     ("您已签到过了", True), ("validate", False),
                     ("签到失败，请重新扫描", False), ("photoAuthError_PCR007", False),
                     ("请先登录再进行签到", False), ("", False)]:
    got, msg = P.translate_result(raw)
    eq(got, want_ok, f"translate({raw!r})")
    ok(bool(msg), f"translate({raw!r}) 有文案")
ok("防作弊" in P.translate_result("validate")[1], "validate 提示准确")
ok("现场" in P.translate_result("photoAuthError_PCR007")[1], "PCR007 提示准确")


# --------------------------------------------------------------------------
section("二维码解析")
q1 = P.parse_qr("https://mobilelearn.chaoxing.com/widget/sign/e?id=6000059680136"
                "&c=251295&enc=0DA06A4208CAAF0961A7EEC658E0EDF5&DB_STRATEGY=PRIMARY_KEY")
ok(q1.usable, "H5 活码可用")
eq(q1.active_id, "6000059680136", "活码 id -> activeId")
eq(q1.enc, "0DA06A4208CAAF0961A7EEC658E0EDF5", "活码 enc")

q1b = P.parse_qr("https://mobilelearn.chaoxing.com/widget/sign/e?id=6000059680136"
                 "&c=206225&enc=0DA06A4208CAAF0961A7EEC658E0EDF5")
eq(q1b.enc, q1.enc, "c 变了 enc 不变（轮换码同一个密钥）")

q2 = P.parse_qr("https://mobilelearn.chaoxing.com/widget/sign/signIn?activeId=600009"
                "&ewnCode=ab12cd")
eq(q2.active_id, "600009", "轮换码 activeId")
eq(q2.ewn_code, "ab12cd", "轮换码 ewnCode")
ok(q2.usable, "轮换码可用")

q3 = P.parse_qr("SIGNIN:eyJhIjoxfQ==")
ok(q3.usable, "SIGNIN 载荷可用")
ok(q3.rcode.startswith("SIGNIN:"), "rcode 保留原文")

q4 = P.parse_qr("0DA06A4208CAAF0961A7EEC658E0EDF5")
eq(q4.enc, "0DA06A4208CAAF0961A7EEC658E0EDF5", "纯 enc 串")
ok(q4.usable, "纯 enc 可用")

# 分享文本里夹着链接
q5 = P.parse_qr("【签到通知】老师发布了签到，点这里 http://mobilelearn.chaoxing.com/"
                "widget/sign/e?id=600008&enc=AABBCCDD11223344 快来")
eq(q5.enc, "AABBCCDD11223344", "从分享文本里挖链接")

eq(P.parse_qr("").usable, False, "空串不可用")
eq(P.parse_qr("https://www.chaoxing.com/").usable, False, "普通网址不可用")
ok("无法识别" in P.parse_qr("https://example.com/x").describe(), "describe 兜底文案")


# --------------------------------------------------------------------------
section("坐标转换")
# 天安门 WGS-84 -> GCJ-02，参考值 39.908722, 116.397499（高德）
g = geo.wgs84_to_gcj02(39.90862, 116.39131)
ok(abs(g[0] - 39.91006) < 0.002 and abs(g[1] - 116.39756) < 0.002, "wgs84->gcj02", str(g))

# 往返误差应 < 2 米
back = geo.gcj02_to_wgs84(*g)
d_round = geo.distance(39.90862, 116.39131, *back)
ok(d_round < 2.0, "gcj02->wgs84 往返误差 < 2m", f"{d_round:.2f}m")

# BD-09 单向转换量级正确（几百米）
b = geo.gcj02_to_bd09(39.91006, 116.39756)
ok(geo.distance(39.91006, 116.39756, *b) > 100, "gcj02->bd09 偏移量级", str(b))
back2 = geo.bd09_to_gcj02(*b)
ok(geo.distance(39.91006, 116.39756, *back2) < 2.0, "bd09->gcj02 往返", f"{geo.distance(39.91006,116.39756,*back2):.2f}m")

# 境外不做偏移
eq(geo.wgs84_to_gcj02(48.8566, 2.3522), (48.8566, 2.3522), "境外不偏移")

# 距离
eq(round(geo.distance(39.9, 116.4, 39.9, 116.4)), 0, "同点距离 0")
ok(300 < geo.distance(39.9, 116.4, 39.903, 116.4) < 400, "0.003 度纬度 ≈ 333m",
   f"{geo.distance(39.9,116.4,39.903,116.4):.1f}")

# 抖动：不出半径
import random as _rnd
rng = _rnd.Random(42)
worst = 0.0
for _ in range(500):
    j = geo.jitter(30.5, 114.3, 40.0, rng)
    worst = max(worst, geo.distance(30.5, 114.3, *j))
ok(worst <= 40.0, "抖动始终在半径内", f"max={worst:.1f}m")
ok(worst > 1.0, "抖动确实有位移", f"max={worst:.1f}m")

section("坐标粘贴解析")
eq(geo.parse_point("30.5,114.3"), (30.5, 114.3), "逗号")
eq(geo.parse_point("30.5 114.3"), (30.5, 114.3), "空格")
eq(geo.parse_point("114.3,30.5"), (30.5, 114.3), "经纬颠倒自动纠正")
eq(geo.parse_point("30.5，114.3"), (30.5, 114.3), "中文逗号")
eq(geo.parse_point("abc"), None, "非数字")
eq(geo.parse_point(""), None, "空")


# --------------------------------------------------------------------------
section("课程列表解析")
payload = {"result": 1, "channelList": [{"content": {"course": {"data": [
    {"id": 233333333, "name": "高等数学", "clazzs": [
        {"id": 555555551, "name": "2024级1班"},
        {"id": 555555552, "name": "2024级2班"},
    ]},
    {"id": 233333334, "name": "大学物理", "clazzs": []},
]}}}]}
cs = P.parse_courses(payload)
# 老版结构：高等数学挂两个班 -> 2 条；大学物理 clazzs 为空且 content 上没有 id，
# 拿不到 classId 就没法签到，直接丢掉才对（早期版本会产出一条 classId="" 的废记录）
eq(len(cs), 2, "两个班级，无 classId 的被丢弃")
eq(cs[0].course_id, "233333333", "courseId")
eq(cs[0].class_id, "555555551", "classId")
eq(cs[0].name, "高等数学", "课程名")
eq(cs[0].class_name, "2024级1班", "班级名")
eq(P.parse_courses({"channelList": []}), [], "空列表")
eq(P.parse_courses({"result": 0}), [], "未登录")
eq(len(P.parse_courses({"channelList": [{"content": {
    "course": json.dumps({"data": [{"id": 1, "name": "字符串化", "clazzs": [{"id": 2}]}]})}}]})),
   1, "course 是 JSON 字符串")

section("课程列表解析 · 新版结构（实测 2026）")
# 新版：班级信息平铺在 content 上，course.data[0].clazzs 是 null
payload_new = {"result": 1, "channelList": [
    {"content": {"id": 157462133, "name": "24级物理学1",
                 "course": {"data": [{"id": 268194985, "name": "量子力学2026",
                                      "clazzs": None}]}}},
    {"content": {"id": 157280727, "name": "2026年",
                 "course": {"data": [{"id": 230379591, "name": "高中物理教学专题研究"}]}}},
    # 老版本结构混在里面也要能认
    {"content": {"course": {"data": [{"id": 233333333, "name": "高等数学",
                                      "clazzs": [{"id": 555555551, "name": "1班"}]}]}}},
]}
cs = P.parse_courses(payload_new)
eq(len(cs), 3, "新旧结构混排都能解析")
eq(cs[0].course_id, "268194985", "新版 courseId")
eq(cs[0].class_id, "157462133", "新版 classId 来自 content.id")
eq(cs[0].name, "量子力学2026", "新版课程名")
eq(cs[0].class_name, "24级物理学1", "新版班级名")
eq(cs[1].class_id, "157280727", "第二条 classId")
eq(cs[2].class_id, "555555551", "老版 clazzs 仍然生效")

# 新旧字段都在时不能重复产出
dup = {"channelList": [{"content": {
    "id": 157462133, "name": "24级物理学1",
    "course": {"data": [{"id": 268194985, "name": "量子力学",
                         "clazzs": [{"id": 157462133, "name": "24级物理学1"}]}]}}}]}
eq(len(P.parse_courses(dup)), 1, "同一 courseId+classId 只保留一条")


# --------------------------------------------------------------------------
section("URL 组装")
u = P.build_active_list_url("233333333", "555555551", "133138", now=1700000000000)
ok(u.startswith("https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist?"), "列表 URL")
ok("courseId=233333333" in u and "classId=555555551" in u, "列表参数名大小写")
ok("showNotStartedActive=0" in u, "默认只查进行中")
eq(P.build_active_list_url("", "555"), None, "缺 courseId 返回 None")
eq(P.build_active_list_url("233", ""), None, "缺 classId 返回 None")

u = P.build_active_info_url("6000059680136", now=1700000000000)
ok(u.startswith("https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo?activeId="),
   "详情 URL")
eq(P.build_active_info_url(""), None, "空 activeId 返回 None")

ok(P.build_course_list_url().startswith("https://mooc1-api.chaoxing.com/mycourse/backclazzdata"),
   "课程列表 URL")
ok("getTchClazzClass=1" not in P.build_course_list_url(), "参数名别写错")
ok(P.build_pan_token_url("215505229").endswith("?puid=215505229"), "pan token URL")
ok(P.build_pan_upload_url().endswith("/upload"), "pan upload URL")


# --------------------------------------------------------------------------
section("图片校验")
ok(U.sniff_image(b"\xff\xd8\xff\xe0" + b"\x00" * 20) == ("jpg", "image/jpeg"), "识别 jpg")
ok(U.sniff_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20) == ("png", "image/png"), "识别 png")
ok(U.sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("webp", "image/webp"), "识别 webp")
eq(U.sniff_image(b"<?php echo 1; ?>"), None, "拒绝伪装的 php")
eq(U.sniff_image(b""), None, "空内容")
eq(U.sniff_image(b"GIF89a"), ("gif", "image/gif"), "识别 gif")

import tempfile  # noqa: E402
tmp = os.path.join(tempfile.gettempdir(), "cxsign_selfcheck.png")
with open(tmp, "wb") as fh:
    fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
good, why, ext, mime = U.validate_image(tmp)
ok(good, "合法图片通过", why)
eq(ext, "png", "扩展名")
os.unlink(tmp)

bad = os.path.join(tempfile.gettempdir(), "cxsign_selfcheck.bin")
with open(bad, "wb") as fh:
    fh.write(b"not an image at all")
good, why, _, _ = U.validate_image(bad)
ok(not good and "不是常见图片" in why, "非法图片被拒", why)
os.unlink(bad)

ok(not U.validate_image("/nonexistent/x.jpg")[0], "不存在的文件被拒")


section("服务端直出二维码的解析（/sign/qrcode）")
# 实测格式：'<enc>-<13 位毫秒时间戳>'，学生身份下 enc 是 'null'
eq(P.parse_server_qr_text("null-1792514345987"), ("", "服务端只给了时间戳，enc=null（没权限或活动不在进行中）"),
   "null 占位符")
ok("null" in P.parse_server_qr_text("null-1792514345987")[1], "null 的说明写清楚")

enc, why = P.parse_server_qr_text("0DA06A4208CAAF0961A7EEC658E0EDF5-1792514345987")
eq(enc, "0DA06A4208CAAF0961A7EEC658E0EDF5", "真 enc 能解析出来")
eq(why, "拿到 enc", "说明")

# 万一服务端直接给完整链接
enc, _ = P.parse_server_qr_text(
    "https://mobilelearn.chaoxing.com/widget/sign/e?id=6000059680136"
    "&enc=0DA06A4208CAAF0961A7EEC658E0EDF5")
eq(enc, "0DA06A4208CAAF0961A7EEC658E0EDF5", "H5 链接形态也能解")

# 纯 hex
eq(P.parse_server_qr_text("AABBCCDD11223344AABBCCDD11223344")[0],
   "AABBCCDD11223344AABBCCDD11223344", "纯 hex 形态")

eq(P.parse_server_qr_text("")[0], "", "空串")
ok("没见过的" in P.parse_server_qr_text("hello-world-123")[1], "不认识的内容给说明")


# --------------------------------------------------------------------------
section("photoResult 结构分析")
from cxsign.photoprobe import analyze as _pa  # noqa: E402

# 典型可伪造结构：时间戳|纬度|经度|设备号|md5
r = _pa("1730000000000|30.541234|114.361234|0123456789abcdef|d41d8cd98f00b204e9800998ecf8427e")
eq(len(r["segments"]), 5, "竖线分隔切成 5 段")
ok("时间戳" in r["segments"][0]["guess"], "第 0 段认成时间戳")
ok("纬度" in r["segments"][1]["guess"], "第 1 段认成纬度")
ok("经度" in r["segments"][2]["guess"], "第 2 段认成经度")
ok("MD5" in r["segments"][4]["guess"], "最后一段认成 MD5")
ok("可以自己造" in r["verdict"], "结论：可伪造", r["verdict"])
eq(r["confidence"], "high", "高置信度")

# base64 裹 JSON
b64json = ("eyJ0IjoxNzMwMDAwMDAwMDAwLCJsYXQiOjMwLjU0LCJsb24iOjExNC4zNiwiaCI6ImFiYyJ9")
r = _pa(b64json)
ok("base64(JSON)" in r["structure"], "识别出 base64(JSON)", r["structure"])
ok(any(s.get("key") == "t" for s in r["segments"]), "JSON 字段被展开成段")
ok(any(s.get("key") == "lat" for s in r["segments"]), "lat 字段展开")

# JWT
r = _pa("eyJhbGciOiJIUzI1NiJ9.eyJ0IjoxNzMwMDAwMDAwfQ.abcdefghij")
ok("JWT" in r["structure"], "识别 JWT", r["structure"])
ok(r.get("json", {}).get("header", {}).get("alg") == "HS256", "解出 JWT header")
ok("服务端签发" in r["verdict"], "JWT 结论：造不出来", r["verdict"])

# 从整条请求串里抽
r = _pa("activeId=600005&photoResult=1730000000000%7C30.54%7C114.36"
        "%7Cd41d8cd98f00b204e9800998ecf8427e&uid=1")
ok(r.get("note"), "从查询串里抽出了 photoResult")
eq(r["input_len"], 59, "抽出后的长度")

# 空 / 垃圾
eq(_pa("")["structure"], "空", "空输入")
r = _pa("hello")
ok("结构太简单" in r["verdict"], "垃圾输入给出「不像凭证」", r["verdict"])


# --------------------------------------------------------------------------
section("配置合并")
cfg = deep_merge(DEFAULT_CONFIG, {"poll": {"activeSeconds": 3}, "sign": {"qr": False}})
eq(cfg["poll"]["activeSeconds"], 3, "覆盖生效")
eq(cfg["poll"]["idleSeconds"], DEFAULT_CONFIG["poll"]["idleSeconds"], "未覆盖的保留默认")
eq(cfg["sign"]["qr"], False, "布尔覆盖")
eq(cfg["sign"]["plain"], True, "同级其他键保留")
eq(DEFAULT_CONFIG["poll"]["activeSeconds"], 5, "默认配置没被原地改")
eq(deep_merge({"a": 1}, {}), {"a": 1}, "空 patch")


# --------------------------------------------------------------------------
section("状态持久化")
state_path = os.path.join(tempfile.gettempdir(), "cxsign_state_test.json")
if os.path.exists(state_path):
    os.unlink(state_path)
st = State(state_path)
rec = Record(active_id="600001", name="测试", kind="plain", state="SIGNED", message="签到成功")
ok(not st.is_signed("600001"), "初始未签")
st.mark_signed("600001", rec)
ok(st.is_signed("600001"), "标记已签")
ok(os.path.exists(state_path), "落盘")
st2 = State(state_path)
ok(st2.is_signed("600001"), "重载后仍然已签（重启不重复签）")
st2.mark_pending("600002", Record(active_id="600002", state="WAITING"), ttl=60)
eq(list(st2.pending().keys()), ["600002"], "pending 记录")
st2.mark_pending("600003", Record(active_id="600003", state="WAITING"), ttl=-1)
ok("600003" not in st2.pending(), "过期 pending 自动清理")
os.unlink(state_path)


# --------------------------------------------------------------------------
section("引擎集成（不打网络）")
from cxsign.engine import Engine  # noqa: E402


class FakeSession:
    uid = "215505229"
    fid = "133138"
    uname = "张三"

    def get_json(self, url, headers=None):
        if "getPPTActiveInfo" in url:
            return {"result": 1, "data": {"activeId": "600001", "activeSort": 4,
                                          "otherId": 4, "locationText": "武汉大学",
                                          "locationRange": "500", "name": "位置签到",
                                          "courseId": "233333333"}}, 200, url
        if "activelist" in url:
            return {"result": 1, "data": {"activeList": [
                {"id": "600001", "status": 1, "nameOne": "位置签到"}]}}, 200, url
        return {"result": 1, "channelList": []}, 200, url

    def request(self, url, method="GET", data=None, headers=None, follow=True):
        return 200, "success", url

    def post_form(self, url, fields, headers=None):
        return 200, "success", url


eng = Engine(deep_merge(DEFAULT_CONFIG, {"sign": {"location": True}}), FakeSession(),
             State(""), on_event=lambda e: None)
eng.courses = [{"courseId": "233333333", "classId": "555555551", "name": "高等数学"}]
ik = P.classify(P.ActiveInfo(active_sort=4))
eq(ik.key, "location", "集成：位置类型")
ok(ik.needs_location, "集成：需要位置")

# 有坐标时参数里必须带 address + 真实经纬度
p = dict(P.build_sign_params(active_id="600001", uid="1", fid="2", kind="location",
                             lat=30.5412, lon=114.3612, address="武汉大学"))
ok(p["address"] == "武汉大学" and p["latitude"].startswith("30.54"), "集成：位置参数完整")

# 解析不出坐标时 resolve_point 应回 -1（引擎据此不发请求）
eng._point = None           # noqa: SLF001
eng.cfg["location"]["mode"] = "manual"
eng.cfg["location"]["point"] = None
lat, lon, addr, datum = eng.resolve_point(P.ActiveInfo(location_text=""))
eq((lat, lon), (-1.0, -1.0), "无坐标时回 -1")
eq(datum, "gcj02", "默认坐标系")

# 手选点优先
eng.set_point(30.5, 114.3, "gcj02")
lat, lon, addr, datum = eng.resolve_point(P.ActiveInfo(location_text="武汉大学"))
ok(abs(lat - 30.5) < 1e-6 and abs(lon - 114.3) < 1e-6, "手选点优先", f"{lat},{lon}")


# --------------------------------------------------------------------------
section("二维码 -> 签到联动（假会话）")
class QrSession(FakeSession):
    def __init__(self):
        self.posted = []

    def post_form(self, url, fields, headers=None):
        self.posted.append(dict(fields))
        return 200, "success", url


qs = QrSession()
eng2 = Engine(DEFAULT_CONFIG, qs, State(""), on_event=lambda e: None)
recs = eng2.feed_qr("https://mobilelearn.chaoxing.com/widget/sign/e?id=600001"
                    "&enc=AABBCCDD11223344", source="selfcheck")
eq(len(recs), 1, "二维码产生一次签到")
eq(recs[0].state, "SIGNED", "二维码签到成功")
ok(any(p.get("enc") == "AABBCCDD11223344" for p in qs.posted), "提交里带上了 enc")
ok(any(p.get("activeId") == "600001" for p in qs.posted), "提交里带上了 activeId")

# 同一张码短时间内重复投递要被去重
before = len(qs.posted)
eng2.feed_qr("https://mobilelearn.chaoxing.com/widget/sign/e?id=600001"
             "&enc=AABBCCDD11223344", source="selfcheck")
eq(len(qs.posted), before, "重复码被去重")


# --------------------------------------------------------------------------
section("本地 HTTP API（真起一个服务，打本机）")
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from cxsign.server import EventBus, serve  # noqa: E402

bus = EventBus()
eng3 = Engine(DEFAULT_CONFIG, FakeSession(), State(""), on_event=bus.push)
httpd = None
try:
    httpd = serve(eng3, bus, "127.0.0.1", 18848, "")
    base = "http://127.0.0.1:18848"

    def _get(path: str):
        try:
            with urllib.request.urlopen(base + path, timeout=5) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def _post(path: str, obj):
        req = urllib.request.Request(
            base + path, data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"raw": raw}

    st, body = _get("/api/status")
    eq(st, 200, "GET /api/status 200")
    data = json.loads(body)
    ok(data.get("ok") is True, "status ok=true")
    ok("stats" in data["data"], "status 带 stats")

    st, body = _get("/")
    ok(st == 200 and "签到哨兵" in body, "首页 HTML")

    st, obj = _post("/api/point", {"lat": 30.5, "lon": 114.3, "datum": "gcj02"})
    ok(obj.get("ok") is True, "POST /api/point 成功")
    ok(abs(eng3._point[0] - 30.5) < 1e-6, "选点写进引擎")   # noqa: SLF001

    st, obj = _post("/api/qr", {"text": "https://mobilelearn.chaoxing.com/widget/sign/e"
                                        "?id=600001&enc=DEADBEEF00112233"})
    ok(obj.get("ok") is True, "POST /api/qr 接受文本")
    eq(len(obj.get("results") or []), 1, "二维码触发一次签到")
    eq((obj["results"][0]).get("state"), "SIGNED", "二维码签到成功")

    st, obj = _post("/api/login", {})
    eq(st, 400, "空 cookie 返回 400")

    st, body = _get("/api/qr/backends")
    ok(json.loads(body).get("ok") is True, "解码器探测接口")
except Exception as e:                                  # noqa: BLE001
    FAIL.append(f"HTTP API 冒烟测试异常: {e}")
finally:
    if httpd:
        httpd.shutdown()


# --------------------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print(f"❌ {len(FAIL)} 项失败 / {PASS + len(FAIL)} 项")
    for f in FAIL:
        print("   ·", f)
    raise SystemExit(1)
print(f"✅ 全部 {PASS} 项通过")
