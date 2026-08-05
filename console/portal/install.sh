#!/usr/bin/env bash
# GuDuu OS OEM 节点公开引导安装器。

# 这个文件只负责从官方严格 Git Tag 取回完整 distro 工具，然后把控制权
# 交给已经过测试的 distro/install.sh。长期 OEM KEY 不进 URL、命令或本文件，
# 仍由客户在服务器终端交互输入，避免泄露到 Shell history 或反向代理日志。
set -euo pipefail

RELEASE_TAG="v1.24.0"
ARCHIVE_URL="https://github.com/GuDuuOS/GuDuuOS-Team/archive/refs/tags/${RELEASE_TAG}.tar.gz"
INSTALL_ROOT="${GUDUU_INSTALL_ROOT:-/opt/guduu-os}"

say() { printf '\033[1;36m[GuDuu OS]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请使用 sudo 执行官方安装命令。"
command -v curl >/dev/null 2>&1 || die "缺少 curl。"
command -v tar >/dev/null 2>&1 || die "缺少 tar。"

# 既有目录可能包含生产 .env 和数据挂载关系，引导器绝不覆盖；升级由
# 节点更新代理按镜像 digest 执行。
[ ! -e "$INSTALL_ROOT" ] || die "${INSTALL_ROOT} 已存在；已安装节点请使用自动更新，不要重复安装。"

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
chmod 0755 "$INSTALL_ROOT/install.sh" "$INSTALL_ROOT/doctor.sh" \
  "$INSTALL_ROOT/update.sh" "$INSTALL_ROOT/update_agent.py" \
  "$INSTALL_ROOT/apply_images.py"

say "发行工具已安装到 ${INSTALL_ROOT}，现在进入节点配置。"
cd "$INSTALL_ROOT"
exec ./install.sh "$@"
