"""二维码解码：把「老师屏幕上/群里发的那张码」变成签到要用的 enc。

这一层只负责「图片 -> 字符串」。字符串怎么用，交给 protocol.parse_qr。

解码后端按可用性自动挑，装了哪个用哪个：
    1. pyzbar（最准，Termux: pkg install zbar && pip install pyzbar）
    2. OpenCV QRCodeDetector（pip install opencv-python-headless）
    3. 系统命令 zbarimg / zxing
    4. 都没有 -> 明确报错，别静默失败（手机端会说"没装解码器"）
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
from dataclasses import dataclass, field

_BACKENDS: list[str] = []


def _probe() -> list[str]:
    global _BACKENDS
    if _BACKENDS:
        return _BACKENDS
    found: list[str] = []
    # zxing-cpp 优先：纯 wheel，自带编译好的库，不用另装系统依赖
    # （pyzbar 在 Windows 上经常卡在 zbar DLL 加载失败）
    try:
        import zxingcpp  # noqa: F401
        found.append("zxingcpp")
    except Exception:
        pass
    try:
        import pyzbar.pyzbar  # noqa: F401
        found.append("pyzbar")
    except Exception:
        pass
    try:
        import cv2  # noqa: F401
        found.append("opencv")
    except Exception:
        pass
    for cmd in ("zbarimg", "zxing"):
        if shutil.which(cmd):
            found.append(cmd)
    _BACKENDS = found
    return found


def backends() -> list[str]:
    return list(_probe())


def available() -> bool:
    return bool(_probe())


@dataclass
class DecodeResult:
    ok: bool
    texts: list[str] = field(default_factory=list)
    backend: str = ""
    message: str = ""

    @property
    def first(self) -> str:
        return self.texts[0] if self.texts else ""


def decode_bytes(content: bytes) -> DecodeResult:
    """从图片字节里解出所有二维码文本（去重保序）。"""
    if not content:
        return DecodeResult(False, message="空图片")
    if len(content) > 12 * 1024 * 1024:
        return DecodeResult(False, message="图片过大")

    errors: list[str] = []
    for name in _probe():
        try:
            if name == "zxingcpp":
                out = _decode_zxingcpp(content)
            elif name == "pyzbar":
                out = _decode_pyzbar(content)
            elif name == "opencv":
                out = _decode_cv2(content)
            else:
                out = _decode_cli(content, name)
            if out:
                return DecodeResult(True, _uniq(out), name, "解码成功")
            errors.append(f"{name}: 图里没找到二维码")
        except Exception as e:                      # noqa: BLE001
            errors.append(f"{name}: {e}")
    if not errors:
        return DecodeResult(False, message="没有可用的解码后端"
                                           "（pip install zxing-cpp 最省事）")
    return DecodeResult(False, message="; ".join(errors[:3]))


def decode_file(path: str) -> DecodeResult:
    if not path or not os.path.exists(path):
        return DecodeResult(False, message="文件不存在")
    with open(path, "rb") as fh:
        return decode_bytes(fh.read())


# --------------------------------------------------------------------------
# 后端实现
# --------------------------------------------------------------------------

def _uniq(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        s = (s or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _decode_zxingcpp(content: bytes) -> list[str]:
    """zxing-cpp：纯 wheel，自带编译好的库，跨平台最省事。"""
    import zxingcpp
    from PIL import Image
    img = Image.open(io.BytesIO(content))
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    out: list[str] = []
    for r in zxingcpp.read_barcodes(img):
        txt = getattr(r, "text", "") or ""
        if txt:
            out.append(txt)
    return out


def _decode_pyzbar(content: bytes) -> list[str]:
    from PIL import Image
    from pyzbar.pyzbar import decode as zbdecode
    img = Image.open(io.BytesIO(content))
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    out: list[str] = []
    for item in zbdecode(img):
        try:
            out.append(item.data.decode("utf-8"))
        except UnicodeDecodeError:
            out.append(item.data.decode("latin-1"))
    return out


def _decode_cv2(content: bytes) -> list[str]:
    import cv2
    import numpy as np
    buf = np.frombuffer(content, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        return []
    det = cv2.QRCodeDetector()
    out: list[str] = []

    # 原图
    text, pts, _ = det.detectAndDecode(img)
    if text:
        out.append(text)

    # 小图先放大再试（截图里的二维码经常只有 100px）
    if not out:
        h, w = img.shape[:2]
        scale = 3 if max(h, w) < 500 else 2
        big = cv2.resize(img, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
        text, _, _ = det.detectAndDecode(big)
        if text:
            out.append(text)

    # 灰度 + 二值化再试一次
    if not out:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        text, _, _ = det.detectAndDecode(thr)
        if text:
            out.append(text)
    return out


def _decode_cli(content: bytes, cmd: str) -> list[str]:
    import tempfile
    suffix = ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(content)
        tmp = fh.name
    try:
        if cmd == "zbarimg":
            args = ["zbarimg", "--quiet", "--raw", tmp]
        else:
            args = ["zxing", "--raw", tmp] if shutil.which("zxing") else [tmp]
        proc = subprocess.run(args, capture_output=True, timeout=20)
        text = proc.stdout.decode("utf-8", "replace")
        return [line for line in text.splitlines() if line.strip()]
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


__all__ = ["decode_bytes", "decode_file", "available", "backends", "DecodeResult"]
