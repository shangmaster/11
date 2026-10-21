#!/data/data/com.termux/files/usr/bin/bash
# ============================================================================
# 签到哨兵 · 启动（带保活）
#
#     bash start.sh              前台跑，Ctrl+C 停
#     bash start.sh -d           后台跑，关掉终端也不停
#     bash start.sh -d --kill    停掉后台那份
#
# 后台模式会把日志写到 core/data/sentinel.log
# ============================================================================

set -u
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok(){ printf "${GREEN}✓${NC}  %s\n" "$*"; }
warn(){ printf "${YELLOW}!${NC}  %s\n" "$*"; }
die(){ printf "${RED}✗${NC}  %s\n" "$*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$(cd "$SCRIPT_DIR/../../core" && pwd)"
[ -d "$CORE" ] || die "找不到 core 目录"
cd "$CORE" || die "进不去 $CORE"

PORT="${PORT:-8848}"
LOG="$CORE/data/sentinel.log"
PIDFILE="$CORE/data/sentinel.pid"

DAEMON=0
KILL=0
for a in "$@"; do
  case "$a" in
    -d|--daemon) DAEMON=1 ;;
    -k|--kill)   KILL=1 ;;
    --port=*)    PORT="${a#*=}" ;;
  esac
done

# ---------------------------------------------------------------- 停
if [ "$KILL" = "1" ]; then
  if [ -f "$PIDFILE" ]; then
    P=$(cat "$PIDFILE")
    if kill -0 "$P" 2>/dev/null; then
      kill "$P" && ok "已停止 PID $P"
    else
      warn "PID $P 已经不在了"
    fi
    rm -f "$PIDFILE"
  else
    pkill -f "run.py serve" 2>/dev/null && ok "已停止" || warn "没在跑"
  fi
  exit 0
fi

# ---------------------------------------------------------------- 前置检查
[ -f data/cookie.json ] || die "还没登录。先跑：
    cd $CORE
    python run.py login --account 手机号 --password 密码"

# Termux 保活（没装 termux-api 就跳过，不影响）
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null && \
  ok "已申请 wakelock（系统不容易杀）" || \
  warn "没有 wakelock（装 termux-api 可以解决：pkg install termux-api）"

# 端口占用检查
if python - "$PORT" <<'PY'
import socket, sys
s = socket.socket()
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
    sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
then
  :
else
  die "端口 $PORT 被占用。换个端口：PORT=8849 bash start.sh"
fi

# ---------------------------------------------------------------- 起
if [ "$DAEMON" = "1" ]; then
  mkdir -p data
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    die "已经在后台跑了（PID $(cat "$PIDFILE")）。要停就 bash start.sh --kill"
  fi
  nohup python run.py serve --host 0.0.0.0 --port "$PORT" >> "$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  sleep 3
  if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    ok "后台启动，PID $(cat "$PIDFILE")"
    IP=$(python - <<'PY'
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    print(s.getsockname()[0])
except Exception:
    print("127.0.0.1")
PY
)
    echo
    echo "  手机浏览器:  http://127.0.0.1:$PORT/"
    echo "  同 WiFi 设备: http://$IP:$PORT/"
    echo "  日志:        $LOG"
    echo "  停止:        bash start.sh --kill"
  else
    die "启动失败，看日志：tail -50 $LOG"
  fi
else
  echo
  echo "  手机浏览器: http://127.0.0.1:$PORT/"
  echo "  Ctrl+C 停止"
  echo
  exec python run.py serve --host 0.0.0.0 --port "$PORT"
fi
