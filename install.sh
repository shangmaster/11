#!/data/data/com.termux/files/usr/bin/bash
# ============================================================================
# 签到哨兵 · Termux 一键安装
#
# 用法（在 Termux 里）：
#     bash install.sh                 # 从 ~/Download 找 cxsign-sentinel.zip
#     bash install.sh /sdcard/Download/cxsign-sentinel.zip
#
# 它会做：装依赖 -> 解压 -> 装 Python 包 -> 检查解码器 -> 打印下一步
# 不会自动登录，cookie 要你自己给（脚本最后会说怎么给）。
# ============================================================================

set -u

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
say()  { printf "${BLUE}==>${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}✓${NC}  %s\n" "$*"; }
warn() { printf "${YELLOW}!${NC}  %s\n" "$*"; }
die()  { printf "${RED}✗${NC}  %s\n" "$*"; exit 1; }

# ---------------------------------------------------------------- 环境检查
if [ ! -d /data/data/com.termux ]; then
  die "这脚本只能在 Termux 里跑。先装 Termux：https://f-droid.org/packages/com.termux/"
fi
ok "在 Termux 里"

case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64 ;;
  armv7l|arm)    ARCH=arm   ;;
  x86_64)        ARCH=x86_64;;
  *)             ARCH=$(uname -m) ;;
esac
say "架构: $ARCH"

HOME_DIR="$HOME"
TARGET="$HOME_DIR/cxsign-sentinel"

# ---------------------------------------------------------------- 换源
say "检查软件源（国内直连官方源经常卡住）"
if ! grep -q "mirrors.tuna" "$PREFIX/etc/apt/sources.list" 2>/dev/null; then
  warn "如果你 pkg update 很慢，可以另外开一个窗口跑：termux-change-repo"
fi

# ---------------------------------------------------------------- 基础包
say "安装基础组件（python / unzip / zbar）"
pkg update -y >/dev/null 2>&1 || warn "pkg update 有报错，继续尝试"
pkg install -y python unzip zbar >/dev/null 2>&1 \
  || pkg install -y python unzip >/dev/null 2>&1 \
  || warn "部分包没装上，后面可能缺东西"
ok "基础组件就绪"

# ---------------------------------------------------------------- 找 zip
ZIP="${1:-}"
if [ -z "$ZIP" ]; then
  say "没给 zip 路径，在常见位置找…"
  termux-setup-storage 2>/dev/null || true
  for p in \
    /sdcard/Download/cxsign-sentinel.zip \
    /storage/emulated/0/Download/cxsign-sentinel.zip \
    "$HOME_DIR/cxsign-sentinel.zip" \
    "$HOME_DIR/storage/downloads/cxsign-sentinel.zip"
  do
    if [ -f "$p" ]; then ZIP="$p"; break; fi
  done
fi

if [ -n "$ZIP" ] && [ -f "$ZIP" ]; then
  ok "找到安装包: $ZIP"
  if [ -d "$TARGET" ]; then
    warn "$TARGET 已存在，先备份成 cxsign-sentinel.bak"
    rm -rf "${TARGET}.bak"
    mv "$TARGET" "${TARGET}.bak"
  fi
  say "解压到 $HOME_DIR"
  unzip -q -o "$ZIP" -d "$HOME_DIR" || die "解压失败，确认 zip 没坏"
  ok "解压完成"
elif [ -d "$TARGET" ]; then
  ok "已经有 $TARGET，跳过解压"
else
  die "找不到 cxsign-sentinel.zip。把 zip 传到手机 Download 目录，再跑：
      bash install.sh /sdcard/Download/cxsign-sentinel.zip"
fi

[ -d "$TARGET/core" ] || die "$TARGET/core 不存在，包结构不对"

# ---------------------------------------------------------------- Python 包
say "装二维码解码后端（拍照/二维码都要用）"
if python -c "import pyzbar.pyzbar" 2>/dev/null; then
  ok "pyzbar 已可用"
else
  pip install --quiet pyzbar pillow 2>/dev/null && \
    python -c "import pyzbar.pyzbar" 2>/dev/null && ok "pyzbar 装好了" || {
      warn "pyzbar 不可用，试试 pyzbar 之外的后端"
      if python -c "import zxingcpp" 2>/dev/null; then
        ok "zxingcpp 已可用"
      else
        pip install --quiet zxing-cpp 2>/dev/null && \
          python -c "import zxingcpp" 2>/dev/null && ok "zxingcpp 装好了" || \
          warn "两个解码后端都没装上 —— 二维码功能会不可用，其他签到不影响"
      fi
    }
fi

# ---------------------------------------------------------------- 自检
say "环境自检"
cd "$TARGET/core" || die "进不去 $TARGET/core"
python run.py doctor 2>&1 | sed 's/^/    /'

# ---------------------------------------------------------------- 下一步
cat <<EOF

$(printf "${GREEN}========================================${NC}")
$(printf "${GREEN} 装好了${NC}")
$(printf "${GREEN}========================================${NC}")

目录：$TARGET

下一步要登录（二选一）：

  $(printf "${YELLOW}A. 账号密码${NC}")
     cd $TARGET/core
     python run.py login --account 你的手机号 --password 你的密码

  $(printf "${YELLOW}B. 从电脑搬 cookie（推荐，最稳）${NC}")
     在电脑上找到 core/data/cookie.json，发到手机，然后：
     mkdir -p $TARGET/core/data
     cp /sdcard/Download/cookie.json $TARGET/core/data/cookie.json

  $(printf "${YELLOW}C. 直接贴 cookie 串${NC}")
     cd $TARGET/core
     python run.py login --cookie "_uid=...; fid=...; _d=...; uf=..."

登录成功后：

     cd $TARGET/core
     bash $TARGET/android/termux/start.sh

然后手机浏览器打开 http://127.0.0.1:8848/

EOF
