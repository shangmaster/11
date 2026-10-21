"""对比两个活动列表接口，看哪个能看到「刚发的签到」：

  旧（一直在用）：/v2/apis/active/student/activelist
  新（文档说签到在这里）：/ppt/activeAPI/taskactivelist

taskactivelist 的参数是 courseId / classId / uid。
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session                                        # noqa: E402
from cxsign.protocol import (                                         # noqa: E402
    HOST_MOBILE, HOST_MOOC, build_course_list_url, parse_courses,
)

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")


def rows_of(data) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("activeList", "taskActiveList", "list", "data"):
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            r = rows_of(v)
            if r:
                return r
    return []


def ms(v) -> int:
    try:
        n = int(str(v).split(".")[0])
        return n * 1000 if n < 100000000000 else n
    except (TypeError, ValueError):
        return 0


def main() -> int:
    s = Session(cookie_file=COOKIE)
    data, _, _ = s.get_json(build_course_list_url(HOST_MOOC))
    courses = parse_courses(data)
    print(f"课程 {len(courses)}\n")

    now = int(time.time() * 1000)
    found_new = []

    for c in courses:
        # 两个接口各拉一次
        urls = {
            "activelist": f"{HOST_MOBILE}/v2/apis/active/student/activelist"
                          f"?fid={s.fid}&courseId={c.course_id}&classId={c.class_id}"
                          f"&showNotStartedActive=0&_={now}",
            "taskactivelist": f"{HOST_MOBILE}/ppt/activeAPI/taskactivelist"
                              f"?courseId={c.course_id}&classId={c.class_id}&uid={s.uid}",
        }
        for name, url in urls.items():
            d, st, _ = s.get_json(url)
            rows = rows_of(d)
            for r in rows:
                ts = ms(r.get("startTime") or r.get("starttime"))
                age_h = (now - ts) / 3600000 if ts else 99999
                if age_h < 24:            # 24 小时内
                    found_new.append((age_h, name, c, r))
            if rows and st == 200:
                newest = max((ms(r.get("startTime") or r.get("starttime")) for r in rows),
                             default=0)
                if newest and (now - newest) / 3600000 < 24:
                    print(f"  {name:<15} {c.name[:20]:<22} {len(rows)} 条  "
                          f"最新 {(now-newest)/60000:.0f} 分钟前")

    print(f"\n24 小时内的活动：{len(found_new)} 条")
    found_new.sort(key=lambda x: x[0])
    for age_h, name, c, r in found_new[:12]:
        aid = r.get("activeId") or r.get("activePrimaryId") or r.get("id")
        print("=" * 80)
        print(f"  {age_h*60:.0f} 分钟前  [{name}]  activeId={aid}")
        print(f"  课程: {c.name} / {c.class_name}")
        print(f"  名字: {r.get('nameOne') or r.get('name') or r.get('title')}")
        print(f"  status={r.get('status')}  activeType={r.get('activeType')}  "
              f"otherId={r.get('otherId')}")

    if found_new:
        r = found_new[0][3]
        print("\n最新一条完整字段：")
        for k, v in sorted(r.items()):
            print(f"   {k:<20} = {str(v)[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
