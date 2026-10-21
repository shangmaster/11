"""签到引擎：发现 -> 判定 -> 执行，一条流水线跑到底。

和浏览器插件的根本区别：插件要人打开页面，引擎是常驻的。所以这里做三件事：
  1. 轮询所有课程的进行中活动（毫秒级去重，不会重复签）
  2. 按 activeSort 判定类型，分派到对应执行器
  3. 二维码这一类不阻塞：挂起成 pending，任何一路扫码器投递 enc 就立刻补签

状态机（每个 activeId）：
    DISCOVERED -> CLASSIFIED -> (SIGNED | WAITING | FAILED | SKIPPED)
    WAITING  --收到 enc/code--> SIGNED
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import geo
from .protocol import (
    HOST_MOBILE, KIND_LABELS, PATH_PRE_SIGN,
    Activity, ActiveInfo, Kind, QrPayload,
    active_point,
    build_active_info_url, build_active_list_url, build_sign_params,
    build_sign_url, classify, extract_activities, normalize_active_info,
    parse_qr, sign_uses_post, translate_result,
)
from .upload import upload_photo_file

Event = dict[str, Any]
EventHook = Callable[[Event], None]


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "poll": {
        "activeSeconds": 5,       # 有进行中活动时的轮询间隔
        "idleSeconds": 12,        # 没活动时退避
        "maxCoursesPerRound": 40,
    },
    "sign": {
        "plain": True,
        "location": True,
        "qr": True,
        "code": False,            # 签到码要老师屏幕上的数字，默认不自动
        "gesture": False,
        "preSignWarmup": True,
    },
    "location": {
        "mode": "auto",           # auto=按 locationText 地理编码 / fixed=固定点 / manual=地图选点
        "datum": "gcj02",         # 地图页给的是 GCJ-02；高德/腾讯同系
        "point": None,            # [lat, lon]
        "address": "",            # 提交时的 address 文本，空则用 locationText
        "amapKey": "",
        "jitterMeters": 30,
        "useOsmFallback": True,
    },
    "photo": {
        "enabled": True,
        "file": "",               # 单张
        "album": [],              # 多张轮换
        "photoResult": "",        # 可选：现场凭证（见 docs/04）
    },
    "qr": {
        "pendingMinutes": 25,     # 活动结束后多久内还接受 enc
        "dedupeSeconds": 6,       # 同一张码重复投递的合并窗口
        # 先问服务端要二维码（/sign/qrcode?activeId=），拿不到再等图。
        # 服务端在学生身份下可能把 enc 抹成 null，那就退回等图，不影响流程。
        "serverSide": True,
        "serverSideRetrySeconds": 20,
    },
    "notify": {
        "bark": "",               # https://api.day.app/<key>
        "ntfy": "",               # https://ntfy.sh/<topic>
        "pushplus": "",
        "onlyResult": True,
    },
    "log": {"level": "info", "file": ""},
}


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    cfg = deep_merge(DEFAULT_CONFIG, raw)
    base = os.path.dirname(os.path.abspath(path))
    for key in ("file",):
        p = cfg["photo"].get(key) or ""
        if p and not os.path.isabs(p):
            cfg["photo"][key] = os.path.normpath(os.path.join(base, p))
    album = []
    for p in cfg["photo"].get("album") or []:
        album.append(p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p)))
    cfg["photo"]["album"] = album
    return cfg


# --------------------------------------------------------------------------
# 状态
# --------------------------------------------------------------------------

@dataclass
class Record:
    active_id: str
    course: str = ""
    name: str = ""
    kind: str = "unknown"
    state: str = "DISCOVERED"
    message: str = ""
    at: float = field(default_factory=time.time)
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "activeId": self.active_id, "course": self.course, "name": self.name,
            "kind": self.kind, "state": self.state, "message": self.message,
            "at": self.at, "detail": self.detail,
        }


class State:
    """已签/待签的持久化。重启后不会重复签到，也不会重复推送。"""

    def __init__(self, path: str):
        self.path = path
        self.data: dict[str, Any] = {"signed": {}, "pending": {}, "meta": {}}
        self.lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                self.data.update(d)
        except Exception:
            pass

    def save(self) -> None:
        if not self.path:
            return
        with self.lock:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    def is_signed(self, aid: str) -> bool:
        with self.lock:
            return aid in self.data["signed"]

    def mark_signed(self, aid: str, rec: Record) -> None:
        with self.lock:
            self.data["signed"][aid] = rec.to_dict()
            self.data["pending"].pop(aid, None)
            self.save()

    def mark_pending(self, aid: str, rec: Record, ttl: float) -> None:
        with self.lock:
            self.data["pending"][aid] = {**rec.to_dict(), "expireAt": time.time() + ttl}
            self.save()

    def pending(self) -> dict[str, dict]:
        with self.lock:
            now = time.time()
            alive = {k: v for k, v in self.data["pending"].items()
                     if (v.get("expireAt") or 0) > now}
            if len(alive) != len(self.data["pending"]):
                self.data["pending"] = alive
            return dict(alive)

    def mark_failed(self, aid: str, rec: Record) -> None:
        with self.lock:
            self.data.setdefault("failed", {})[aid] = rec.to_dict()
            self.save()


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------

class Engine:
    def __init__(self, cfg: dict, session, state: State,
                 on_event: EventHook | None = None, log: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.s = session
        self.state = state
        self.on_event = on_event or (lambda e: None)
        self._log = log or (lambda m: None)
        self.courses: list[dict] = []
        self._course_at = 0.0
        self._info_cache: dict[str, tuple[float, ActiveInfo]] = {}
        self._last_poll = 0.0
        self._qr_seen: dict[str, float] = {}
        self._photo_cursor = 0
        self._memo: dict[str, float] = {}      # activeId -> 处理尝试时间，防抖
        self._point: tuple[float, float] | None = None
        self._stop = threading.Event()
        self.stats = {"polls": 0, "found": 0, "signed": 0, "failed": 0, "qr": 0}

    # ---------------- 事件 ----------------

    def emit(self, level: str, code: str, title: str, **extra: Any) -> None:
        ev: Event = {"ts": time.time(), "level": level, "code": code, "title": title}
        ev.update(extra)
        try:
            self.on_event(ev)
        except Exception:
            pass
        self._log(f"[{level}] {title}" + (f" | {extra}" if extra else ""))

    # ---------------- 课程 ----------------

    def refresh_courses(self) -> list[dict]:
        from .protocol import build_course_list_url, parse_courses
        from .protocol import HOST_MOOC
        data, status, final = self.s.get_json(build_course_list_url(HOST_MOOC))
        if status == 0:
            self.emit("warn", "course_net", f"课程列表不可达: {str(data)[:60]}")
            return self.courses
        if "passport" in (final or ""):
            self.emit("error", "login", "登录态失效，请更新 cookie")
            return self.courses
        rows = parse_courses(data)
        self.courses = [
            {"courseId": c.course_id, "classId": c.class_id,
             "name": c.name, "className": c.class_name}
            for c in rows if c.course_id and c.class_id
        ]
        # 按配置过滤课程
        want = set(self.cfg.get("courses") or [])
        if want:
            self.courses = [c for c in self.courses
                            if c["courseId"] in want or c["name"] in want]
        self._course_at = time.time()
        self.emit("info", "courses", f"载入 {len(self.courses)} 个班级")
        return self.courses

    def _ensure_courses(self) -> None:
        if not self.courses or time.time() - self._course_at > 1800:
            self.refresh_courses()

    # ---------------- 发现 + 判定 ----------------

    def fetch_activities(self, course: dict) -> list[Activity]:
        """拉这门课的活动。

        优先用 `ppt/activeAPI/taskactivelist` —— 这是**唯一能看到刚发布的签到**
        的接口。老的 `v2/apis/active/student/activelist` 返回的是历史列表，
        老师两分钟前发的签到在它里面根本不存在（实测踩了一整轮）。
        新接口为空时才回退到老的，兼容不同版本的账号。
        """
        from .protocol import build_task_list_url

        acts: list[Activity] = []
        turl = build_task_list_url(course["courseId"], course["classId"],
                                   self.s.uid or "")
        if turl:
            data, status, final = self.s.get_json(turl)
            if status and "passport" in (final or ""):
                self.emit("error", "login", "登录态失效，请更新 cookie")
                return []
            acts = extract_activities(data)

        if not acts:
            url = build_active_list_url(course["courseId"], course["classId"],
                                        self.s.fid or self.cfg.get("fid", ""))
            if url:
                data, status, final = self.s.get_json(url)
                if status == 0:
                    return []
                if "passport" in (final or ""):
                    self.emit("error", "login", "登录态失效，请更新 cookie")
                    return []
                acts = extract_activities(data)

        for a in acts:
            a.course_id = a.course_id or course["courseId"]
            a.class_id = a.class_id or course["classId"]
        return acts

    def fetch_info(self, active_id: str, ttl: float = 90.0) -> ActiveInfo | None:
        hit = self._info_cache.get(active_id)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        data, status, _ = self.s.get_json(build_active_info_url(active_id))
        if status == 0 or not isinstance(data, dict):
            return None
        if data.get("result") not in (1, "1", True):
            return None
        info = normalize_active_info(data)
        self._info_cache[active_id] = (time.time(), info)
        return info

    # ---------------- 执行器 ----------------

    def resolve_point(self, info: ActiveInfo | None) -> tuple[float, float, str, str]:
        """决定这次位置签到提交哪个点。

        返回 (lat, lon, address, datum)；坐标解不出来时返回 (-1.0, -1.0, ...)，
        优先级：地图手选 > 老师设定的点 > 配置固定点 > 按 locationText 地理编码。
        """
        loc = self.cfg["location"]
        datum = loc.get("datum") or "gcj02"
        target_text = info.location_text if info else ""

        # 1) 手动在地图上选的点优先（用户显式指定就尊重它）
        if self._point:
            lat, lon = self._point
            return lat, lon, (loc.get("address") or target_text), datum

        # 2) 老师发布签到时在地图上点的那个点 —— 最准，不用猜
        #    getPPTActiveInfo 里的 locationLatitude_gd / locationLongitude_gd
        #    就是这个点（高德系 = GCJ-02，和本项目地图页同一套坐标系）
        pt = active_point(info)
        if pt:
            return pt[0], pt[1], (loc.get("address") or target_text), "gcj02"

        # 3) 配置里写死的点
        if loc.get("mode") == "fixed" and loc.get("point"):
            lat, lon = float(loc["point"][0]), float(loc["point"][1])
            return lat, lon, (loc.get("address") or target_text), datum

        # 4) 按老师的地址文本地理编码（老师没在地图上标点时才走到这）
        if target_text:
            hit = self._geocode(target_text)
            if hit:
                return hit[0], hit[1], (loc.get("address") or target_text), "gcj02"

        # 5) 兜底：-1 会让服务端判"未定位"，但至少请求格式合法
        return -1.0, -1.0, (loc.get("address") or target_text), datum

    def _geocode(self, text: str) -> tuple[float, float, str] | None:
        loc = self.cfg["location"]

        def fetcher(url, headers=None):
            st, body, _ = self.s.request(url, headers=headers or {})
            return st, body

        key = loc.get("amapKey") or ""
        if key:
            pt = geo.geocode_amap(text, key, fetcher)
            if pt:
                return pt[0], pt[1], "amap"
        if loc.get("useOsmFallback", True):
            pt = geo.geocode_osm(text, fetcher)
            if pt:
                g = geo.wgs84_to_gcj02(pt[0], pt[1])
                return g[0], g[1], "osm"
        return None

    def pre_sign(self, act: Activity) -> None:
        """官方客户端的预热请求。H5 页面直接签也行，但先打一下更像真机。"""
        if not self.cfg["sign"].get("preSignWarmup", True):
            return
        from urllib.parse import urlencode
        qs = urlencode({
            "activePrimaryId": act.active_id,
            "classId": act.class_id,
            "uid": self.s.uid,
            "chatId": "",
            "general": "",
            "sys": "1", "ls": "1", "appType": "15", "ut": "s",
            "_": str(int(time.time() * 1000)),
        })
        try:
            self.s.request(f"{HOST_MOBILE}{PATH_PRE_SIGN}?{qs}")
        except Exception:
            pass

    def submit(self, act: Activity, kind: Kind, *,
               enc: str = "", sign_code: str = "",
               object_id: str = "", photo_result: str = "",
               point: tuple[float, float, str, str] | None = None) -> Record:
        """真正发签到请求。返回 Record（state=SIGNED/FAILED）。"""
        rec = Record(active_id=act.active_id, course=act.course_id,
                     name=act.name or (kind.label + "签到"), kind=kind.key)
        info = self.fetch_info(act.active_id)
        address = ""
        lat = lon = -1.0
        # activeSort=8 是「二维码 + 指定地点」：enc 和坐标要同时带
        force_loc = bool(info and info.active_sort == 8)
        if kind.needs_location or force_loc:
            p = point or self.resolve_point(info)
            lat, lon, address, datum = p
            if (lat, lon) != (-1.0, -1.0):
                lat, lon = geo.to_gcj02(lat, lon, datum)
                rng_m = float(self.cfg["location"].get("jitterMeters") or 0)
                if rng_m > 0:
                    lat, lon = geo.jitter(lat, lon, rng_m, random.Random())
                lat, lon = round(lat, 6), round(lon, 6)

        # 拍照：优先用调用方给的，其次配置里的本地图
        if kind.needs_photo or kind.key == "photo":
            if not object_id and self.cfg["photo"].get("enabled", True):
                path = self._pick_photo()
                if path:
                    up = upload_photo_file(self.s, self.s.uid, path)
                    if up.ok:
                        object_id = up.object_id
                        self.emit("info", "upload", f"照片已上传 {os.path.basename(path)}",
                                  objectId=object_id)
                    else:
                        self.emit("warn", "upload", f"照片上传失败: {up.message}")
            photo_result = photo_result or self.cfg["photo"].get("photoResult") or ""

        params = build_sign_params(
            active_id=act.active_id,
            uid=self.s.uid,
            fid=self.s.fid or str(self.cfg.get("fid") or ""),
            kind=kind.key,
            course_id=act.course_id,
            name=self.s.uname or self.cfg.get("uname", ""),
            device_code=self.cfg.get("deviceCode") or "",
            lat=lat, lon=lon,
            address=address,
            object_id=object_id,
            photo_result=photo_result,
            sign_code=sign_code,
            enc=enc,
            force_location=force_loc,
        )

        if self.cfg["sign"].get("preSignWarmup", True):
            self.pre_sign(act)

        if sign_uses_post(kind.key):
            from .protocol import encode_pairs
            status, text, final = self.s.post_form(
                f"{HOST_MOBILE}/pptSign/stuSignajax",
                dict(params),
                headers={"Referer": f"https://mobilelearn.chaoxing.com/newsign/preSign"
                                    f"?activeId={act.active_id}"},
            )
        else:
            status, text, final = self.s.request(build_sign_url(params))

        ok, human = translate_result(text)
        if status == 0:
            ok, human = False, f"网络错误: {text[:80]}"
        if "passport" in (final or ""):
            ok, human = False, "登录态失效，被重定向到登录页"

        rec.state = "SIGNED" if ok else "FAILED"
        rec.message = human
        rec.detail = {
            "params": dict(params), "response": (text or "")[:400],
            "lat": lat, "lon": lon, "address": address,
            "objectId": object_id, "enc": enc[:16] + "…" if enc else "",
        }
        if ok:
            self.stats["signed"] += 1
            self.state.mark_signed(act.active_id, rec)
            self.emit("ok", "signed", f"✅ {rec.name}（{kind.label}）签到成功", record=rec.to_dict())
        else:
            self.stats["failed"] += 1
            self.state.mark_failed(act.active_id, rec)
            self.emit("error", "sign_failed", f"❌ {rec.name}（{kind.label}）{human}",
                      record=rec.to_dict())
        return rec

    def _pick_photo(self) -> str:
        album = [p for p in (self.cfg["photo"].get("album") or []) if p and os.path.exists(p)]
        single = self.cfg["photo"].get("file") or ""
        if album:
            path = album[self._photo_cursor % len(album)]
            self._photo_cursor += 1
            return path
        if single and os.path.exists(single):
            return single
        return ""

    # ---------------- 二维码 ----------------

    def try_server_qr(self, active_id: str) -> tuple[str, str]:
        """先问服务端要二维码，拿不到再退回「等图」。

        接口：GET /sign/qrcode?activeId=<id>
        实测（2026-10）：返回一张 115×115 的二维码 JPEG，
        内容是 `<enc>-<13 位毫秒时间戳>`，例如 `null-1792514345987`。

        `enc` 是 null 有两种可能：
          · 活动不在进行中（我试的三个活动都不是进行中的真签到）
          · 学生身份没权限拿密钥
        所以每次发现二维码签到都试一次：是第一种就赚了，直接签完；
        是第二种就退回等图，不影响原有流程。
        """
        if not self.cfg["qr"].get("serverSide", True):
            return "", "服务端取码已关闭"
        from .protocol import HOST_MOBILE, parse_server_qr_text

        url = f"{HOST_MOBILE}/sign/qrcode?activeId={active_id}"
        try:
            status, body, _ = self.s.request_bytes(url)
        except AttributeError:
            # 老 Session 没有 request_bytes
            status, body, _ = 0, b"", url
        if status != 200 or not body:
            return "", f"没拿到二维码（HTTP {status}）"
        if body[:3] != b"\xff\xd8\xff":
            head = body[:40].decode("utf-8", "replace")
            return "", f"返回的不是图片：{head}"

        from . import qr as qrdecode
        res = qrdecode.decode_bytes(body)
        if not res.ok:
            return "", f"二维码图片解不开：{res.message}"

        enc, why = parse_server_qr_text(res.first)
        self.emit("info", "server_qr", f"服务端二维码：{res.first[:40]} → {why}",
                  activeId=active_id)
        return enc, why

    def feed_qr(self, raw: str | bytes, source: str = "manual") -> list[Record]:
        """任何一路扫码器把码投进来（文本或图片字节）。返回本次触发的签到结果。

        三种形态都能吃：
          · 二维码原文（H5 活码 / SIGNIN: / 轮换码）
          · 图片字节（自己解）
          · 整段分享文本（手机分享过来的消息，里面有链接）
        """
        texts: list[str] = []
        if isinstance(raw, bytes):
            from . import qr as qrdecode
            res = qrdecode.decode_bytes(raw)
            if not res.ok:
                self.emit("warn", "qr_decode", f"图片解码失败: {res.message}", source=source)
                return []
            texts = res.texts
            self.stats["qr"] += 1
        else:
            texts = [str(raw)]

        results: list[Record] = []
        for text in texts:
            payload = parse_qr(text)
            if not payload.usable:
                continue
            # 去重：同一张码连续投递（轮换码每 30 秒变一次，但 enc 常常不变）
            key = payload.enc or payload.ewn_code or payload.rcode
            now = time.time()
            if key in self._qr_seen and now - self._qr_seen[key] < float(
                    self.cfg["qr"].get("dedupeSeconds") or 6):
                continue
            self._qr_seen[key] = now
            self.emit("info", "qr_decoded", f"取到二维码 {payload.describe()}", source=source)
            rec = self.sign_by_qr(payload)
            if rec:
                results.append(rec)
        return results

    def sign_by_qr(self, payload: QrPayload) -> Record | None:
        """拿到 enc 就能签，不需要事先知道 activeId。"""
        aid = payload.active_id
        act = Activity(active_id=aid or "", status=1)
        if aid:
            info = self.fetch_info(aid)
            if info:
                act.course_id = str(info.raw.get("courseId") or "")
                act.class_id = str(info.raw.get("classId") or "")
                act.name = info.name
        if not act.course_id:
            # 详情拿不到就去活动列表里找一次
            self._ensure_courses()
            for c in self.courses:
                for a in self.fetch_activities(c):
                    if a.active_id == aid:
                        act = a
                        break
                if act.active_id == aid and act.course_id:
                    break

        # 二维码签到可能同时要求「指定地点」（activeSort=8）
        info = self.fetch_info(aid) if aid else None
        kind = classify(info) if info else Kind(key="qr")
        kind.key = "qr"

        if not aid and not payload.rcode:
            self.emit("warn", "qr_incomplete", "二维码里没有活动编号，无法提交")
            return None

        return self.submit(act, kind, enc=payload.enc or "",
                           sign_code=payload.ewn_code or "")

    # ---------------- 一轮轮询 ----------------

    def poll_once(self) -> list[Record]:
        self.stats["polls"] += 1
        self._ensure_courses()
        out: list[Record] = []
        found_running = False
        cfg_sign = self.cfg["sign"]
        pending = self.state.pending()

        for course in self.courses[: int(self.cfg["poll"].get("maxCoursesPerRound") or 40)]:
            for act in self.fetch_activities(course):
                if not act.running:
                    continue
                found_running = True
                self.stats["found"] += 1
                if self.state.is_signed(act.active_id):
                    continue
                if act.active_id in pending:
                    continue
                # 同一活动每 45 秒最多评估一次，避免刷爆详情接口
                last = self._memo.get(act.active_id, 0)
                if time.time() - last < 45:
                    continue
                self._memo[act.active_id] = time.time()

                info = self.fetch_info(act.active_id)
                kind = classify(info, act)
                if not kind.is_sign:
                    # activelist 里混着作业(25)、考试、问卷(14)、讨论……
                    # 它们的 activeSort 是别的含义，照签到表查会被误判成二维码，
                    # 然后白发一次提交请求。这里必须先拦掉。
                    self._log(f"  跳过非签到活动：{act.name or course['name']}"
                              f"（activeType={getattr(info, 'active_type', None)}）")
                    continue
                self.emit("info", "classified",
                          f"发现签到：{act.name or course['name']} · {kind.describe()}",
                          activeId=act.active_id, kind=kind.key)

                if not cfg_sign.get(kind.key, False):
                    self.emit("info", "skipped", f"按配置跳过 {KIND_LABELS.get(kind.key)} 签到",
                              activeId=act.active_id)
                    continue

                if kind.key == "qr":
                    # 先试服务端直出二维码：能拿到 enc 就当场签完，不用等图
                    enc, why = self.try_server_qr(act.active_id)
                    if enc:
                        self.emit("ok", "server_qr_hit",
                                  f"🔑 服务端直出 enc，直接签：{act.name}",
                                  activeId=act.active_id)
                        out.append(self.submit(act, kind, enc=enc))
                        continue
                    # 拿不到再挂起等图
                    ttl = float(self.cfg["qr"].get("pendingMinutes") or 25) * 60
                    self.state.mark_pending(act.active_id, Record(
                        active_id=act.active_id, course=act.course_id,
                        name=act.name, kind=kind.key, state="WAITING"), ttl)
                    self.emit("info", "waiting_qr",
                              f"⏳ 二维码签到待取码：{act.name}（{why}）",
                              activeId=act.active_id)
                    continue

                if kind.key == "code" and not cfg_sign.get("code"):
                    continue

                # 位置签到：解析不出坐标就先别发，避免留下"未定位"记录
                if kind.needs_location:
                    p = self.resolve_point(info)
                    if p[0] == -1.0:
                        self.emit("warn", "no_point",
                                  f"位置签到缺坐标：{act.name}（地址文本「{p[2]}」解析失败，"
                                  f"请在地图上选点）", activeId=act.active_id)
                        ttl = float(self.cfg["qr"].get("pendingMinutes") or 25) * 60
                        self.state.mark_pending(act.active_id, Record(
                            active_id=act.active_id, course=act.course_id,
                            name=act.name, kind=kind.key, state="WAITING"), ttl)
                        continue

                out.append(self.submit(act, kind))

        self._last_poll = time.time()
        self._next_interval = (float(self.cfg["poll"].get("activeSeconds") or 5)
                               if found_running
                               else float(self.cfg["poll"].get("idleSeconds") or 12))
        return out

    # ---------------- 常驻 ----------------

    def run_forever(self, max_rounds: int = 0) -> None:
        rounds = 0
        self.emit("info", "start", "引擎启动")
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as e:                  # noqa: BLE001
                self.emit("error", "poll", f"轮询异常: {e}")
            rounds += 1
            if max_rounds and rounds >= max_rounds:
                break
            wait = getattr(self, "_next_interval", 8.0)
            self._stop.wait(wait)
        self.emit("info", "stop", "引擎停止")

    def stop(self) -> None:
        self._stop.set()

    # ---------------- 运行时控制（给手机端 API 用） ----------------

    def set_point(self, lat: float, lon: float, datum: str = "gcj02") -> None:
        g = geo.to_gcj02(lat, lon, datum)
        self._point = g
        self.emit("info", "point", f"选点已更新 {g[0]:.6f},{g[1]:.6f}")

    def clear_point(self) -> None:
        self._point = None

    def set_photo(self, path: str) -> bool:
        if path and os.path.exists(path):
            self.cfg["photo"]["file"] = path
            return True
        return False

    def location_hints(self, limit: int = 5) -> list[str]:
        """老师最近要求过的签到地点，给地图页做一键跳转。"""
        out: list[str] = []
        seen: set[str] = set()
        cutoff = time.time() - 3600
        for ts, info in sorted(self._info_cache.values(), key=lambda x: -x[0]):
            if ts < cutoff:
                continue
            t = (info.location_text or "").strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
            if len(out) >= limit:
                break
        return out

    def status(self) -> dict:
        return {
            "courses": len(self.courses),
            "signed": len(self.state.data.get("signed") or {}),
            "pending": list(self.state.pending().keys()),
            "stats": self.stats,
            "point": self._point,
            "photo": self.cfg["photo"].get("file") or "",
            "lastPoll": self._last_poll,
            "login": {"uid": self.s.uid, "fid": self.s.fid, "uname": self.s.uname},
        }


__all__ = ["Engine", "State", "Record", "DEFAULT_CONFIG", "load_config", "deep_merge"]
