"""photoResult 结构分析器。

为什么需要它：拍照签到卡在 `photoAuthError_PCR007` —— 服务端要「现场拍摄凭证」。
这个凭证是官方 App 的原生桥生成的，网页端 / 纯 HTTP 客户端拿不到。

但「拿不到」有两种情况，处理方式完全不同：

  情况 A：它只是客户端拼出来的（时间戳 + 坐标 + 设备号 + 图 hash）
          -> 我们自己就能算，引擎直接造一个，问题彻底解决

  情况 B：它是服务端下发的一次性 token，或者带私钥签名
          -> 只能 hook 官方 App 让它现场生成

所以正确的第一步不是去 hook，而是**抓一次真的看看**。这个模块就是干这个的：
把抓到的那串丢进来，它告诉你里面装了什么、像 A 还是像 B。

用法：
    python run.py probe-photo --text "<抓到的那串>"
    python run.py probe-photo --file photoResult.txt
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from urllib.parse import unquote

B64_RE = re.compile(r"^[A-Za-z0-9+/=_-]{16,}$")
HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _try_b64(seg: str) -> bytes | None:
    s = seg.strip()
    if not s:
        return None
    pad = "=" * (-len(s) % 4)
    for alt in (s + pad, s.replace("-", "+").replace("_", "/") + pad):
        try:
            return base64.b64decode(alt, validate=False)
        except (binascii.Error, ValueError):
            continue
    return None


def _printable(data: bytes) -> bool:
    if not data:
        return False
    ok = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    return ok / len(data) > 0.85


def _score_timestamp(n: int) -> str | None:
    """判断一个整数像不像时间戳。返回人话。"""
    now = int(time.time())
    if 1_600_000_000 <= n <= now + 86400:            # 秒
        return f"像 Unix 秒级时间戳 -> {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(n))}"
    if 1_600_000_000_000 <= n <= (now + 86400) * 1000:  # 毫秒
        ms = n // 1000
        return f"像 Unix 毫秒时间戳 -> {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ms))}"
    return None


def _score_coord(f: float) -> str | None:
    if 3.86 <= f <= 53.55:
        return "像纬度（中国境内）"
    if 73.66 <= f <= 135.05:
        return "像经度（中国境内）"
    return None


def _describe_segment(seg: str, idx: int) -> dict:
    info: dict = {"i": idx, "raw": seg, "len": len(seg)}
    s = seg.strip()

    if not s:
        info["kind"] = "空"
        return info

    # 纯数字
    if s.isdigit():
        n = int(s)
        info["kind"] = "纯数字"
        ts = _score_timestamp(n)
        if ts:
            info["guess"] = ts
        elif len(s) >= 6:
            info["guess"] = f"数字 id（{len(s)} 位）"
        else:
            info["guess"] = "小整数"
        return info

    # 带小数点的数字 -> 可能是坐标
    if re.fullmatch(r"-?\d+\.\d+", s):
        try:
            f = float(s)
            g = _score_coord(f)
            info["kind"] = "小数"
            info["guess"] = g or "小数（不是中国境内坐标）"
        except ValueError:
            info["kind"] = "小数"
        return info

    # hash
    if HEX32.match(s):
        info["kind"] = "32 位 hex"
        info["guess"] = "像 MD5"
        return info
    if HEX40.match(s):
        info["kind"] = "40 位 hex"
        info["guess"] = "像 SHA-1"
        return info
    if HEX64.match(s):
        info["kind"] = "64 位 hex"
        info["guess"] = "像 SHA-256"
        return info

    # base64
    if B64_RE.match(s):
        raw = _try_b64(s)
        if raw:
            if _printable(raw):
                info["kind"] = "base64"
                info["decoded"] = raw.decode("utf-8", "replace")[:400]
                info["guess"] = "base64 里是可读文本"
                return info
            if raw[:1] == b"\xff" or raw[:8].startswith(b"\x89PNG"):
                info["kind"] = "base64"
                info["guess"] = f"base64 里是图片二进制（{len(raw)} 字节）"
                return info
            info["kind"] = "base64"
            info["guess"] = f"base64 里是 {len(raw)} 字节二进制"
            return info

    if s.upper() in ("TRUE", "FALSE", "NULL", "NONE"):
        info["kind"] = "字面量"
        return info

    info["kind"] = "文本"
    info["guess"] = f"长度 {len(s)}"
    return info


def analyze(raw: str) -> dict:
    """把一串 photoResult（或整个请求的参数）拆开分析。"""
    text = (raw or "").strip()
    report: dict = {
        "input_len": len(text),
        "segments": [],
        "structure": "",
        "verdict": "",
        "advice": [],
        "confidence": "low",
    }
    if not text:
        report["structure"] = "空"
        return report

    # 如果用户把整行查询串粘进来了，先把 photoResult 抽出来
    m = re.search(r"(?:^|[?&])photoResult=([^&\s]+)", text)
    if m:
        text = unquote(m.group(1))
        report["input_len"] = len(text)
        report["note"] = "已从请求参数里抽出 photoResult"

    # 形态判断
    shapes = []
    if "|" in text:
        shapes.append("竖线分隔")
    if text.startswith("{"):
        shapes.append("JSON")
    if text.count(".") == 2 and all(
        re.fullmatch(r"[A-Za-z0-9_\-=]+", p or "") for p in text.split(".")
    ):
        shapes.append("JWT（三段 base64）")
    if "=" in text and "&" in text:
        shapes.append("查询串")
    report["structure"] = " + ".join(shapes) or "单一值"

    # 分段
    segs: list[str]
    if "|" in text:
        segs = text.split("|")
    elif text.startswith("{"):
        segs = []
    elif "&" in text:
        segs = [p.split("=", 1)[1] for p in text.split("&") if "=" in p]
    else:
        segs = [text]

    if text.startswith("{"):
        try:
            obj = json.loads(text)
            report["json"] = obj
            segs = [str(v) for v in obj.values() if not isinstance(v, (dict, list))]
            shapes.append("JSON 已解析")
        except Exception:
            pass

    report["segments"] = [_describe_segment(s, i) for i, s in enumerate(segs)]

    # base64 里裹着 JSON 的情况（很常见）：把里面的字段也当段来分析，
    # 否则只会得出「一段二进制」这种没用的结论。
    extra: list[dict] = []
    for seg in list(report["segments"]):
        decoded = (seg.get("decoded") or "").strip()
        if not decoded.startswith("{"):
            continue
        try:
            obj = json.loads(decoded)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        report["json"] = obj
        report["structure"] += " -> base64(JSON)"
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                continue
            item = _describe_segment(str(v), len(report["segments"]) + len(extra))
            item["key"] = k
            extra.append(item)
    report["segments"].extend(extra)

    # JWT 特殊处理
    if "JWT" in " ".join(shapes):
        parts = text.split(".")
        try:
            header = _try_b64(parts[0])
            payload = _try_b64(parts[1])
            if header and _printable(header):
                report["json"] = {"header": json.loads(header.decode()),
                                  "payload": json.loads((payload or b"{}").decode()
                                                        if payload and _printable(payload) else "{}")}
        except Exception:
            pass

    report.update(_verdict(report))
    return report


def _verdict(r: dict) -> dict:
    """从结构反推：能不能自己造。"""
    segs = r["segments"]
    names = [s.get("guess", "") for s in segs]
    joined = " ".join(names)
    lens = [s["len"] for s in segs]

    has_ts = any("时间戳" in n for n in names)
    has_coord = sum(1 for n in names if "坐标" in n or "纬度" in n or "经度" in n)
    has_hash = any("MD5" in n or "SHA" in n for n in names)
    has_b64blob = any("base64" in n for n in names)
    n_seg = len([s for s in segs if s["raw"]])

    advice: list[str] = []
    verdict = ""
    conf = "medium"

    if has_ts and has_hash and has_coord >= 1:
        verdict = "大概率是客户端拼装（时间戳 + 坐标 + 图 hash），可以自己造"
        conf = "high"
        advice.append("下一步：把这张表里的**每一段**换成你自己的值，重新提交试一次。")
        advice.append("时间戳用当前时间，坐标用你要签到的点，hash 用你上传那张图的 md5。")
        advice.append("如果服务端回 success，说明它只校验格式 —— 引擎就能直接生成，不用碰 App。")
    elif has_ts and not has_hash:
        verdict = "有时间戳但没看到图 hash，可能只校验「新鲜度」"
        advice.append("时间戳改成当前时间试试；如果还拒绝，说明它跟服务端状态有关，得 hook。")
    elif "JWT" in r["structure"]:
        verdict = "看起来是 JWT / 服务端签发的 token"
        conf = "high"
        advice.append("payload 里如果有 exp，那就是一次性凭证，自己造不出来。")
        advice.append("这种情况只能 hook 官方 App 现场生成，见 android-hook/。")
    elif has_b64blob:
        verdict = "里面裹了一段二进制或密文"
        advice.append("先把 base64 解开看看是什么（上面 segments 里有 decoded）。")
        advice.append("如果是图片本身 -> 说明这串就是图，不需要它也行。")
        advice.append("如果是密文 -> 大概率带签名，只能 hook。")
    elif n_seg <= 2 and not has_ts:
        verdict = "结构太简单，不像完整凭证"
        advice.append("可能抓到的不是真的 photoResult（比如抓的是空值或别的参数）。")
        advice.append("确认一下：抓包时那次签到是不是**真的成功了**，失败的那次不会有有效值。")
    else:
        verdict = "结构没对上已知模式"
        advice.append("把上面 segments 的猜测逐条核对一下，或者把这串脱敏后发出来一起看。")

    if r["input_len"] > 2000:
        advice.append("长度超过 2000 字符 —— 很可能内嵌了图片本身（base64 图）。")
    if len(set(l for l in lens if l)) == 1 and n_seg > 3:
        advice.append("每一段长度都一样，像是固定宽度编码（hex / 定长字段）。")

    return {"verdict": verdict, "advice": advice, "confidence": conf}


def format_report(r: dict) -> str:
    lines = []
    lines.append("=" * 62)
    lines.append("photoResult 结构分析")
    lines.append("=" * 62)
    if r.get("note"):
        lines.append(f"注：{r['note']}")
    lines.append(f"总长度   : {r['input_len']}")
    lines.append(f"整体形态 : {r['structure']}")
    lines.append("")
    lines.append("分段明细：")
    for s in r["segments"]:
        key = f" {s['key']}=" if s.get("key") else ""
        head = f"  [{s['i']}] {s['kind']:<10} len={s['len']:<4}{key}"
        guess = s.get("guess", "")
        lines.append(f"{head} {guess}")
        if s.get("decoded"):
            preview = s["decoded"].replace("\n", " ")[:150]
            lines.append(f"        -> {preview}")
        if s["len"] <= 64 and s["raw"]:
            lines.append(f"        原值: {s['raw']}")
    if r.get("json"):
        lines.append("")
        lines.append("JSON：")
        lines.append("  " + json.dumps(r["json"], ensure_ascii=False, indent=2)[:1200])
    lines.append("")
    lines.append(f"结论（{r['confidence']} 置信度）：{r['verdict']}")
    if r["advice"]:
        lines.append("")
        lines.append("下一步：")
        for a in r["advice"]:
            lines.append(f"  · {a}")
    lines.append("=" * 62)
    return "\n".join(lines)


__all__ = ["analyze", "format_report"]
