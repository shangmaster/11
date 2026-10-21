"""超星学习通签到协议层（零第三方依赖）。

所有 URL / 参数名 / 类型码都来自官方客户端实测，不要凭直觉改：
  · 活动列表  v2/apis/active/student/activelist
  · 活动详情  v2/apis/active/getPPTActiveInfo   <- activeSort 只有这里准
  · 提交签到  pptSign/stuSignajax
  · 照片上传  pan-yz.chaoxing.com/api/token + /upload

设计原则：本模块只做「纯函数」——拼 URL、解析 JSON、判定类型、组装参数。
不发起任何网络请求，方便离线自测（selfcheck.py 覆盖全部解析分支）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

# --------------------------------------------------------------------------
# 主机与路径
# --------------------------------------------------------------------------

HOST_MOBILE = "https://mobilelearn.chaoxing.com"
HOST_MOOC = "https://mooc1-api.chaoxing.com"
HOST_PAN = "https://pan-yz.chaoxing.com"
HOST_PASSPORT = "https://passport2.chaoxing.com"
HOST_IMOOC = "https://i.chaoxing.com"

PATH_ACTIVE_LIST = "/v2/apis/active/student/activelist"
PATH_ACTIVE_INFO = "/v2/apis/active/getPPTActiveInfo"
PATH_SIGN = "/pptSign/stuSignajax"
PATH_PRE_SIGN = "/pptSign/preSign"
PATH_CHECK_CODE = "/pptSign/checkSignCode"
PATH_COURSE_LIST = "/mycourse/backclazzdata"
PATH_PAN_TOKEN = "/api/token"
PATH_PAN_UPLOAD = "/upload"
PATH_TASK_LIST = "/ppt/activeAPI/taskactivelist"

# 官方 App 的 UA。服务端对 UA 敏感（缺 com.chaoxing.mobile 会被当成网页端），
# 保留 ChaoxingStudy 段即可，版本号可以随官方升级，不必精确匹配。
APP_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 "
    "(schild:0123456789abcdef) (device:0123456789abcdef) Language/zh_CN "
    "com.chaoxing.mobile/ChaoXingStudy_3_6_4_android_phone_1014_96_@0"
)

DEFAULT_APP_TYPE = "15"          # appType=15 就是 Android 学生端
DEFAULT_IFTIJIAO = "1"

# 二维码里可能出现的三种载荷形态（官方扫描器 / H5 活码 / 轮换码）
RE_SIGNIN = re.compile(r"^SIGNIN[:：](?P<rest>.+)$", re.S)
RE_WIDGET_E = re.compile(r"widget/sign/e\?(?P<q>[^\s]+)")
RE_WIDGET_SIGNIN = re.compile(r"widget/sign/signIn\?(?P<q>[^\s]+)")
RE_URL = re.compile(r"https?://[^\s\"'<>]+")
RE_DIGITS_ID = re.compile(r"^\d{6,}$")


# --------------------------------------------------------------------------
# 签到类型
# --------------------------------------------------------------------------

# 基础类型决定「必须提供什么才能签上」；附加要求（拍照/人脸/验证码）叠在上面。
KIND_LABELS = {
    "plain": "普通",
    "location": "位置",
    "qr": "二维码",
    "code": "签到码",
    "gesture": "手势",
    "unknown": "未知",
}

# otherId：稳定类型码（老字段，几乎所有活动都有）
OTHER_ID_KINDS = {
    0: "plain",      # 新建普通签到实测 otherId=0 且没有 activeSort
    1: "plain",
    2: "plain",      # 部分版本把「普通」编成 2
    3: "gesture",
    4: "location",
    5: "code",
    6: "qr",
    7: "qr",
    8: "qr",
}

# activeSort：细分码，来自活动详情，优先级最高
ACTIVE_SORT_KINDS = {
    1: "plain",      # 纯普通
    2: "plain",      # 普通 + 防作弊验证码
    3: "plain",      # 普通 + 拍照（拍照是附加要求，不是类型！）
    4: "location",   # 位置
    5: "location",   # 位置 + 人脸
    6: "qr",         # 二维码
    7: "qr",         # 二维码自动刷新
    8: "qr",         # 二维码 + 指定地点
    9: "code",       # 签到码
    11: "qr",        # 实测：活动名「二维码签到」，不带 enc 提交会回「签到失败，请重新扫描」
    16: "gesture",   # 手势（9 宫格轨迹）
}

KIND_NEEDS = {
    "plain": {"location": False, "qr": False, "code": False, "gesture": False},
    "location": {"location": True, "qr": False, "code": False, "gesture": False},
    "qr": {"location": False, "qr": True, "code": False, "gesture": False},
    "code": {"location": False, "qr": False, "code": True, "gesture": False},
    "gesture": {"location": False, "qr": False, "code": False, "gesture": True},
    "unknown": {"location": False, "qr": False, "code": False, "gesture": False},
}


def kind_from_name(name: str) -> str:
    """最后兜底：从活动名字猜类型。老师起名往往很直白。"""
    s = name or ""
    if not s:
        return ""
    if re.search(r"二维码|扫码|扫一扫", s):
        return "qr"
    if re.search(r"手势", s):
        return "gesture"
    if re.search(r"签到码|数字码|验证码签到", s):
        return "code"
    if re.search(r"位置|定位|签到地点", s):
        return "location"
    if re.search(r"普通|常规", s):
        return "plain"
    return ""


def _to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v)))
    except (TypeError, ValueError):
        return None


def _flag(v: Any) -> bool | None:
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y"):
        return True
    if s in ("0", "false", "no", "n"):
        return False
    return None


def strip_tags(v: Any) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", str(v))).strip()


# --------------------------------------------------------------------------
# URL 组装
# --------------------------------------------------------------------------

def build_task_list_url(course_id: str, class_id: str, uid: str,
                        host: str = HOST_MOBILE) -> str | None:
    """每门课的任务列表 —— **签到活动出现在这里**。

    这个接口比 /v2/apis/active/student/activelist 新，返回的是「当前这门课
    正在进行的所有活动」。实测踩过的坑：用 activelist 时，刚发布的签到
    完全看不到（那个接口返回的是已结束的历史），引擎一直显示「发现 0 个」，
    实际老师两分钟前就发了一个。
    """
    if not course_id or not class_id:
        return None
    qs = urlencode({"courseId": course_id, "classId": class_id, "uid": uid})
    return f"{host}{PATH_TASK_LIST}?{qs}"


def build_active_list_url(course_id: str, class_id: str, fid: str = "",
                          show_not_started: str = "0", now: int | None = None,
                          host: str = HOST_MOBILE) -> str | None:
    """活动列表。courseId / classId 缺一不可，参数名大小写与官方一致。"""
    if not course_id or not class_id:
        return None
    qs = urlencode({
        "fid": fid or "",
        "courseId": course_id,
        "classId": class_id,
        "showNotStartedActive": show_not_started,
        "_": str(now if now is not None else int(time.time() * 1000)),
    })
    return f"{host}{PATH_ACTIVE_LIST}?{qs}"


def build_active_info_url(active_id: str, now: int | None = None,
                          host: str = HOST_MOBILE) -> str | None:
    if not active_id:
        return None
    qs = urlencode({
        "activeId": active_id,
        "_": str(now if now is not None else int(time.time() * 1000)),
    })
    return f"{host}{PATH_ACTIVE_INFO}?{qs}"


def build_course_list_url(host: str = HOST_MOOC) -> str:
    qs = urlencode({"view": "json", "getTchClazzType": "1", "mcode": "", "rss": "1"})
    return f"{host}{PATH_COURSE_LIST}?{qs}"


def build_pan_token_url(puid: str, host: str = HOST_PAN) -> str:
    return f"{host}{PATH_PAN_TOKEN}?{urlencode({'puid': puid})}"


def build_pan_upload_url(host: str = HOST_PAN) -> str:
    return f"{host}{PATH_PAN_UPLOAD}"


# --------------------------------------------------------------------------
# 解析：活动列表 / 活动详情
# --------------------------------------------------------------------------

@dataclass
class Activity:
    active_id: str
    status: int = 0              # 1=进行中 2=已结束 0/缺省=未开始
    other_id: int | None = None
    active_sort: int | None = None
    if_photo: bool | None = None
    name: str = ""
    start_time: Any = ""
    class_id: str = ""
    course_id: str = ""
    # taskactivelist 的条目直接带这两个字段，省掉一次详情请求
    active_type: int | None = None
    url: str = ""

    @property
    def running(self) -> bool:
        return self.status == 1


@dataclass
class Kind:
    key: str = "unknown"
    needs_photo: bool = False
    needs_face: bool = False
    needs_vcode: bool = False
    from_name: bool = False
    is_sign: bool = True          # False = 这个活动根本不是签到（问卷/作业/考试）
    evidence: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.key, "未知")

    @property
    def needs_location(self) -> bool:
        return KIND_NEEDS.get(self.key, KIND_NEEDS["unknown"])["location"]

    @property
    def needs_qr(self) -> bool:
        return KIND_NEEDS.get(self.key, KIND_NEEDS["unknown"])["qr"]

    @property
    def needs_code(self) -> bool:
        return KIND_NEEDS.get(self.key, KIND_NEEDS["unknown"])["code"]

    @property
    def needs_gesture(self) -> bool:
        return KIND_NEEDS.get(self.key, KIND_NEEDS["unknown"])["gesture"]

    def describe(self) -> str:
        """给面板/日志看的一行判定说明，含判定依据。"""
        bits = [f"类型={self.label}"]
        if self.needs_photo:
            bits.append("要拍照")
        if self.needs_face:
            bits.append("要人脸")
        if self.needs_vcode:
            bits.append("要验证码")
        ev = self.evidence
        raw = " · ".join(
            f"{k}={v}" for k, v in (
                ("activeSort", ev.get("activeSort")),
                ("otherId", ev.get("otherId")),
                ("ifphoto", ev.get("ifphoto")),
            ) if v is not None
        )
        if raw:
            bits.append(f"依据:{raw}")
        if self.from_name:
            bits.append("(名字推断)")
        return " ".join(bits)


def _pick_id(*vals: Any) -> str:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if RE_DIGITS_ID.match(s):
            return s
    return ""


def extract_activities(payload: Any) -> list[Activity]:
    """把 activelist 的响应归一化成 Activity 列表。

    兼容 {data:{activeList:[...]}} / {activeList:[...]} / 裸数组 / data 为数组。
    """
    if not isinstance(payload, (dict, list)):
        return []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload.get("activeList"), list):
        rows = payload["activeList"]
    elif isinstance(payload.get("taskActiveList"), list):
        rows = payload["taskActiveList"]          # taskactivelist 的形态
    elif isinstance(payload.get("list"), list):
        rows = payload["list"]
    else:
        data = payload.get("data")
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict) and isinstance(data.get("activeList"), list):
            rows = data["activeList"]
        elif isinstance(data, dict) and isinstance(data.get("data"), dict) \
                and isinstance(data["data"].get("activeList"), list):
            rows = data["data"]["activeList"]
        elif isinstance(data, dict) and isinstance(data.get("activeList"), dict):
            rows = []
        else:
            rows = []

    out: list[Activity] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        aid = _pick_id(item.get("activeId"), item.get("activePrimaryId"), item.get("id"))
        if not aid:
            continue
        status = _to_int(item.get("activeStatus", item.get("status"))) or 0
        out.append(Activity(
            active_id=aid,
            status=status,
            other_id=_to_int(item.get("otherId")),
            active_sort=_to_int(item.get("activeSort")),
            if_photo=_flag(item.get("ifphoto")),
            name=strip_tags(item.get("nameOne") or item.get("name") or item.get("title") or ""),
            start_time=item.get("startTime") or item.get("start_time") or "",
            class_id=str(item.get("classId") or ""),
            course_id=str(item.get("courseId") or ""),
            active_type=_to_int(item.get("activeType")),
            url=str(item.get("url") or ""),
        ))
    return out


@dataclass
class ActiveInfo:
    active_id: str = ""
    active_type: int | None = None     # 2 = 签到（PPT 活动）；14 = 问卷；其他见 docs/01
    active_sort: int | None = None
    other_id: int | None = None
    if_photo: bool | None = None
    if_need_vcode: bool | None = None
    open_check_face: int | None = None
    if_refresh_ewm: int | None = None
    if_open_address: int | None = None
    number_count: int | None = None
    location_text: str = ""
    location_range: str = ""
    # 老师发布签到时设定的那个点。真实抓包里这三组是分开的：
    #   locationLatitude/Longitude      原始（可能是 BD-09）
    #   locationLatitude_gd/Longitude_gd 高德系（GCJ-02，跟地图页一致）
    # 有值就直接用，比拿地址文本去地理编码准得多。
    location_lat: str = ""
    location_lon: str = ""
    location_lat_gd: str = ""
    location_lon_gd: str = ""
    view_pic_path: str = ""            # ppt_ewm=签到 ppt_wq=问卷 ppt_zy=作业
    ewm_refresh_time: int | None = None
    name: str = ""
    status: int | None = None
    start_time: int | None = None
    end_time: int | None = None
    raw: dict = field(default_factory=dict)


def normalize_active_info(payload: Any) -> ActiveInfo:
    d = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        d = payload if isinstance(payload, dict) else {}
    if isinstance(d.get("data"), dict):
        d = d["data"]
    return ActiveInfo(
        active_id=str(d.get("activeId") or d.get("id") or ""),
        active_type=_to_int(d.get("activeType")),
        active_sort=_to_int(d.get("activeSort")),
        other_id=_to_int(d.get("otherId")),
        if_photo=_flag(d.get("ifphoto")),
        if_need_vcode=_flag(d.get("ifNeedVCode")),
        open_check_face=_to_int(d.get("openCheckFaceFlag") or d.get("ifOpenCheckFace") or d.get("ifface")),
        if_refresh_ewm=_to_int(d.get("ifrefreshewm")),
        if_open_address=_to_int(d.get("ifopenAddress")),
        number_count=_to_int(d.get("numberCount")),
        location_text=strip_tags(d.get("locationText") or ""),
        location_range=str(d.get("locationRange") or ""),
        location_lat=str(d.get("locationLatitude") or ""),
        location_lon=str(d.get("locationLongitude") or ""),
        location_lat_gd=str(d.get("locationLatitude_gd") or ""),
        location_lon_gd=str(d.get("locationLongitude_gd") or ""),
        view_pic_path=str(d.get("viewPicPath") or ""),
        ewm_refresh_time=_to_int(d.get("ewmRefreshTime")),
        name=strip_tags(d.get("name") or d.get("nameOne") or d.get("title") or ""),
        status=_to_int(d.get("status")),
        start_time=_to_int(d.get("starttime") or d.get("startTime")),
        end_time=_to_int(d.get("endtime") or d.get("endTime")),
        raw=d,
    )


def active_point(info: ActiveInfo | None) -> tuple[float, float] | None:
    """从活动详情里取老师设定的签到点（GCJ-02）。没有就返回 None。

    优先级：`_gd` 后缀（高德系，和地图页同一套坐标系）> 原始字段。
    """
    if info is None:
        return None

    def _num(v: str) -> float | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        # 服务端在没设点时会给 -1 / 0
        if f == 0 or f == -1 or abs(f) > 180:
            return None
        return f

    for la, lo in ((info.location_lat_gd, info.location_lon_gd),
                   (info.location_lat, info.location_lon)):
        a, b = _num(la), _num(lo)
        if a is not None and b is not None:
            # 判断是 lat/lon 还是写反了
            if 3.86 < a < 53.55 and 73.66 < b < 135.05:
                return a, b
            if 3.86 < b < 53.55 and 73.66 < a < 135.05:
                return b, a
    return None


def _other_kind(v: int | None) -> str:
    """otherId -> 类型。只认合法取值范围内的，脏数据忽略。

    实测见过 otherId=2000024683117 —— 那是把活动 ID 串进了类型字段，
    照表查会落到 unknown，但如果恰好低位能对上就会误判。所以先卡范围。
    """
    if v is None:
        return ""
    if not (0 <= v <= 20):
        return ""
    return OTHER_ID_KINDS.get(v, "")


def classify(info: ActiveInfo | None = None, act: Activity | None = None) -> Kind:
    """判定签到类型。

    优先级：活动详情 activeSort > 活动详情 otherId > 列表字段 > 名字兜底。
    注意 ifrefreshewm 只表示「二维码可以自动刷新」的能力位，不是类型标志，
    单独出现时不能把活动判成二维码（这是最容易踩的坑）。

    还有一道前置闸门：**只有 activeType=2 才是签到**。
    activelist 里混着作业(25)、考试、问卷(14)、讨论……它们的 activeSort
    是别的含义。实测一个「问卷」活动的 activeSort=6，照签到的表查就是「二维码」，
    会被当成签到去提交，白白发一次请求。
    """
    ev: dict = {}

    # 闸门：非签到活动直接判 false
    if info is not None and info.active_type is not None and info.active_type != 2:
        ev.update({"activeType": info.active_type, "activeSort": info.active_sort,
                   "otherId": info.other_id})
        return Kind(key="unknown", is_sign=False, evidence=ev)

    key = ""

    # 第一层：activeSort（最权威）
    if info is not None:
        ev.update({"activeSort": info.active_sort, "otherId": info.other_id,
                   "ifphoto": info.if_photo})
        if info.active_sort is not None:
            key = ACTIVE_SORT_KINDS.get(info.active_sort, "")
    if not key and act is not None:
        ev.setdefault("activeSort", act.active_sort)
        ev.setdefault("otherId", act.other_id)
        ev.setdefault("ifphoto", act.if_photo)
        if act.active_sort is not None:
            key = ACTIVE_SORT_KINDS.get(act.active_sort, "")

    # 第二层：活动名字。
    # activeSort 有值但不在表里（比如 11）= 新出现的类型码，此时 otherId
    # 往往也一起失准（实测 activeSort=11 + otherId=2 的活动叫「二维码签到」，
    # 套 otherId 会判成普通，提交不带 enc，服务端回「请重新扫描」）。
    # 所以这一步排在 otherId 前面。
    from_name = False
    if not key:
        nm = (info.name if info else "") or (act.name if act else "")
        key = kind_from_name(nm)
        from_name = bool(key)

    # 第三层：otherId —— 只认合法取值范围，脏数据直接忽略
    # （实测见过 otherId=2000024683117，那是活动 ID 串错了字段）
    if not key:
        oid = info.other_id if info is not None else (act.other_id if act is not None else None)
        key = _other_kind(oid)

    if not key:
        key = "unknown"

    photo = None
    for src in (info, act):
        if src is not None:
            v = getattr(src, "if_photo", None)
            if v is not None:
                photo = v
                break

    return Kind(
        key=key,
        needs_photo=bool(photo) or key == "photo",
        needs_face=bool(info and info.open_check_face == 1),
        needs_vcode=bool(info and info.if_need_vcode),
        from_name=from_name,
        evidence=ev,
    )


# --------------------------------------------------------------------------
# 签到参数组装
# --------------------------------------------------------------------------

def sign_uses_post(kind: str) -> bool:
    """官方 H5 页面：纯普通/防作弊用 GET，其余（位置/拍照/二维码/签到码）用 POST。"""
    return kind != "plain"


def build_sign_params(
    *,
    active_id: str,
    uid: str,
    fid: str,
    kind: str = "plain",
    course_id: str = "",
    name: str = "",
    device_code: str = "",
    validate: str = "",
    lat: float | None = None,
    lon: float | None = None,
    address: str = "",
    object_id: str = "",
    photo_result: str = "",
    sign_code: str = "",
    enc: str = "",
    app_type: str = DEFAULT_APP_TYPE,
    include_useragent: bool | None = None,
    force_location: bool = False,
) -> list[tuple[str, str]]:
    """组装 stuSignajax 参数（有序列表，保序是为了让抓包对比时逐字一致）。

    几个照抄官方页面的细节：
      · 拿不到定位时页面发 -1，非位置签到服务端接受 -1
      · useragent 字段只在 GET（纯普通/防作弊）时出现，POST 表单里没有
      · address / ifTiJiao / vp* 只在需要位置时发，别的时候别塞
      · force_location=True 用于「二维码 + 指定地点」(activeSort=8)：
        enc 和坐标要同时带，光看 kind 判断会漏掉坐标
    """
    needs_loc = force_location or KIND_NEEDS.get(kind, KIND_NEEDS["unknown"])["location"]
    if include_useragent is None:
        include_useragent = not sign_uses_post(kind)

    la = -1.0 if lat is None else float(lat)
    lo = -1.0 if lon is None else float(lon)

    pairs: list[tuple[str, str]] = [
        ("activeId", active_id),
        ("courseId", course_id),
        ("uid", uid),
        ("clientip", ""),
    ]
    if include_useragent:
        pairs.append(("useragent", ""))
    pairs += [
        ("latitude", f"{la:.6f}"),
        ("longitude", f"{lo:.6f}"),
        ("fid", fid),
        ("appType", app_type),
        ("name", name),
    ]
    if device_code:
        pairs.append(("deviceCode", device_code))
    if validate:
        pairs.append(("validate", validate))
    if object_id:
        pairs.append(("objectId", object_id))
    if photo_result:
        pairs.append(("photoResult", photo_result))
    if sign_code:
        pairs.append(("signCode", sign_code))
    if enc:
        pairs.append(("enc", enc))

    if needs_loc:
        pairs += [
            ("address", address),
            ("ifTiJiao", DEFAULT_IFTIJIAO),
            ("vpProbability", ""),
            ("vpStrategy", ""),
            ("currentFaceId", ""),
            ("ifCFP", "0"),
            ("faceEnc", ""),
            ("faceCode", ""),
        ]
    return pairs


def encode_pairs(pairs: list[tuple[str, str]]) -> str:
    return urlencode([(k, v) for k, v in pairs])


def build_sign_url(pairs: list[tuple[str, str]], host: str = HOST_MOBILE) -> str:
    return f"{host}{PATH_SIGN}?{encode_pairs(pairs)}"


# --------------------------------------------------------------------------
# 返回码翻译
# --------------------------------------------------------------------------

RESULT_OK = {"success", "success2"}

RESULT_MESSAGES = {
    "success": "签到成功",
    "success2": "签到成功（已记录）",
    "validate": "需要防作弊验证码（validate）",
    "您已签到过了": "已经签过，无需重复",
    "您已签到过了！": "已经签过，无需重复",
    "签到失败，请重新扫描": "二维码已失效或 enc 不对，请重新取码",
    "photoAuthError_PCR007": "服务端要求现场拍摄凭证（photoResult），objectId 不够",
    "请先登录再进行签到": "登录态失效，请更新 cookie",
    "活动已结束": "活动已结束",
    "签到已结束": "签到已结束",
}


def translate_result(text: str) -> tuple[bool, str]:
    """返回 (是否成功, 人话)。"""
    s = (text or "").strip()
    low = s.lower()
    if low in RESULT_OK:
        return True, RESULT_MESSAGES[low]
    # 「已经签过」算成功：幂等，不能报错（重复轮询时很常见）
    if "已签到" in s or "已签过" in s:
        return True, "已经签过，无需重复"
    if s in RESULT_MESSAGES:
        return False, RESULT_MESSAGES[s]
    if not s:
        return False, "空响应（可能被重定向到登录页）"
    return False, s[:200]


# --------------------------------------------------------------------------
# 二维码载荷解析
# --------------------------------------------------------------------------

@dataclass
class QrPayload:
    raw: str = ""
    active_id: str = ""
    enc: str = ""
    ewn_code: str = ""
    rcode: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.enc or self.rcode or self.ewn_code)

    def describe(self) -> str:
        if self.enc:
            return f"e?id={self.active_id} enc={self.enc[:12]}…"
        if self.ewn_code:
            return f"signIn?id={self.active_id} ewnCode={self.ewn_code}"
        if self.rcode:
            return f"SIGNIN rcode={self.rcode[:24]}…"
        return "无法识别的二维码"


def parse_qr(raw: str) -> QrPayload:
    """解析扫描到的二维码字符串，三种形态都吃：
      1) https://mobilelearn.chaoxing.com/widget/sign/e?id=<activeId>&enc=<enc>
      2) https://mobilelearn.chaoxing.com/widget/sign/signIn?activeId=<id>&ewnCode=<code>
      3) SIGNIN:<payload>  （官方 App 扫描器自己产的，交给 newsign/studentSign?rcode=）
    """
    s = (raw or "").strip()
    out = QrPayload(raw=s)
    if not s:
        return out

    m = RE_SIGNIN.match(s)
    if m:
        rest = m.group("rest").strip()
        out.rcode = s
        u = RE_URL.search(rest)
        if u:
            # 少数情况 SIGNIN: 后面还跟一条 H5 链接，继续挖
            inner = parse_qr(u.group(0))
            if inner.usable:
                inner.raw = s
                return inner
        return out

    u = RE_URL.search(s)
    url = u.group(0) if u else s

    m = RE_WIDGET_E.search(url)
    if m:
        q = _parse_query(m.group("q"))
        out.active_id = q.get("id", "")
        out.enc = q.get("enc", "")
        return out

    m = RE_WIDGET_SIGNIN.search(url)
    if m:
        q = _parse_query(m.group("q"))
        out.active_id = q.get("activeId", "") or q.get("id", "")
        out.ewn_code = q.get("ewnCode", "") or q.get("code", "")
        return out

    # 兜底：只要查询串里同时有 enc 和 id/activeId 就当二维码用
    if "?" in url:
        q = _parse_query(url.split("?", 1)[1])
        if q.get("enc"):
            out.active_id = q.get("id", "") or q.get("activeId", "")
            out.enc = q["enc"]
            return out

    # 也可能是纯 enc 串（调试时手输）
    if re.fullmatch(r"[0-9A-Fa-f]{16,64}", s):
        out.enc = s
    return out


def parse_server_qr_text(text: str) -> tuple[str, str]:
    """解析 `/sign/qrcode?activeId=X` 那张图解出来的内容。

    实测格式（三个活动都一样）：`<enc>-<13 位毫秒时间戳>`
        null-1792514345987      <- 学生身份 / 活动不在进行中：enc 被服务端抹成 null
        <32位hex>-1792514...    <- 有权限时才是真密钥

    返回 (enc, 说明)。enc 为空表示没拿到，说明里写原因。
    """
    s = (text or "").strip()
    if not s:
        return "", "二维码内容是空的"
    if s.startswith("null-"):
        return "", "服务端只给了时间戳，enc=null（没权限或活动不在进行中）"

    m = re.fullmatch(r"([0-9A-Fa-f]{16,64})[-_](\d{10,14})", s)
    if m:
        return m.group(1), "拿到 enc"

    # 万一返回的就是完整 H5 链接
    if s.startswith("http") or s.upper().startswith("SIGNIN"):
        q = parse_qr(s)
        if q.enc:
            return q.enc, "拿到 enc（H5 链接形态）"

    # 只有一段 hex 也认
    if re.fullmatch(r"[0-9A-Fa-f]{16,64}", s):
        return s, "拿到 enc（纯 hex 形态）"

    return "", f"没见过的二维码内容：{s[:40]}"


def _parse_query(qs: str) -> dict[str, str]:
    from urllib.parse import parse_qs
    out: dict[str, str] = {}
    for k, v in parse_qs(qs, keep_blank_values=True).items():
        if v:
            out[k] = v[0]
    return out


# --------------------------------------------------------------------------
# 课程列表解析
# --------------------------------------------------------------------------

@dataclass
class Course:
    course_id: str
    class_id: str
    name: str
    class_name: str = ""


def parse_courses(payload: Any) -> list[Course]:
    """backclazzdata -> [{courseId, classId, name}]。

    实测结构（2026 版，一个 53 个班级的账号验证过）：

        { result: 1, channelList: [
            { content: {
                id:   157462133,          <- 班级编号在这一层
                name: "24级物理学1",       <- 班级名
                course: { data: [
                    { id: 268194985,      <- 课程编号
                      name: "量子力学2026",  <- 课程名
                      clazzs: [...]       <- 老版本才有，新版本是 null
                    } ]
                }
            } }
        ] }

    老版本把 `clazzs` 挂在 `course.data[i]` 下面，新版本不放，班级信息直接平铺在
    `content` 上。两种都认：先看 clazzs，没有再回落 content.id / content.name。

    这里踩过一个坑：早期只读 clazzs，遇到新结构时 clazzs 为 null ->
    解析出 classId="" -> 被过滤掉 -> 界面永远显示「载入 0 个班级」，
    但登录态明明有效，很难看出问题在哪。
    """
    out: list[Course] = []
    seen: set[tuple[str, str]] = set()
    if not isinstance(payload, dict):
        return out
    channels = payload.get("channelList")
    if not isinstance(channels, list):
        return out

    def add(cid: str, class_id: str, cname: str, class_name: str) -> None:
        if not cid or not class_id:
            return
        key = (cid, class_id)
        if key in seen:
            return
        seen.add(key)
        out.append(Course(course_id=cid, class_id=class_id,
                          name=cname, class_name=class_name))

    for ch in channels:
        if not isinstance(ch, dict):
            continue
        content = ch.get("content")
        if not isinstance(content, dict):
            continue
        course = content.get("course")
        if isinstance(course, str):
            try:
                import json
                course = json.loads(course)
            except Exception:
                continue
        if not isinstance(course, dict):
            continue
        rows = course.get("data")
        if not isinstance(rows, list):
            continue

        # 班级信息可能平铺在 content 上（新版），也可能在 clazzs 里（老版）
        c_class_id = str(content.get("id") or "")
        c_class_name = strip_tags(content.get("name") or "")

        for row in rows:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("id") or "")
            cname = strip_tags(row.get("name") or "")
            clazzes = row.get("clazzs")
            emitted = False
            if isinstance(clazzes, list):
                for cz in clazzes:
                    if not isinstance(cz, dict):
                        continue
                    add(cid, str(cz.get("id") or ""), cname,
                        strip_tags(cz.get("name") or ""))
                    emitted = True
            if not emitted:
                add(cid, c_class_id, cname, c_class_name)
    return out


__all__ = [
    "HOST_MOBILE", "HOST_MOOC", "HOST_PAN", "HOST_PASSPORT",
    "APP_UA", "DEFAULT_APP_TYPE", "DEFAULT_IFTIJIAO",
    "KIND_LABELS", "OTHER_ID_KINDS", "ACTIVE_SORT_KINDS", "KIND_NEEDS",
    "Activity", "ActiveInfo", "Kind", "Course", "QrPayload",
    "build_active_list_url", "build_active_info_url", "build_course_list_url",
    "build_task_list_url",
    "build_pan_token_url", "build_pan_upload_url",
    "extract_activities", "normalize_active_info", "classify", "kind_from_name",
    "build_sign_params", "build_sign_url", "encode_pairs", "sign_uses_post",
    "translate_result", "RESULT_OK", "parse_qr", "parse_courses", "strip_tags",
]
