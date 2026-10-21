"""找一个刚发的签到：扫全部课程的进行中活动，把 activeType / activeSort / 名字全打出来，
然后对每个都试一次 /sign/qrcode，看服务端给不给真 enc。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.engine import Engine, State, DEFAULT_CONFIG, deep_merge   # noqa: E402
from cxsign.net import Session                                        # noqa: E402
from cxsign.protocol import (                                         # noqa: E402
    HOST_MOOC, build_active_list_url, build_course_list_url,
    classify, extract_activities, normalize_active_info, parse_courses,
    build_active_info_url,
)

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")


def main() -> int:
    s = Session(cookie_file=COOKIE)
    print(f"uid={s.uid} fid={s.fid}")

    data, st, _ = s.get_json(build_course_list_url(HOST_MOOC))
    courses = parse_courses(data)
    print(f"课程 {len(courses)} 个，开始扫进行中的活动…\n")

    running = []
    for i, c in enumerate(courses):
        url = build_active_list_url(c.course_id, c.class_id, s.fid or "")
        if not url:
            continue
        d, st2, _ = s.get_json(url)
        for a in extract_activities(d):
            if a.status == 1:
                running.append((a, c))
        if (i + 1) % 15 == 0:
            print(f"  …扫到 {i+1}/{len(courses)}，已发现 {len(running)} 个进行中")

    print(f"\n进行中的活动：{len(running)} 个")
    if not running:
        print("一个都没有 —— 可能老师还没发，或者活动立刻结束了")
        return 1

    eng = Engine(deep_merge(DEFAULT_CONFIG, {}), s, State(""), on_event=lambda e: None)

    for a, c in running:
        info = eng.fetch_info(a.active_id)
        kind = classify(info, a)
        at = getattr(info, "active_type", None)
        print("=" * 74)
        print(f"activeId   : {a.active_id}")
        print(f"课程       : {c.name} / {c.class_name}")
        print(f"名字       : {a.name}")
        print(f"activeType : {at}          <- 2 才是签到，14 是问卷，25 是作业")
        print(f"activeSort : {getattr(info, 'active_sort', None)}")
        print(f"otherId    : {getattr(info, 'other_id', None)}")
        print(f"viewPicPath: {getattr(info, 'view_pic_path', '')}")
        print(f"判定       : {kind.key}  (is_sign={kind.is_sign})  {kind.describe()}")

        # 直出二维码
        enc, why = eng.try_server_qr(a.active_id)
        print(f"/sign/qrcode -> enc={enc!r}")
        print(f"                {why}")
        if enc:
            print("  ★★★ 服务端给了真 enc！可以全自动签")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
