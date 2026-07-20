#!/usr/bin/env bash
# ============================================================
# GuDuu Nexus 母舰 —— 一键部署脚本（部在你自己的 Nexus 小 VM 上）
# ------------------------------------------------------------
# 用法（干净 Ubuntu 22.04+，root 或 sudo）：
#   sudo bash nexus/deploy.sh
# 交互式问：Nexus 域名（如 nexus.guduu.co）、拉代码用的 GitHub token。
#
# 干了什么：
#   1. 装依赖：python3-venv / git / Caddy（官方 apt 源，自动 HTTPS）
#   2. 拉主仓库到 /opt/nexus/app，venv 装 nexus/requirements.txt
#   3. 生成 NEXUS_ADMIN_TOKEN / NEXUS_DASH_TOKEN → /etc/nexus.env（600）
#   4. systemd 服务 nexus.service（监听 127.0.0.1:9100，只对 Caddy 暴露）
#   5. Caddy 反代：https://<域名>/ → Nexus（fleet API + LLM 网关 + 数据大屏）
#
# 数据库：P1 起步用 SQLite（/opt/nexus/data/nexus.db，一台小 VM 管上百实例
# 的心跳/流水绰绰有余）；舰队大了迁 Postgres 只需改 /etc/nexus.env 的
# NEXUS_DATABASE_URL。原厂 LLM key（模块6 铁律：只进网关 env）也配在 nexus.env。
# 幂等：重复跑 = 拉新代码 + 重启（token 不重生成）。
# ============================================================
set -euo pipefail

say() { printf '\033[1;35m[Nexus]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 root/sudo 运行。"

APP=/opt/nexus/app
VENV=/opt/nexus/venv
DATA=/opt/nexus/data
ENVF=/etc/nexus.env

# ---------- 1. 收集配置 ----------
read -rp "Nexus 域名（如 nexus.guduu.co，需已解析到本机公网 IP）: " DOMAIN
[ -n "$DOMAIN" ] || die "域名不能为空。"
if [ ! -d "$APP/.git" ]; then
  read -rp "GitHub token（拉私有仓库用）: " GH_TOKEN
  [ -n "$GH_TOKEN" ] || die "token 不能为空。"
fi

# ---------- 2. 系统依赖 ----------
say "安装依赖……"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git curl debian-keyring \
  debian-archive-keyring apt-transport-https >/dev/null
# Caddy 官方 apt 源（Ubuntu 默认源没有 caddy）
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

# ---------- 3. 代码 + venv ----------
mkdir -p "$DATA"
if [ -d "$APP/.git" ]; then
  say "更新代码……"
  git -C "$APP" pull --ff-only
else
  say "拉取代码……"
  mkdir -p "$(dirname "$APP")"
  git clone --depth 1 "https://${GH_TOKEN}@github.com/GuDuuOS/CosMac.git" "$APP"
fi
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -r "$APP/nexus/requirements.txt"

# ---------- 4. 环境文件（密钥只生成一次，重跑不覆盖）----------
if [ ! -f "$ENVF" ]; then
  say "生成密钥……"
  cat > "$ENVF" <<EOF
# GuDuu Nexus 运行配置（600 权限，含密钥，绝不外传）
NEXUS_DATABASE_URL=sqlite:///$DATA/nexus.db
NEXUS_LISTEN_HOST=127.0.0.1
NEXUS_LISTEN_PORT=9100
# 管理令牌（console/命令行管理用）与只读大屏令牌（分权：大屏挂墙只能看）
NEXUS_ADMIN_TOKEN=$(openssl rand -hex 32)
NEXUS_DASH_TOKEN=$(openssl rand -hex 24)
# —— 原厂 LLM key（模块6 铁律：只存在这里，永不下发实例）——
# 配好后 systemctl restart nexus 生效
NEXUS_GW_ANTHROPIC_KEY=
NEXUS_GW_OPENAI_KEY=
NEXUS_GW_ARK_KEY=
EOF
  chmod 600 "$ENVF"
else
  say "沿用已有 $ENVF（密钥不重生成）"
fi

# ---------- 5. systemd ----------
cat > /etc/systemd/system/nexus.service <<EOF
[Unit]
Description=GuDuu Nexus (fleet + LLM gateway + dashboard)
After=network-online.target

[Service]
WorkingDirectory=$APP
EnvironmentFile=$ENVF
ExecStart=$VENV/bin/python -m nexus
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now nexus
systemctl restart nexus

# ---------- 6. Caddy ----------
cat > /etc/caddy/Caddyfile <<EOF
# GuDuu Nexus：自动 HTTPS，全部流量反代给本机 Nexus 服务
$DOMAIN {
	encode zstd gzip
	reverse_proxy 127.0.0.1:9100
}
EOF
systemctl reload caddy || systemctl restart caddy

# ---------- 7. 自检 + 输出 ----------
sleep 2
curl -fsS http://127.0.0.1:9100/nexus/health >/dev/null || die "Nexus 服务未就绪：journalctl -u nexus -n 30"
DASH_TOKEN=$(grep '^NEXUS_DASH_TOKEN=' "$ENVF" | cut -d= -f2)
say "=============================================="
say "部署完成 ✅"
say "  数据大屏： https://$DOMAIN/#token=$DASH_TOKEN"
say "  （首次打开后令牌记入浏览器，之后直接访问 https://$DOMAIN 即可）"
say "  管理令牌见 $ENVF（NEXUS_ADMIN_TOKEN，发 KEY/充值用）"
say "  升级：     cd $APP && git pull && systemctl restart nexus"
say "  日志：     journalctl -u nexus -f"
say "=============================================="
