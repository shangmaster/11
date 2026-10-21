"""一次性诊断：为什么登录有效但课程列表解析出 0 个。

只打印结构，不打印 cookie 内容。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session                    # noqa: E402
from cxsign.protocol import HOST_MOOC, build_course_list_url  # noqa: E402


def shape(v, depth=0):
    if isinstance(v, dict):
        return "{" + ", ".join(list(v.keys())[:14]) + "}"
    if isinstance(v, list):
        return f"[{len(v)} x {shape(v[0], depth+1) if v else '?'}]"
    return type(v).__name__


cookie_file = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")
if not os.path.exists(cookie_file):
    print("没有 cookie.json，先登录")
    raise SystemExit(1)

s = Session(cookie_file=cookie_file)
print(f"uid={s.uid}  fid={s.fid}  jar={len(list(s.jar))} 条")

url = build_course_list_url(HOST_MOOC)
print("请求:", url)

data, status, final = s.get_json(url)
print(f"HTTP {status}  最终地址 {final[:120]}")
print("返回类型:", type(data).__name__)

if data is None:
    st, text, _ = s.request(url)
    print("不是 JSON，前 300 字：")
    print(repr(text[:300]))
elif isinstance(data, dict):
    print("顶层 keys:", list(data.keys()))
    print("result:", data.get("result"), " msg:", str(data.get("msg"))[:60])
    cl = data.get("channelList")
    print("channelList:", shape(cl))
    if isinstance(cl, list) and cl:
        c0 = cl[0]
        print("channel[0]:", shape(c0))
        if isinstance(c0, dict):
            content = c0.get("content")
            print("  content:", shape(content))
            if isinstance(content, dict):
                course = content.get("course")
                print("  course:", shape(course))
                if isinstance(course, str):
                    course = json.loads(course)
                    print("  course 是 JSON 字符串，解析后:", shape(course))
                if isinstance(course, dict):
                    rows = course.get("data")
                    print("  data:", shape(rows))
                    if isinstance(rows, list) and rows:
                        r0 = rows[0]
                        print("  row[0] keys:", list(r0.keys()))
                        print("  row[0] id/name:", r0.get("id"), "|", str(r0.get("name"))[:30])
                        cz = r0.get("clazzs")
                        print("  clazzs:", shape(cz))
                        if isinstance(cz, list) and cz:
                            print("  clazzs[0] keys:", list(cz[0].keys())
                                  if isinstance(cz[0], dict) else type(cz[0]).__name__)
                            if isinstance(cz[0], dict):
                                print("  clazzs[0] id/name:", cz[0].get("id"), "|",
                                      str(cz[0].get("name"))[:30])
