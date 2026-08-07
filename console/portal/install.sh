#!/usr/bin/env bash
# GuDuu OS OEM 节点公开引导安装器。

# 这个文件只负责从官方严格 Git Tag 取回完整 distro 工具，然后把控制权
# 交给已经过测试的 distro/install.sh。长期 OEM KEY 不进 URL、命令或本文件，
# 仍由客户在服务器终端交互输入，避免泄露到 Shell history 或反向代理日志。
set -euo pipefail

# v1.30.0 安装器按不可变 digest 优先拉 Docker Hub，失败后再整组
# 回退平台自建仓与 GHCR，方便国内服务器使用标准 Docker 加速器。
RELEASE_TAG="v1.30.0"
ARCHIVE_URL="https://github.com/GuDuuOS/GuDuuOS-Team/archive/refs/tags/${RELEASE_TAG}.tar.gz"
INSTALL_ROOT="${GUDUU_INSTALL_ROOT:-/opt/guduu-os}"
REINSTALL=0
FORWARD_ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--reinstall" ]; then
    REINSTALL=1
  else
    FORWARD_ARGS+=("$arg")
  fi
done

say() { printf '\033[1;36m[GuDuu OS]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请使用 sudo 执行官方安装命令。"
command -v curl >/dev/null 2>&1 || die "缺少 curl。"
command -v tar >/dev/null 2>&1 || die "缺少 tar。"

# 既有目录可能包含生产 .env 和数据挂载关系，默认绝不覆盖。
# 显式 --reinstall 时也不删除数据：停容器后把整个目录移到带时间戳的
# 备份路径，新安装失败仍可人工恢复。输入原域名是防误操作门禁。
REINSTALL_BACKUP=""
if [ -e "$INSTALL_ROOT" ]; then
  [ "$REINSTALL" -eq 1 ] || die "${INSTALL_ROOT} 已存在；升级请用 ./update.sh，安全重装请加 --reinstall。"
  [ -f "$INSTALL_ROOT/.env" ] || die "${INSTALL_ROOT} 不是完整节点，请先人工检查，安装器不会自动移动。"
  OLD_DOMAIN="$(sed -n 's/^DOMAIN=//p' "$INSTALL_ROOT/.env" | head -1)"
  [ -n "$OLD_DOMAIN" ] || die "旧 .env 缺少 DOMAIN，无法安全确认重装对象。"
  CONFIRM_DOMAIN="${GUDUU_REINSTALL_CONFIRM:-}"
  if [ -z "$CONFIRM_DOMAIN" ]; then
    [ -r /dev/tty ] || die "重装必须在 SSH 交互终端执行，以便确认原域名。"
    read -rp "安全重装会停止当前节点；请输入原域名 ${OLD_DOMAIN} 确认: " CONFIRM_DOMAIN </dev/tty
  fi
  [ "$CONFIRM_DOMAIN" = "$OLD_DOMAIN" ] || die "域名确认不匹配，已取消重装。"
  REINSTALL_BACKUP="${INSTALL_ROOT}.backup.$(date -u +%Y%m%dT%H%M%SZ)"
  say "停止旧容器，保留数据到 ${REINSTALL_BACKUP}……"
  (cd "$INSTALL_ROOT" && docker compose down)
  mv -- "$INSTALL_ROOT" "$REINSTALL_BACKUP"
fi

TEMP_DIR="$(mktemp -d)"
cleanup() { rm -r -- "$TEMP_DIR"; }
trap cleanup EXIT INT TERM

say "下载 GuDuu OS ${RELEASE_TAG} 官方发行工具……"
curl -fL --retry 3 --connect-timeout 15 "$ARCHIVE_URL" -o "$TEMP_DIR/release.tar.gz"
tar -xzf "$TEMP_DIR/release.tar.gz" -C "$TEMP_DIR"
SOURCE_DIR="$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'GuDuuOS-Team-*' -print -quit)"
[ -n "$SOURCE_DIR" ] && [ -d "$SOURCE_DIR/distro" ] || die "发行包结构不完整。"

install -d -m 0755 "$INSTALL_ROOT"
cp -a "$SOURCE_DIR/distro/." "$INSTALL_ROOT/"
chmod 0755 "$INSTALL_ROOT/install.sh" "$INSTALL_ROOT/ensure_host.sh" "$INSTALL_ROOT/doctor.sh" \
  "$INSTALL_ROOT/update.sh" "$INSTALL_ROOT/update_agent.py" \
  "$INSTALL_ROOT/apply_images.py" "$INSTALL_ROOT/migrate_host_tools.sh"

say "发行工具已安装到 ${INSTALL_ROOT}，现在进入节点配置。"
cd "$INSTALL_ROOT"
# 把引导器自己的版本传给安装器，最终报告可以明确区分
# “安装工具版本”和“实际安装应用版本”，不再静默地用旧基线。
export GUDUU_INSTALLER_VERSION="${RELEASE_TAG#v}"
if [ -n "$REINSTALL_BACKUP" ]; then
  say "旧节点已完整保留：${REINSTALL_BACKUP}"
fi
exec ./install.sh "${FORWARD_ARGS[@]}"
