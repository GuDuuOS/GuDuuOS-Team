#!/usr/bin/env bash
# GuDuu OS 存量节点宿主更新代理公开引导器。
# 仅从严格发行 Tag 下载迁移工具；不携带 OEM KEY，不切换应用镜像。
set -euo pipefail

# v1.32.0 与当前节点发行版保持一致；宿主工具迁移仍独立于应用镜像切换。
RELEASE_TAG="v1.32.0"
ARCHIVE_URL="https://github.com/GuDuuOS/GuDuuOS-Team/archive/refs/tags/${RELEASE_TAG}.tar.gz"

say() { printf '\033[1;36m[GuDuu OS]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请使用 sudo 执行官方宿主工具迁移命令。"
command -v curl >/dev/null 2>&1 || die "缺少 curl。"
command -v tar >/dev/null 2>&1 || die "缺少 tar。"

TEMP_DIR="$(mktemp -d /tmp/guduu-host-tools.XXXXXX)"
cleanup() { rm -rf -- "$TEMP_DIR"; }
trap cleanup EXIT INT TERM

say "下载 GuDuu OS ${RELEASE_TAG} 宿主更新工具……"
curl --proto '=https' --tlsv1.2 -fsSL "$ARCHIVE_URL" \
  | tar -xz -C "$TEMP_DIR" --strip-components=1

[ -f "$TEMP_DIR/distro/migrate_host_tools.sh" ] \
  || die "发行包不完整，缺少宿主迁移脚本。"
export GUDUU_HOST_TOOLS_VERSION="${RELEASE_TAG#v}"
bash "$TEMP_DIR/distro/migrate_host_tools.sh" "$@"
