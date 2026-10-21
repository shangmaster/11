#!/usr/bin/env python3
"""签到哨兵 · 命令行入口。

    python run.py doctor                        # 环境自检（解码器/依赖/网络）
    python run.py login --cookie "..."          # 导入浏览器 cookie 并验证
    python run.py courses                       # 列出课程/班级
    python run.py watch                         # 常驻轮询（推荐配合 serve 一起）
    python run.py serve --port 8848             # 只起本地 API + 地图选点
    python run.py all                           # watch + serve（手机端用这个）
    python run.py qr --file qr.png              # 手动投一张二维码
    python run.py qr --text "https://mobilelearn.chaoxing.com/widget/sign/e?..." 
    python run.py point --lat 30.5 --lon 114.3  # 设置位置签到的点
    python run.py sign --active 6000059680136   # 立刻签某个活动
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
except Exception:
    pass

from cxsign import qr as qrdecode                     # noqa: E402
from cxsign.engine import Engine, State, load_config  # noqa: E402
from cxsign.net import Session                        # noqa: E402
from cxsign.notify import Notifier                    # noqa: E402
from cxsign.server import EventBus, serve             # noqa: E402

DATA_DIR = os.path.join(HERE, "data")


def _ensure_data() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _new_session(args, cfg) -> Session:
    _ensure_data()
    cookie_file = args.cookie_file or os.path.join(DATA_DIR, "cookie.json")
    s = Session(cookie_file=cookie_file)
    if getattr(args, "cookie", ""):
        from cxsign.server import extract_cookie
        n = s.set_cookies(extract_cookie(args.cookie) or args.cookie)
        print(f"导入 cookie {n} 条")
    if not s.uid:
        s.uid = str(cfg.get("uid") or "")
    if not s.fid:
        s.fid = str(cfg.get("fid") or "")
    if not s.uname:
        s.uname = str(cfg.get("uname") or "")
    s.cookie_file = cookie_file
    return s


def _build(args, cfg):
    s = _new_session(args, cfg)
    bus = EventBus()
    notifier = Notifier(cfg.get("notify"))

    def hook(ev):
        bus.push(ev)
        if ev.get("level") in ("ok", "error") or not cfg["notify"].get("onlyResult", True):
            notifier.send(ev.get("title", ""),
                          json.dumps(ev.get("record"), ensure_ascii=False)[:300]
                          if ev.get("record") else "",
                          level=ev.get("level", "info"))

    def log(msg):
        if cfg.get("log", {}).get("level") == "quiet":
            return
        print(msg, flush=True)

    state = State(os.path.join(DATA_DIR, "state.json"))
    eng = Engine(cfg, s, state, on_event=hook, log=log)
    return eng, bus


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_doctor(args, cfg) -> int:
    print("== 签到哨兵 环境自检 ==")
    print(f"Python      : {sys.version.split()[0]}")
    print(f"工作目录    : {HERE}")
    print(f"配置文件    : {args.config or '(默认)'}")
    bs = qrdecode.backends()
    print(f"二维码解码  : {', '.join(bs) if bs else '无（安装 pyzbar/opencv/zbarimg）'}")
    try:
        from PIL import Image  # noqa: F401
        print("Pillow      : 有")
    except Exception:
        print("Pillow      : 无（pyzbar 后端需要）")
    for d in ("mobilelearn.chaoxing.com", "passport2.chaoxing.com", "pan-yz.chaoxing.com"):
        try:
            import socket
            ip = socket.gethostbyname(d)
            print(f"DNS {d:<32}: {ip}")
        except Exception as e:
            print(f"DNS {d:<32}: 失败 {e}")
    s = _new_session(args, cfg)
    if s.cookie_file and os.path.exists(s.cookie_file):
        ok, why = s.probe_login()
        print(f"登录态      : {'有效' if ok else '无效'}（{why}）")
        print(f"uid/fid     : {s.uid or '-'} / {s.fid or '-'}")
    else:
        print("登录态      : 还没导 cookie（python run.py login --cookie \"...\"）")
    return 0


def cmd_login(args, cfg) -> int:
    s = _new_session(args, cfg)

    account = args.account
    password = args.password

    # 什么都没给就交互问一句，省得用户去翻文档
    if not args.cookie and not account:
        print("两种登录方式：")
        print("  1) 账号密码   python run.py login --account 你的手机号 --password 你的密码")
        print("  2) 粘贴 cookie python run.py login --cookie \"_uid=...; fid=...; ...\"")
        print("")
        try:
            account = input("账号（直接回车跳过）：").strip()
        except (EOFError, KeyboardInterrupt):
            account = ""
        if account:
            import getpass
            try:
                password = getpass.getpass("密码（输入时不显示）：")
            except Exception:
                password = input("密码：").strip()

    if account:
        from cxsign.net import password_login
        ok, why = password_login(s, account, password or "", s.fid or "")
        print(("✅ " if ok else "❌ ") + why)
        if not ok:
            print("账号开了图形验证码/二次验证的话，密码登录会被拦 ——")
            print("改用 cookie 方式：电脑浏览器登录后复制 Cookie 整行。")
            return 1
    else:
        if not args.cookie:
            print("cookie 是空的，什么都没做")
            return 2
        ok, why = s.probe_login()
        print(("✅ " if ok else "❌ ") + why)
        if not ok:
            return 1

    # 密码登录后 cookie 已经在 jar 里了，再探一次：既复核登录态，也顺手同步 uid/fid
    if not s.uid or not s.fid:
        s.probe_login()
    path = s.save()
    print(f"已保存: {path}")
    print(f"uid={s.uid or '-'}  fid={s.fid or '-'}  name={s.uname or '-'}")
    if not s.fid:
        print("⚠️ 没拿到 fid。有些账号登录响应里不带，改用 cookie 方式最稳")
    return 0


def cmd_courses(args, cfg) -> int:
    eng, _ = _build(args, cfg)
    rows = eng.refresh_courses()
    if not rows:
        print("没拿到课程，先检查登录态")
        return 1
    for c in rows:
        print(f"{c['courseId']:<14} {c['classId']:<12} {c['name']} / {c['className']}")
    return 0


def cmd_watch(args, cfg) -> int:
    eng, bus = _build(args, cfg)
    stop = threading.Event()

    def _sig(_signum, _frame):
        stop.set()
        eng.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _sig)
        except (ValueError, AttributeError):
            pass

    if args.serve or args.command in ("all", "serve"):
        httpd = serve(eng, bus, args.host, args.port, args.token)
        print(f"本地 API: http://{args.host}:{args.port}/  地图: /map")
    else:
        httpd = None

    t = threading.Thread(target=eng.run_forever, daemon=True)
    t.start()
    print("引擎已启动，Ctrl+C 停止")
    while not stop.is_set():
        time.sleep(0.5)
    eng.stop()
    if httpd:
        httpd.shutdown()
    print("已停止")
    return 0


def cmd_serve(args, cfg) -> int:
    return cmd_watch(args, cfg)


def cmd_qr(args, cfg) -> int:
    eng, _ = _build(args, cfg)
    if args.file:
        res = qrdecode.decode_file(args.file)
        if not res.ok:
            print(f"❌ 解码失败: {res.message}")
            return 1
        print(f"解码后端 {res.backend}，拿到 {len(res.texts)} 个码：")
        for t in res.texts:
            print("  " + t[:160])
        recs = eng.feed_qr(open(args.file, "rb").read(), source="cli-file")
    else:
        text = args.text or sys.stdin.read()
        recs = eng.feed_qr(text, source="cli-text")
    if not recs:
        print("没有产生签到（码可能不匹配任何进行中的活动，或已签过）")
        return 0
    for r in recs:
        print(("✅ " if r.state == "SIGNED" else "❌ ") + f"{r.name}: {r.message}")
    return 0


def cmd_point(args, cfg) -> int:
    eng, _ = _build(args, cfg)
    eng.set_point(args.lat, args.lon, args.datum)
    print(f"选点: {eng._point[0]:.6f}, {eng._point[1]:.6f} ({args.datum})")  # noqa: SLF001
    return 0


def cmd_sign(args, cfg) -> int:
    eng, _ = _build(args, cfg)
    from cxsign.server import _sign_by_id
    rec = _sign_by_id(eng, args.active, args.kind or "")
    print(("✅ " if rec.get("state") == "SIGNED" else "❌ ")
          + f"{rec.get('name')} {rec.get('message')}")
    return 0 if rec.get("state") == "SIGNED" else 1


# --------------------------------------------------------------------------

def cmd_probe_photo(args, cfg) -> int:
    """分析抓到的 photoResult，判断能不能自己造。"""
    from cxsign.photoprobe import analyze, format_report
    raw = args.text or ""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            raw = fh.read()
    if not raw.strip():
        print("用法：")
        print('  python run.py probe-photo --text "<抓到的那串>"')
        print("  python run.py probe-photo --file photoResult.txt")
        print("")
        print("不知道从哪抓？见 docs/04-拍照的硬边界.md 的「绕法 2」。")
        return 2
    print(format_report(analyze(raw)))
    return 0


def cmd_upload_test(args, cfg) -> int:
    from cxsign.uploadtest import run as _run
    s = _new_session(args, cfg)
    return _run(args, cfg, s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run.py", description="签到哨兵 · 学习通自动签到引擎")
    ap.add_argument("command", nargs="?", default="doctor",
                    choices=["doctor", "login", "courses", "watch", "serve", "all",
                             "qr", "point", "sign", "probe-photo", "upload-test"])
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--cookie", default="", help="浏览器导出的 cookie 串")
    ap.add_argument("--cookie-file", default="", help="cookie.json 路径")
    ap.add_argument("--account", default="", help="登录用手机号（login 子命令）")
    ap.add_argument("--password", default="", help="登录用密码（login 子命令）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8848)
    ap.add_argument("--token", default="", help="本地 API 访问令牌（对外暴露时必设）")
    ap.add_argument("--serve", action="store_true", help="watch 时同时起本地 API")
    ap.add_argument("--file", default="", help="二维码图片路径")
    ap.add_argument("--text", default="", help="二维码原文 / 分享文本 / photoResult 值")
    ap.add_argument("--lat", type=float, default=0.0)
    ap.add_argument("--lon", type=float, default=0.0)
    ap.add_argument("--datum", default="gcj02", choices=["gcj02", "wgs84", "bd09"])
    ap.add_argument("--active", default="", help="活动编号")
    ap.add_argument("--kind", default="", help="强制类型 plain/location/qr/code")
    args = ap.parse_args(argv)

    cfg = load_config(args.config) if os.path.exists(args.config) else load_config_dict()

    handlers = {
        "doctor": cmd_doctor, "login": cmd_login, "courses": cmd_courses,
        "watch": cmd_watch, "serve": cmd_serve, "all": cmd_watch,
        "qr": cmd_qr, "point": cmd_point, "sign": cmd_sign,
        "probe-photo": cmd_probe_photo, "upload-test": cmd_upload_test,
    }
    return handlers[args.command](args, cfg)


def load_config_dict() -> dict:
    from cxsign.engine import DEFAULT_CONFIG, deep_merge
    return deep_merge(DEFAULT_CONFIG, {})


if __name__ == "__main__":
    raise SystemExit(main())
