#!/usr/bin/env bash
# GuDuu OS 存量节点宿主更新工具迁移。
#
# 只更新宿主侧代理/体检工具与 systemd 单元，不切换 bot/web 镜像、不重建容器，
# 也不覆盖 .env、数据库、证书或 OEM 自定义的 Caddy/Compose 文件。
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
TARGET_ROOT=""

say()  { printf '\033[1;36m[GuDuu OS]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[警告]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --install-root) TARGET_ROOT="${2:-}"; shift 2 ;;
    *) die "未知参数：$1（仅支持 --install-root /opt/…）" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "请使用 sudo 执行宿主更新工具迁移。"
command -v flock >/dev/null 2>&1 || die "服务器缺少 flock（util-linux）。"
command -v install >/dev/null 2>&1 || die "服务器缺少 install 命令。"
command -v python3 >/dev/null 2>&1 || die "服务器缺少 python3。"

if [ -z "$TARGET_ROOT" ]; then
  candidates=()
  for candidate in /opt/cosmac /opt/guduu-os; do
    [ -f "$candidate/distro/.env" ] && candidates+=("$candidate")
  done
  [ "${#candidates[@]}" -gt 0 ] || die "没有找到已安装节点；可用 --install-root 指定安装根目录。"
  [ "${#candidates[@]}" -eq 1 ] \
    || die "检测到多个节点目录：${candidates[*]}；请用 --install-root 明确指定。"
  TARGET_ROOT="${candidates[0]}"
fi

case "$TARGET_ROOT" in
  /*) ;;
  *) die "--install-root 必须是绝对路径。" ;;
esac
TARGET_ROOT="${TARGET_ROOT%/}"
TARGET_DISTRO="$TARGET_ROOT/distro"
[ -f "$TARGET_DISTRO/.env" ] || die "$TARGET_DISTRO/.env 不存在，不是有效的 OEM 节点。"
[ -f "$TARGET_DISTRO/docker-compose.yml" ] || die "$TARGET_DISTRO/docker-compose.yml 不存在。"
[ -f "$SCRIPT_DIR/update_agent.py" ] || die "迁移包缺少 update_agent.py。"
[ -f "$SCRIPT_DIR/apply_images.py" ] || die "迁移包缺少 apply_images.py。"

# 在覆盖生产文件前先让 Python 真正编译；compile() 不生成 __pycache__，临时发行包保持干净。
python3 -c 'import pathlib,sys; [compile(pathlib.Path(p).read_text(encoding="utf-8"), p, "exec") for p in sys.argv[1:]]' \
  "$SCRIPT_DIR/update_agent.py" "$SCRIPT_DIR/apply_images.py"

# 与 update_agent.py 使用同一把锁；拿不到锁说明升级正在下载/备份/切换，绝不能中途换代理。
LOCK_PATH="${GUDUU_UPDATE_LOCK:-/var/lock/guduu-update.lock}"
mkdir -p "$(dirname "$LOCK_PATH")"
exec 9>"$LOCK_PATH"
flock -n 9 || die "节点正在执行升级，请稍后重试宿主工具迁移。"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_DIR="$TARGET_DISTRO/data/update/host-tools-backups/$STAMP"
mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"

for name in update_agent.py apply_images.py doctor.sh; do
  [ -f "$TARGET_DISTRO/$name" ] && install -m 0600 "$TARGET_DISTRO/$name" "$BACKUP_DIR/$name"
done
for unit in guduu-update-agent.service guduu-update-agent.timer; do
  [ -f "/etc/systemd/system/$unit" ] && install -m 0600 "/etc/systemd/system/$unit" "$BACKUP_DIR/$unit"
done
service_existed=0; timer_existed=0
[ -f "$BACKUP_DIR/guduu-update-agent.service" ] && service_existed=1
[ -f "$BACKUP_DIR/guduu-update-agent.timer" ] && timer_existed=1

timer_was_active=0
if command -v systemctl >/dev/null 2>&1; then
  systemctl is-active --quiet guduu-update-agent.timer && timer_was_active=1 || true
  systemctl stop guduu-update-agent.timer >/dev/null 2>&1 || true
fi

restore_backup() {
  local rc=$?
  trap - ERR
  warn "迁移未完成，正在恢复宿主工具备份……"
  for name in update_agent.py apply_images.py doctor.sh; do
    [ -f "$BACKUP_DIR/$name" ] && install -m 0755 "$BACKUP_DIR/$name" "$TARGET_DISTRO/$name"
  done
  for unit in guduu-update-agent.service guduu-update-agent.timer; do
    [ -f "$BACKUP_DIR/$unit" ] && install -m 0644 "$BACKUP_DIR/$unit" "/etc/systemd/system/$unit"
  done
  [ "$service_existed" -eq 1 ] || rm -f /etc/systemd/system/guduu-update-agent.service
  [ "$timer_existed" -eq 1 ] || rm -f /etc/systemd/system/guduu-update-agent.timer
  if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || true
    [ "$timer_was_active" -eq 1 ] && systemctl start guduu-update-agent.timer >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap restore_backup ERR

install -m 0755 "$SCRIPT_DIR/update_agent.py" "$TARGET_DISTRO/update_agent.py"
install -m 0755 "$SCRIPT_DIR/apply_images.py" "$TARGET_DISTRO/apply_images.py"
install -m 0755 "$SCRIPT_DIR/doctor.sh" "$TARGET_DISTRO/doctor.sh"

# 客户节点缺省必须人工确认。只在旧 .env 没有该键时追加，绝不覆盖公司灰度节点
# 已经显式设置的 COSMAC_AUTO_UPDATE=1。
if ! grep -Eq '^COSMAC_AUTO_UPDATE=' "$TARGET_DISTRO/.env"; then
  printf '\n# 客户节点默认只接收更新通知；1 仅供公司内部灰度节点显式启用。\nCOSMAC_AUTO_UPDATE=0\n' \
    >> "$TARGET_DISTRO/.env"
fi
chmod 0600 "$TARGET_DISTRO/.env"

if command -v systemctl >/dev/null 2>&1; then
  sed "s|{{DISTRO_DIR}}|$TARGET_DISTRO|g" \
    "$SCRIPT_DIR/templates/guduu-update-agent.service.tpl" \
    > /etc/systemd/system/guduu-update-agent.service
  install -m 0644 "$SCRIPT_DIR/templates/guduu-update-agent.timer.tpl" \
    /etc/systemd/system/guduu-update-agent.timer
  systemctl daemon-reload
  systemctl enable --now guduu-update-agent.timer >/dev/null
else
  warn "当前系统没有 systemd；宿主脚本已更新，但需要管理员自行安排定时执行 update_agent.py。"
fi

mkdir -p "$TARGET_DISTRO/data/update"
printf '%s\n' "${GUDUU_HOST_TOOLS_VERSION:-unknown}" \
  > "$TARGET_DISTRO/data/update/host-tools-version"
chmod 0600 "$TARGET_DISTRO/data/update/host-tools-version"

trap - ERR
say "宿主更新工具迁移完成 ✅"
say "  安装目录：$TARGET_DISTRO"
say "  旧文件备份：$BACKUP_DIR"
say "  客户节点默认仅接收通知，必须在 OS 后台确认后才安装。"
say "  本次没有重建或切换任何 bot/web 容器。"
