#!/usr/bin/env bash
# GuDuu OS 存量节点宿主更新工具迁移。
#
# 只更新宿主侧代理/体检工具与 systemd 单元，不切换 bot/web 镜像、不重建容器，
# 也不覆盖 .env、数据库、证书或 OEM 自定义的 Caddy/Compose 文件。
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
TARGET_ROOT=""
APPROVE_CURRENT=0
SYSTEMD_DIR="${GUDUU_SYSTEMD_DIR:-/etc/systemd/system}"

say()  { printf '\033[1;36m[GuDuu OS]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[警告]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --install-root) TARGET_ROOT="${2:-}"; shift 2 ;;
    --approve-current) APPROVE_CURRENT=1; shift ;;
    *) die "未知参数：$1（仅支持 --install-root /opt/…、--approve-current）" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "请使用 sudo 执行宿主更新工具迁移。"
command -v flock >/dev/null 2>&1 || die "服务器缺少 flock（util-linux）。"
command -v install >/dev/null 2>&1 || die "服务器缺少 install 命令。"
command -v python3 >/dev/null 2>&1 || die "服务器缺少 python3。"
case "$SYSTEMD_DIR" in
  /*) ;;
  *) die "GUDUU_SYSTEMD_DIR 必须是绝对路径。" ;;
esac

if [ -z "$TARGET_ROOT" ]; then
  candidates=()
  for candidate in /opt/cosmac/distro /opt/guduu-os /opt/guduu-os/distro; do
    [ -f "$candidate/.env" ] && [ -f "$candidate/docker-compose.yml" ] \
      && candidates+=("$candidate")
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
if [ -f "$TARGET_ROOT/.env" ] && [ -f "$TARGET_ROOT/docker-compose.yml" ]; then
  TARGET_DISTRO="$TARGET_ROOT"
else
  TARGET_DISTRO="$TARGET_ROOT/distro"
fi
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
  [ -f "$SYSTEMD_DIR/$unit" ] && install -m 0600 "$SYSTEMD_DIR/$unit" "$BACKUP_DIR/$unit"
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
    [ -f "$BACKUP_DIR/$unit" ] && install -m 0644 "$BACKUP_DIR/$unit" "$SYSTEMD_DIR/$unit"
  done
  [ "$service_existed" -eq 1 ] || rm -f "$SYSTEMD_DIR/guduu-update-agent.service"
  [ "$timer_existed" -eq 1 ] || rm -f "$SYSTEMD_DIR/guduu-update-agent.timer"
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

# 客户节点缺省必须人工确认。固定内部灰度节点 #2 由代理读取持久化实例身份后
# 自动放行；这里仅为旧 .env 补安全默认值，不改任何已有配置。
if ! grep -Eq '^COSMAC_AUTO_UPDATE=' "$TARGET_DISTRO/.env"; then
  printf '\n# 客户节点默认只接收更新通知；固定内部灰度节点 #2 由代理自动识别。\nCOSMAC_AUTO_UPDATE=0\n' \
    >> "$TARGET_DISTRO/.env"
fi
chmod 0600 "$TARGET_DISTRO/.env"

# 与 docker-compose.yml 的 /var/lib/cosmac bind mount 完全一致。
install -d -m 0770 "$TARGET_DISTRO/data/cosmac"

if command -v systemctl >/dev/null 2>&1; then
  install -d -m 0755 "$SYSTEMD_DIR"
  sed "s|{{DISTRO_DIR}}|$TARGET_DISTRO|g" \
    "$SCRIPT_DIR/templates/guduu-update-agent.service.tpl" \
    > "$SYSTEMD_DIR/guduu-update-agent.service"
  install -m 0644 "$SCRIPT_DIR/templates/guduu-update-agent.timer.tpl" \
    "$SYSTEMD_DIR/guduu-update-agent.timer"
  systemctl daemon-reload
  systemctl enable --now guduu-update-agent.timer >/dev/null
  if ! systemctl start guduu-update-agent.service; then
    warn "代理首次检查未成功；timer 已保留，会在 5 分钟内自动重试。"
    warn "排障：journalctl -u guduu-update-agent.service -n 50 --no-pager"
  fi
  if [ "$APPROVE_CURRENT" -eq 1 ]; then
    PENDING_PATH="$TARGET_DISTRO/data/cosmac/pending-update.json"
    APPROVAL_PATH="$TARGET_DISTRO/data/cosmac/approved-update.json"
    [ -f "$PENDING_PATH" ] \
      || die "尚未取得待安装版本；请检查更新代理日志后重试 --approve-current。"
    RELEASE_ID="$(python3 -c 'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); print(int(value.get("release_id") or 0))' "$PENDING_PATH")"
    [ "$RELEASE_ID" -gt 0 ] || die "待安装版本文件缺少合法 release_id。"
    python3 -c 'import json,os,sys,tempfile; target=sys.argv[1]; release_id=int(sys.argv[2]); parent=os.path.dirname(target); fd,temp=tempfile.mkstemp(prefix=".approved-update-",dir=parent); f=os.fdopen(fd,"w",encoding="utf-8"); json.dump({"release_id":release_id,"approved_by":"宿主 root 显式批准"},f,ensure_ascii=False); f.flush(); os.fsync(f.fileno()); os.fchmod(f.fileno(),0o660); f.close(); os.replace(temp,target)' \
      "$APPROVAL_PATH" "$RELEASE_ID"
    say "已由宿主 root 明确批准当前 release #${RELEASE_ID}，开始执行一次更新。"
    systemctl start guduu-update-agent.service
  fi
else
  [ "$APPROVE_CURRENT" -eq 0 ] \
    || die "--approve-current 需要 systemd 更新代理，当前宿主不支持。"
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
say "  客户与官网节点默认仅接收通知；固定内部灰度节点 #2 自动安装。"
say "  timer 已启用，并已立即执行一次更新检查。"
say "  本次没有重建或切换任何 bot/web 容器。"
