#!/usr/bin/env python3
"""生成 docs/architecture.png —— 一张图说清这套东西怎么搭起来的。

    python tools/make_diagram.py

刻意用代码画而不是手绘：改了架构图能跟着改，不会出现文档和图对不上。
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1520, 962
BG = "#0d1117"
CARD = "#161b22"
CARD2 = "#1c2430"
LINE = "#30363d"
FG = "#e6edf3"
DIM = "#8b949e"
BLUE = "#2f81f7"
GREEN = "#3fb950"
AMBER = "#d29922"
PURPLE = "#a371f7"
RED = "#f85149"

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "docs", "architecture.png"))

FONT = "C:/Windows/Fonts/msyh.ttc"
FONT_B = "C:/Windows/Fonts/msyhbd.ttc"
MONO = "C:/Windows/Fonts/consola.ttf"


def F(size: int, bold: bool = False, mono: bool = False):
    path = MONO if mono else (FONT_B if bold else FONT)
    if not os.path.exists(path):
        path = FONT
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        # 非 Windows 上没有微软雅黑，退回 Pillow 自带位图字体（中文会缺字，但不会崩）
        return ImageFont.load_default()


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)


def box(x0, y0, x1, y1, r=14, fill=CARD, outline=LINE, width=1):
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width)


def text(x, y, s, size=15, color=FG, bold=False, mono=False, anchor="lm"):
    d.text((x, y), s, font=F(size, bold, mono), fill=color, anchor=anchor)


def arrow(x0, y0, x1, y1, color=LINE, w=2, head=9, dash=False):
    if dash:
        steps = max(2, int(math.hypot(x1 - x0, y1 - y0) / 9))
        for i in range(steps):
            if i % 2:
                continue
            t0, t1 = i / steps, (i + 0.6) / steps
            d.line(
                [x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0,
                 x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1],
                fill=color, width=w,
            )
    else:
        d.line([x0, y0, x1, y1], fill=color, width=w)
    a = math.atan2(y1 - y0, x1 - x0)
    for s in (0.45, -0.45):
        d.line([x1, y1, x1 - head * math.cos(a + s), y1 - head * math.sin(a + s)],
               fill=color, width=w)


def chip(x, y, label, color=DIM, size=12):
    w = d.textlength(label, font=F(size, mono=True)) + 18
    d.rounded_rectangle([x, y - 11, x + w, y + 11], radius=6, fill="#0d1117", outline=LINE)
    text(x + 9, y, label, size, color, mono=True)
    return w + 8


# ------------------------------------------------------------------ 标题
text(44, 46, "签到哨兵 · 架构", 30, FG, bold=True)
text(44, 84, "引擎在常开的设备上 7×24 轮询，手机端只是遥控器和取码器", 15, DIM)

# ------------------------------------------------------------------ 学习通服务器
LX0, LX1 = 40, 330
box(LX0, 130, LX1, 470)
text(LX0 + 20, 162, "学习通服务器", 17, FG, bold=True)
text(LX0 + 20, 190, "只有 HTTP 接口，没有 SDK", 12, DIM)

rows = [
    ("mobilelearn", "活动列表 / 详情 / 签到", BLUE),
    ("mooc1-api", "课程 · 班级", BLUE),
    ("pan-yz", "图片上传", AMBER),
    ("passport2", "登录 / cookie", DIM),
]
y = 228
for name, desc, col in rows:
    d.rounded_rectangle([LX0 + 16, y - 16, LX1 - 16, y + 26], radius=8, fill=CARD2, outline=LINE)
    text(LX0 + 28, y - 2, name, 12.5, col, mono=True)
    text(LX0 + 28, y + 15, desc, 11.5, DIM)
    y += 58

# ------------------------------------------------------------------ 引擎
EX0, EX1 = 420, 1010
box(EX0, 130, EX1, 700, fill="#11161d", outline=BLUE, width=2)
text(EX0 + 22, 162, "core/  引擎 · Python 标准库", 17, FG, bold=True)
text(EX0 + 22, 190, "唯一实现协议的地方，安卓 / iOS / 桌面共用同一份", 12, DIM)

mods = [
    ("session", "cookie 池 · 登录态探测", DIM),
    ("discovery", "课程 → 活动列表 → 详情", DIM),
    ("classify", "activeSort → 9 种类型", GREEN),
    ("signer", "位置 / 二维码 / 拍照 / 签到码", GREEN),
    ("qr", "图片 → enc（pyzbar · cv2 · zbar）", PURPLE),
    ("geo", "WGS84 / GCJ02 / BD09 互转 + 地理编码", PURPLE),
]
col_w = (EX1 - EX0 - 60) / 2
for i, (name, desc, col) in enumerate(mods):
    cx = EX0 + 20 + (i % 2) * (col_w + 20)
    cy = 224 + (i // 2) * 84
    d.rounded_rectangle([cx, cy, cx + col_w, cy + 68], radius=9, fill=CARD2, outline=LINE)
    text(cx + 12, cy + 22, name, 13, col, mono=True, bold=True)
    text(cx + 12, cy + 46, desc, 11, DIM)

# 引擎内部状态机小条
sy = 520
d.rounded_rectangle([EX0 + 20, sy, EX1 - 20, sy + 60], radius=9, fill="#0d1117", outline=LINE)
text(EX0 + 36, sy + 22, "状态机", 12, DIM)
states = [("DISCOVERED", DIM), ("CLASSIFIED", BLUE), ("SIGNED", GREEN),
          ("WAITING", AMBER), ("FAILED", RED)]
sx = EX0 + 110
for s, c in states:
    w = d.textlength(s, font=F(11, mono=True)) + 16
    d.rounded_rectangle([sx, sy + 10, sx + w, sy + 32], radius=6, fill=CARD2, outline=c)
    text(sx + 8, sy + 21, s, 11, c, mono=True)
    sx += w + 14
text(EX0 + 36, sy + 46, "二维码类挂起成 WAITING，任何一路扫码器投递 enc 就立刻补签", 10.5, DIM)

# 本地 API
ay = 604
d.rounded_rectangle([EX0 + 20, ay, EX1 - 20, ay + 74], radius=9, fill="#0d2233", outline=BLUE)
text(EX0 + 36, ay + 22, "本地 HTTP API  127.0.0.1:8848", 13, BLUE, mono=True, bold=True)
text(EX0 + 36, ay + 48, "GET /api/status · POST /api/qr /api/point /api/photo /api/poll"
                        " · SSE /api/events · /map 地图页", 10.5, DIM)

# ------------------------------------------------------------------ 手机端
MX0, MX1 = 1090, 1480
box(MX0, 130, MX1, 452)
text(MX0 + 20, 162, "Android 原生壳", 17, FG, bold=True)
text(MX0 + 20, 190, "能真正「无人值守」那一端", 12, DIM)
a_rows = [
    ("前台服务", "保活 + 状态通知", GREEN),
    ("通知栏取图", "NotificationListener + ML Kit", GREEN),
    ("相册监听", "MediaStore ContentObserver", GREEN),
    ("分享收图", "ACTION_SEND", AMBER),
    ("WebView", "加载引擎的 /map 选点", DIM),
]
y = 226
for name, desc, col in a_rows:
    d.rounded_rectangle([MX0 + 16, y - 15, MX1 - 16, y + 24], radius=8, fill=CARD2, outline=LINE)
    text(MX0 + 28, y - 2, name, 12.5, col, bold=True)
    text(MX0 + 28, y + 14, desc, 11, DIM)
    y += 48

box(MX0, 472, MX1, 730)
text(MX0 + 20, 502, "iOS  Scriptable", 17, FG, bold=True)
text(MX0 + 20, 528, "沙盒限制：不能后台常驻、读不到别人的通知", 11.5, RED)
i_rows = [
    ("面板", "状态 / 地图 / 传图 / 投码", BLUE),
    ("快捷指令", "打开学习通时自动 poll", BLUE),
    ("分享扩展", "相册长按 → 投码", AMBER),
    ("Bark", "签到结果推送", GREEN),
]
y = 562
for name, desc, col in i_rows:
    d.rounded_rectangle([MX0 + 16, y - 15, MX1 - 16, y + 24], radius=8, fill=CARD2, outline=LINE)
    text(MX0 + 28, y - 2, name, 12.5, col, bold=True)
    text(MX0 + 28, y + 14, desc, 11, DIM)
    y += 44

# ------------------------------------------------------------------ 连线
arrow(LX1 + 6, 300, EX0 - 6, 300, DIM, 2)
arrow(EX0 - 6, 322, LX1 + 6, 322, DIM, 2)
text((LX1 + EX0) / 2, 288, "HTTPS", 10.5, DIM, anchor="ms")

arrow(EX1 + 6, 300, MX0 - 6, 300, BLUE, 2)
arrow(MX0 - 6, 322, EX1 + 6, 322, BLUE, 2)
text((EX1 + MX0) / 2, 288, "HTTP", 10.5, DIM, anchor="ms")

# ------------------------------------------------------------------ 底部：三条取码通道
BY0 = 756
box(40, BY0, 1480, BY0 + 176, r=14, fill="#11161d", outline=PURPLE)
text(64, BY0 + 28, "二维码取码三条通道", 16, PURPLE, bold=True)
text(64, BY0 + 56,
     "enc 只存在于老师那张图里 —— 接口不返回，抓包也得先有。所以「自动签到」= 「自动把图拿到手」",
     12, DIM)

chans = [
    ("① 通知栏", "Android 通知使用权", "学习通推送 / 群里转发的图", GREEN),
    ("② 相册", "新增图片 ContentObserver", "学委截图存相册", GREEN),
    ("③ 分享", "ACTION_SEND / 快捷指令", "微信群里长按图片 → 分享", AMBER),
]
cx = 64
for name, how, cover, col in chans:
    d.rounded_rectangle([cx, BY0 + 76, cx + 442, BY0 + 138], radius=8, fill=CARD2, outline=LINE)
    text(cx + 14, BY0 + 98, name, 12.5, col, bold=True)
    text(cx + 106, BY0 + 98, how, 11, DIM)
    text(cx + 106, BY0 + 120, cover, 10.5, "#6e7681")
    cx += 460

text(64, BY0 + 158, "三条都解不出来 → 整张图交给引擎（zbar / OpenCV 对模糊、反光的图更强）", 11, DIM)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
img.save(OUT, "PNG", optimize=True)
print(f"已生成 {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB)")
