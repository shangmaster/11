"""拍照签到的图片上传通道。

流程（照抄官方 H5 拍照签到页）：
    GET  https://pan-yz.chaoxing.com/api/token?puid=<uid>        -> {result:true, _token:"..."}
    POST https://pan-yz.chaoxing.com/upload  (multipart)
         puid=<uid>&_token=<token>&file=<图片>                    -> {objectid:"..."}
    然后把 objectid 作为 objectId 参数提交 stuSignajax。

坑：
  · 字段名是小写 objectid（大写 objectId 也有版本认，但读的时候先读小写）
  · 图片上限 10MB，只收 jpg/png/webp；相册里的 HEIC 要先转
  · 有些老师开了「现场拍摄凭证」，只传 objectId 会回 photoAuthError_PCR007，
    这时必须补 photoResult（见 docs/04-拍照签到的硬边界.md）
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .net import Session
from .protocol import HOST_PAN, build_pan_token_url, build_pan_upload_url

MAX_BYTES = 10 * 1024 * 1024
ALLOWED_MAGIC = {
    b"\xff\xd8\xff": ("jpg", "image/jpeg"),
    b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
    b"RIFF": ("webp", "image/webp"),      # 需再确认 4 字节 WEBP
    b"GIF8": ("gif", "image/gif"),
}


@dataclass
class UploadResult:
    ok: bool
    object_id: str = ""
    message: str = ""
    raw: str = ""


def sniff_image(content: bytes) -> tuple[str, str] | None:
    """返回 (扩展名, mime) 或 None。避免把 .php 改名成 .jpg 传上去。"""
    if not content:
        return None
    for magic, (ext, mime) in ALLOWED_MAGIC.items():
        if content.startswith(magic):
            if magic == b"RIFF" and content[8:12] != b"WEBP":
                continue
            return ext, mime
    return None


def validate_image(path: str) -> tuple[bool, str, str, str]:
    """返回 (ok, 说明, 扩展名, mime)。"""
    if not path or not os.path.exists(path):
        return False, "文件不存在", "", ""
    size = os.path.getsize(path)
    if size <= 0:
        return False, "空文件", "", ""
    if size > MAX_BYTES:
        return False, f"图片 {size/1048576:.1f}MB 超过 10MB 上限，先压缩", "", ""
    with open(path, "rb") as fh:
        head = fh.read(32)
    info = sniff_image(head)
    if not info:
        return False, "不是常见图片格式（只收 jpg / png / webp / gif）", "", ""
    ext, mime = info
    if ext == "gif":
        return False, "gif 不被接受，转成 jpg 再传", "", ""
    return True, f"{ext} {size/1024:.0f}KB", ext, mime


def get_pan_token(session: Session, puid: str) -> tuple[str, str]:
    """返回 (token, 错误说明)。token 为空表示失败。"""
    url = build_pan_token_url(puid)
    data, status, _ = session.get_json(url)
    if status == 0:
        return "", "网络不可达"
    if not isinstance(data, dict):
        return "", f"token 接口返回非 JSON (HTTP {status})"
    token = str(data.get("_token") or data.get("token") or "")
    if data.get("result") is True and token:
        return token, ""
    return "", str(data.get("msg") or "上传令牌获取失败")


def upload_photo(session: Session, puid: str, content: bytes,
                 filename: str = "photo.jpg", mime: str = "image/jpeg") -> UploadResult:
    """把图片字节传进学习通网盘，换回 objectid。

    实测（2026-10）这个接口的真实行为：
      · 端点 https://pan-yz.chaoxing.com/upload 存在（GET 回 405）
      · **先做 IP 白名单校验**：不在允许网段直接回
        `{"result":false,"msg":"您的ip：x.x.x.x 不被允许访问"}`
      · 过了 IP 才看 `_token`；而取 token 的老路径 `/api/token` 现在 404

    所以顺序改成：先不带 token 直接 POST。
    如果回的是「IP 不被允许」，那是网络问题 —— 换手机流量 / 校园网再试，
    参数怎么调都没用，别再浪费时间猜接口。
    """
    if not content:
        return UploadResult(False, message="图片内容为空")
    if len(content) > MAX_BYTES:
        return UploadResult(False, message="图片超过 10MB")

    url = build_pan_upload_url(HOST_PAN)

    def _post(extra: dict) -> tuple[int, str]:
        fields = {"puid": puid, "_from": "mobilelearn", **extra}
        st, text, _ = session.post_multipart(url, fields, "file", filename, content, mime)
        return st, text

    status, text = _post({})
    oid = _extract_object_id(text)
    if oid:
        return UploadResult(True, oid, "上传成功", text)

    if "不被允许访问" in (text or ""):
        import re as _re
        m = _re.search(r"您的ip[:：]\s*([0-9.]+)", text or "")
        ip = m.group(1) if m else "当前 IP"
        return UploadResult(
            False,
            message=f"网盘上传有 IP 白名单，{ip} 不在允许范围 —— "
                    f"换手机流量 / 校园网再试（改参数没用）",
            raw=text,
        )

    token, err = get_pan_token(session, puid)
    if token:
        status, text = _post({"_token": token})
        oid = _extract_object_id(text)
        if oid:
            return UploadResult(True, oid, "上传成功", text)

    return UploadResult(False, message=_explain(text, err), raw=text or "")


def _extract_object_id(text: str) -> str:
    import json
    try:
        data = json.loads(text or "")
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    for k in ("objectid", "objectId", "objectID"):
        if data.get(k):
            return str(data[k])
    files = data.get("files")
    if isinstance(files, list) and files and isinstance(files[0], dict):
        return str(files[0].get("objectid") or "")
    if isinstance(data.get("data"), dict):
        for k in ("objectid", "objectId"):
            if data["data"].get(k):
                return str(data["data"][k])
    return ""


def _explain(text: str, token_err: str) -> str:
    t = text or ""
    if "错误的_token" in t:
        return "上传需要 _token，但取 token 的老接口已 404（接口改版）"
    if "参数错误" in t:
        return f"参数被拒：{t[:120]}"
    if token_err:
        return f"上传被拒：{(t[:100] or token_err)}"
    return f"上传失败：{(t[:120] or '无响应')}"


def upload_photo_file(session: Session, puid: str, path: str) -> UploadResult:
    ok, why, ext, mime = validate_image(path)
    if not ok:
        return UploadResult(False, message=why)
    with open(path, "rb") as fh:
        content = fh.read()
    return upload_photo(session, puid, content, f"photo.{ext}", mime)


__all__ = ["UploadResult", "upload_photo", "upload_photo_file", "validate_image",
           "sniff_image", "get_pan_token", "MAX_BYTES"]
