"""把所有课程最近发布的活动全列出来（不管 status），按开始时间倒序。

用户刚发了一个签到，一定能出现在某个课程里。如果「进行中」扫不到，
那就是状态字段或参数的问题，得看原始条目。
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session                                        # noqa: E402
from cxsign.protocol import (                                         # noqa: E402
    HOST_MOOC, build_active_list_url, build_course_list_url, parse_courses,
)

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")


def collect(s: Session, course, show_not_started: str) -> list[dict]:
    url = build_active_list_url(course.course_id, course.class_id,
                                s.fid or "", show_not_started=show_not_started)
    if not url:
        return []
    data, st, _ = s.get_json(url)
    if not isinstance(data, dict):
        return []
    d = data.get("data")
    rows = None
    if isinstance(data.get("activeList"), list):
        rows = data["activeList"]
    elif isinstance(d, dict) and isinstance(d.get("activeList"), list):
        rows = d["activeList"]
    elif isinstance(d, list):
        rows = d
    if not rows:
        return []
    out = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        item = dict(it)
        item["_course"] = course.name
        item["_class"] = course.class_name
        out.append(item)
    return out


def main() -> int:
    s = Session(cookie_file=COOKIE)
    data, st, _ = s.get_json(build_course_list_url(HOST_MOOC))
    courses = parse_courses(data)
    print(f"uid={s.uid} fid={s.fid}  课程 {len(courses)}\n")

    all_rows: list[dict] = []
    for i, c in enumerate(courses):
        for sn in ("0", "1"):
            all_rows.extend(collect(s, c, sn))
        if (i + 1) % 13 == 0:
            print(f"  …{i+1}/{len(courses)}，累计 {len(all_rows)} 条")

    # 去重（同一个 activeId 可能在两种参数下都出现）
    seen = {}
    for r in all_rows:
        aid = str(r.get("activeId") or r.get("activePrimaryId") or r.get("id") or "")
        if not aid:
            continue
        if aid not in seen:
            seen[aid] = r

    print(f"\n共 {len(seen)} 个活动\n")

    def stime(r):
        for k in ("startTime", "starttime", "createtime"):
            v = r.get(k)
            try:
                n = int(str(v).split(".")[0])
                # 秒级要转毫秒
                return n * 1000 if n < 100000000000 else n
            except (TypeError, ValueError):
                continue
        return 0

    rows = sorted(seen.values(), key=stime, reverse=True)

    print("最近 15 个活动（按开始时间倒序）")
    print("=" * 96)
    now_ms = int(time.time() * 1000)
    for r in rows[:15]:
        aid = r.get("activeId") or r.get("activePrimaryId") or r.get("id")
        ts = stime(r)
        when = ""
        if ts:
            delta = (now_ms - ts) / 1000
            when = f"{delta/60:.0f} 分钟前" if delta < 7200 else f"{delta/3600:.1f} 小时前"
        print(f"  {str(aid):<16} status={str(r.get('status')):<6} "
              f"activeType={str(r.get('activeType')):<5} otherId={str(r.get('otherId')):<6} "
              f"{str(r.get('nameOne') or r.get('name') or '')[:26]:<28} {when}")
        print(f"     课程: {r.get('_course')} / {r.get('_class')}")

    if rows:
        print("\n最新一条的完整字段：")
        for k, v in sorted(rows[0].items()):
            if k.startswith("_"):
                continue
            print(f"   {k:<22} = {str(v)[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
