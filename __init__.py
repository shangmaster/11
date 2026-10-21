"""超星学习通自动签到引擎（签到哨兵 core）。

跨平台：同一份代码跑在 Android Termux、服务器、Windows 上都行，
手机壳通过本地 HTTP API（cxsign.server）操作它。
"""

__version__ = "1.0.0"

from .protocol import (  # noqa: F401
    APP_UA, KIND_LABELS, ActiveInfo, Activity, Kind, QrPayload,
    build_sign_params, build_sign_url, classify, extract_activities,
    normalize_active_info, parse_qr, parse_courses, translate_result,
)
from .net import Session, password_login  # noqa: F401
from .upload import upload_photo, upload_photo_file  # noqa: F401
from .engine import Engine, State, Record, DEFAULT_CONFIG, load_config  # noqa: F401
from .notify import Notifier  # noqa: F401

__all__ = [
    "__version__", "APP_UA", "KIND_LABELS", "ActiveInfo", "Activity", "Kind",
    "QrPayload", "build_sign_params", "build_sign_url", "classify",
    "extract_activities", "normalize_active_info", "parse_qr", "parse_courses",
    "translate_result", "Session", "password_login", "upload_photo",
    "upload_photo_file", "Engine", "State", "Record", "DEFAULT_CONFIG",
    "load_config", "Notifier",
]
