"""最后两条线：

1. getMoreAttendLogList —— 从签到管理页挖出来的接口。
   如果学生能调到，就能看到「老师那边看到的签到明细」，包括存的经纬度。
   这对「地图显示真实位置」这个问题是决定性的：能看到到底存了什么。

2. 消息/群聊接口 —— 老师发签到会不会推一条带图的消息。
   如果能拿到图片 URL，那就是服务器端能做的最后一环：全自动取码。
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from cxsign.net import Session                        # noqa: E402
from cxsign.protocol import HOST_MOBILE               # noqa: E402

COOKIE = os.path.join(os.path.dirname(__file__), "..", "core", "data", "cookie.json")


def show(label: str, st: int, body: str, limit: int = 400) -> None:
    ok = st == 200 and body and not body.lstrip().startswith("<!")
    print(f"\n  {label}  HTTP {st}  {len(body)}B  {'JSON/文本' if ok else 'HTML或空'}")
    if ok:
        txt = body if len(body) <= limit else body[:limit] + " …"
        print("    " + re.sub(r"\s+", " ", txt))


def main() -> int:
    aids = [a for a in sys.argv[1:] if not a.startswith("-")] or ["2000176022657"]
    s = Session(cookie_file=COOKIE)
    print(f"uid={s.uid} fid={s.fid}")

    # ---------------- 1. 签到明细 ----------------
    print("\n" + "=" * 72)
    print("1. 签到明细接口（能确认服务端到底存了什么坐标）")
    print("=" * 72)
    for aid in aids:
        for tpl in (
            f"/widget/sign/getMoreAttendLogList?activeId={aid}&page=1&pageSize=20",
            f"/widget/sign/getMoreAttendLogList?activeId={aid}&pageNum=1&pageSize=20",
            f"/widget/sign/getMoreAttendLogList?activeId={aid}",
            f"/widget/sign/getOneAttendLog?activeId={aid}&uid={s.uid}",
            f"/pptSign/getAttendInfo?activeId={aid}&uid={s.uid}",
            f"/pptSign/getSignInInfo?activeId={aid}&uid={s.uid}",
        ):
            st, body, final = s.request(HOST_MOBILE + tpl)
            show(tpl.split("?")[0] + "?" + tpl.split("?")[1][:40], st, body, 600)

    # ---------------- 2. 消息 / 群聊 ----------------
    print("\n" + "=" * 72)
    print("2. 消息接口：老师发签到会不会推一条带二维码图的")
    print("=" * 72)
    cands = [
        "https://im.chaoxing.com/",
        "https://im.chaoxing.com/api/message/list",
        "https://mobilelearn.chaoxing.com/v2/apis/message/getMessageList",
        "https://mobilelearn.chaoxing.com/v2/apis/chat/getChatList",
        "https://mobilelearn.chaoxing.com/v2/apis/msg/list?pageSize=20&page=1",
        "https://notice.chaoxing.com/pc/notice/getNoticeList?pageSize=50&page=1&noticeType=2",
        "https://notice.chaoxing.com/pc/notice/getNoticeList?pageSize=50&page=1&type=sign",
        "https://mobilelearn.chaoxing.com/v2/apis/active/getActiveList?status=1",
    ]
    for url in cands:
        st, body, _ = s.request(url)
        flag = ""
        if body and ("签到" in body):
            flag += "  ★提到签到"
        if body and re.search(r'https?://[^"\s]+\.(png|jpe?g)', body):
            flag += "  ★含图片URL"
        show(url[:70], st, body, 260)
        if flag:
            print("   " + flag)
            # 找找有没有跟签到有关的图片
            for m in re.finditer(r'(https?://[^"\s]+\.(?:png|jpe?g)[^"\s]*)', body):
                u = m.group(1)
                if any(k in u.lower() for k in ("sign", "ewm", "qr", "notice")):
                    print(f"      图片: {u[:160]}")

    # ---------------- 3. 二维码图片接口试探 ----------------
    print("\n" + "=" * 72)
    print("3. 有没有直接给二维码图片的接口")
    print("=" * 72)
    for aid in aids[:1]:
        for tpl in (
            f"/widget/sign/getSignQrCode?activeId={aid}",
            f"/pptSign/getQrCode?activeId={aid}",
            f"/v2/apis/active/getActiveQrCode?activeId={aid}",
            f"/widget/sign/e?id={aid}&enc=00000000000000000000000000000000",
            f"/sign/qrcode?activeId={aid}",
        ):
            st, body, _ = s.request(HOST_MOBILE + tpl)
            show(tpl[:70], st, body, 200)
            if st == 200 and body and not body.lstrip().startswith("<!"):
                print("      ^^^ 这个有内容，值得细看")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
