#!/usr/bin/env bash
# GuDuu OS 干净宿主机前置依赖安装。
#
# 只支持发行版明确验收的 Ubuntu 22.04+ / Debian 12+，避免在未知系统上静默修改
# 软件源。公开安装器以 sudo 启动；已有 Docker 的开发机仍可由 docker 组成员运行。

guduu_host_die() {
  printf '\033[1;31m[失败]\033[0m %s\n' "$*" >&2
  return 1
}

guduu_load_os_release() {
  local release_file="${GUDUU_OS_RELEASE_FILE:-/etc/os-release}"
  [ -r "$release_file" ] \
    || { guduu_host_die "无法读取 $release_file，暂不支持自动安装。"; return 1; }
  # os-release 是系统提供的 KEY=VALUE 文件；只取本脚本需要的两个字段。
  local os_id="" os_version="" raw key value
  while IFS= read -r raw; do
    case "$raw" in
      ID=*) key="ID"; value="${raw#ID=}" ;;
      VERSION_ID=*) key="VERSION_ID"; value="${raw#VERSION_ID=}" ;;
      *) continue ;;
    esac
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    [ "$key" = "ID" ] && os_id="$value"
    [ "$key" = "VERSION_ID" ] && os_version="$value"
  done < "$release_file"
  GUDUU_HOST_OS_ID="$os_id"
  GUDUU_HOST_OS_VERSION="$os_version"
}

guduu_require_supported_host() {
  guduu_load_os_release || return 1
  command -v dpkg >/dev/null 2>&1 \
    || { guduu_host_die "当前系统缺少 dpkg；仅支持 Ubuntu 22.04+ 或 Debian 12+。"; return 1; }
  case "$GUDUU_HOST_OS_ID" in
    ubuntu)
      dpkg --compare-versions "$GUDUU_HOST_OS_VERSION" ge 22.04 \
        || { guduu_host_die "Ubuntu $GUDUU_HOST_OS_VERSION 过旧；最低支持 22.04。"; return 1; }
      ;;
    debian)
      dpkg --compare-versions "$GUDUU_HOST_OS_VERSION" ge 12 \
        || { guduu_host_die "Debian $GUDUU_HOST_OS_VERSION 过旧；最低支持 12。"; return 1; }
      ;;
    *)
      guduu_host_die "当前系统 $GUDUU_HOST_OS_ID $GUDUU_HOST_OS_VERSION 未经发行验收；仅支持 Ubuntu 22.04+ / Debian 12+。"
      return 1
      ;;
  esac
  case "$(uname -m)" in
    x86_64|aarch64|arm64) ;;
    *) guduu_host_die "当前 CPU 架构 $(uname -m) 暂无 GuDuu OS 发行镜像。"; return 1 ;;
  esac
}

guduu_apt_install_base() {
  [ "$(id -u)" -eq 0 ] \
    || { guduu_host_die "服务器缺少安装依赖，请使用官网提供的 sudo 一键命令。"; return 1; }
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates curl gzip iproute2 openssl python3 tar util-linux
}

guduu_install_docker() {
  [ "$(id -u)" -eq 0 ] \
    || { guduu_host_die "服务器尚未安装 Docker，请使用官网提供的 sudo 一键命令。"; return 1; }
  local installer
  installer="$(mktemp /tmp/guduu-get-docker.XXXXXX.sh)" \
    || { guduu_host_die "无法创建 Docker 安装临时文件。"; return 1; }
  # Docker 官方 convenience installer 会为受支持的 Debian/Ubuntu 配置官方 apt 源，
  # 并安装 Engine、Buildx 与 Compose 插件。先落到 0600 临时文件，失败时不执行半份脚本。
  chmod 0600 "$installer"
  if ! curl --proto '=https' --tlsv1.2 -fsSL https://get.docker.com -o "$installer"; then
    rm -f "$installer"
    guduu_host_die "Docker 官方安装器下载失败，请检查服务器网络。"
    return 1
  fi
  if ! sh "$installer"; then
    rm -f "$installer"
    guduu_host_die "Docker 安装失败，请检查上方 apt/Docker 日志。"
    return 1
  fi
  rm -f "$installer"
}

guduu_start_docker() {
  if command -v systemctl >/dev/null 2>&1; then
    [ "$(id -u)" -eq 0 ] \
      || { guduu_host_die "Docker 服务未就绪，请使用 sudo 执行安装命令。"; return 1; }
    systemctl enable --now docker
  fi
  local i
  for i in $(seq 1 15); do
    docker info >/dev/null 2>&1 && return 0
    sleep 1
  done
  guduu_host_die "Docker 已安装但守护进程未就绪，请检查：systemctl status docker"
}

guduu_ensure_host() {
  guduu_require_supported_host || return 1
  # 先补齐脚本后续必需的系统工具；公开 curl 引导至少已具备 curl，但本地执行
  # distro/install.sh 时不做这个假设。
  local need_base=0 cmd
  for cmd in curl gzip getent openssl python3 ss tar flock; do
    command -v "$cmd" >/dev/null 2>&1 || need_base=1
  done
  [ "$need_base" -eq 0 ] || guduu_apt_install_base || return 1

  command -v docker >/dev/null 2>&1 || guduu_install_docker || return 1
  guduu_start_docker || return 1
  docker compose version >/dev/null 2>&1 \
    || guduu_host_die "Docker Compose 插件不可用；请检查 Docker 官方仓安装结果。"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  guduu_ensure_host
  printf '\033[1;32m[GuDuu OS]\033[0m 宿主机依赖已就绪。\n'
fi
