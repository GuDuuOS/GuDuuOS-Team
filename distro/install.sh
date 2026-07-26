#!/usr/bin/env bash
# ============================================================
# GuDuu OS 发行版 —— OEM 一键安装脚本（模块6 P0）
# ------------------------------------------------------------
# 目标：一台干净的 Ubuntu 22.04+/Debian 12 服务器 + 一个解析好的域名，
#       跑一遍本脚本 = 一个完整可用的 GuDuu OS 实例（自动 HTTPS）。
#
# 用法（在 distro/ 目录下）：
#   ./install.sh                # 交互式提问
#   ./install.sh --domain im.example.com --email admin@example.com  # 半自动
#
# 干了什么（顺序即依赖）：
#   1. 环境自检（docker / 端口 / DNS）
#   2. 收集配置（域名/管理员邮箱/SMTP/OEM 授权码）
#   3. 生成全部密钥 + 渲染配置（.env / homeserver.yaml / appservice / Caddyfile）
#   4. synapse generate（产出签名密钥、日志配置），再覆盖为我们的主配置
#   5. docker compose up -d --build（四个容器全起）
#   6. bootstrap（注册管理员、bot 账号、创建控制室）
# 全程幂等意识：已装过（.env 存在）会拒绝重跑，防止覆盖生产密钥。
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"

# ---------- 小工具 ----------
say()  { printf '\033[1;36m[GuDuu OS]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[警告]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

# 生成 64 位十六进制随机密钥（appservice token / 数据库口令等）
gen_secret() { openssl rand -hex 32; }

# 模板渲染：用 bash 原生替换逐个换 {{占位符}}——不走 sed，避免密钥里
# 特殊字符（/ & \）把 sed 表达式打穿的转义地狱
render() { # render <模板> <输出> <K=V>...
  local tpl="$1" out="$2"; shift 2
  local content; content="$(cat "$tpl")"
  local kv k v
  for kv in "$@"; do
    k="${kv%%=*}"; v="${kv#*=}"
    content="${content//"{{$k}}"/$v}"
  done
  printf '%s\n' "$content" > "$out"
}

# ---------- 0. 前置检查 ----------
[ "$(id -u)" -eq 0 ] || warn "建议以 root 运行（docker 权限）；当前非 root，若报权限错请 sudo 重跑。"
command -v docker >/dev/null 2>&1 || die "未安装 docker。请先执行：curl -fsSL https://get.docker.com | sh"
docker compose version >/dev/null 2>&1 || die "docker compose 插件不可用（docker compose version 失败）。"
command -v openssl >/dev/null 2>&1 || die "缺少 openssl（生成密钥用）。"
command -v curl >/dev/null 2>&1 || die "缺少 curl。"

if [ -f .env ]; then
  die "检测到 .env —— 本机已装过实例。升级请用 ./update.sh；确要重装请先自行备份并删除 .env 与 data/。"
fi

# ---------- 1. 收集配置 ----------
DOMAIN="" ADMIN_EMAIL="" OEM_KEY=""
# 共存模式（--behind-proxy）：本机已有宿主反代（Caddy/nginx）统一收 80/443 时用。
# 容器 Caddy 改为只出明文 HTTP、绑 127.0.0.1:8080，证书归宿主反代管。
BEHIND_PROXY=0
PROXY_HTTP_PORT=8080
# GuDuu Nexus 母舰地址（兑换授权 + 心跳 + LLM 网关都指它）；可用 --nexus 覆盖
NEXUS_URL="${NEXUS_URL:-https://nexus.guduuos.com}"
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --email)  ADMIN_EMAIL="$2"; shift 2 ;;
    --key)    OEM_KEY="$2"; shift 2 ;;
    --nexus)  NEXUS_URL="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --behind-proxy) BEHIND_PROXY=1; shift ;;
    --proxy-port) PROXY_HTTP_PORT="$2"; shift 2 ;;
    *) die "未知参数：$1（支持 --domain/--email/--key/--nexus/--region/--behind-proxy/--proxy-port）" ;;
  esac
done

say "== GuDuu OS 实例安装 =="
[ -n "$DOMAIN" ] || { read -rp "实例域名（如 im.example.com，需已解析到本机公网 IP）: " DOMAIN; }
[ -n "$DOMAIN" ] || die "域名不能为空。"
case "$DOMAIN" in
  *[!a-zA-Z0-9.-]*|.*|*.) die "域名格式不合法：$DOMAIN" ;;
esac

[ -n "$ADMIN_EMAIL" ] || read -rp "管理员邮箱（接收证书通知 + 初始管理员账号）: " ADMIN_EMAIL
[ -n "$ADMIN_EMAIL" ] || die "管理员邮箱不能为空。"

[ -n "$OEM_KEY" ] || read -rp "OEM 授权码（CMK-XXXX-XXXX-XXXX-XXXX；留空=独立模式，无 AI 网关）: " OEM_KEY

# —— 兑换授权（P1③：有授权码就向 GuDuu Nexus 真兑换，失败即终止）——
if [ -n "$OEM_KEY" ]; then
  # 机房地域：只用于 GuDuu 运营大屏在地图上标出你的实例位置。你自己最清楚机器在哪，
  # 所以这里选一下——比用 IP 猜准得多（云服务器 IP 的归属常常是服务商注册地）。
  # 留空也能装，之后可由 GuDuu 侧在后台补填。
  if [ -z "${REGION:-}" ]; then
    echo "机房地域代码（仅用于运营大屏地图标点，可留空）："
    echo "  中国大陆示例：CN-BJ 北京 / CN-SH 上海 / CN-ZJ 浙江 / CN-GD 广东 / CN-SC 四川"
    echo "  港澳台与境外：CN-HK 香港 / CN-TW 台湾 / SG 新加坡 / JP 日本 / US 美国 / DE 德国"
    read -rp "地域代码（留空跳过）: " REGION
  fi
  say "向 GuDuu Nexus（$NEXUS_URL）兑换授权……"
  REDEEM_RESP=$(curl -sS --max-time 20 -X POST "$NEXUS_URL/nexus/redeem" \
    -H "Content-Type: application/json" \
    -d "{\"key\":\"$OEM_KEY\",\"domain\":\"$DOMAIN\",\"admin_email\":\"$ADMIN_EMAIL\",\"region\":\"$REGION\"}") \
    || die "无法连接 GuDuu Nexus（$NEXUS_URL）——检查网络后重试。"
  echo "$REDEEM_RESP" | grep -q '"instance_id"' \
    || die "授权码兑换失败：$REDEEM_RESP"
  say "兑换成功：$REDEEM_RESP"
fi

# SMTP：OEM 自己的发信邮箱。可留空（届时邮箱验证码注册不可用，仅管理员手动建号）
say "配置发信邮箱（注册验证码从这里发出；全部留空可跳过，之后编辑 .env 补配）"
read -rp "SMTP 服务器（如 smtp.example.com，留空跳过）: " SMTP_HOST
SMTP_PORT="465"; SMTP_USER=""; SMTP_PASSWORD=""; SMTP_FROM=""; SMTP_FROM_NAME=""
if [ -n "$SMTP_HOST" ]; then
  read -rp "SMTP 端口 [465]: " SMTP_PORT; SMTP_PORT="${SMTP_PORT:-465}"
  read -rp "SMTP 账号: " SMTP_USER
  read -rsp "SMTP 密码: " SMTP_PASSWORD; echo
  read -rp "发件地址（默认同账号）: " SMTP_FROM; SMTP_FROM="${SMTP_FROM:-$SMTP_USER}"
  read -rp "发件人名称 [GuDuu OS]: " SMTP_FROM_NAME; SMTP_FROM_NAME="${SMTP_FROM_NAME:-GuDuu OS}"
fi

# ---------- 2. DNS / 端口体检（只警告不拦截：可能在 LB/NAT 后面）----------
PUB_IP="$(curl -4fsS --max-time 8 https://ifconfig.me 2>/dev/null || true)"
DNS_IP="$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"
if [ -n "$PUB_IP" ] && [ -n "$DNS_IP" ] && [ "$PUB_IP" != "$DNS_IP" ]; then
  warn "域名 $DOMAIN 解析到 $DNS_IP，本机公网 IP 是 $PUB_IP —— 若不一致证书会签发失败。"
elif [ -z "$DNS_IP" ]; then
  warn "域名 $DOMAIN 当前解析不到 IP —— 请确认 DNS A 记录已生效，否则证书签发会失败。"
fi
if [ "$BEHIND_PROXY" -eq 0 ]; then
  for p in 80 443; do
    if ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$p\$"; then
      warn "端口 $p 已被占用 —— Caddy 需要独占 80/443，请先停掉占用进程（如宿主机 nginx）。"
    fi
  done
fi

# ---------- 3. 生成密钥 + 渲染配置 ----------
say "生成密钥并渲染配置……"
AS_TOKEN="$(gen_secret)"
HS_TOKEN="$(gen_secret)"
REGISTRATION_SHARED_SECRET="$(gen_secret)"
ADMIN_TOKEN="$(gen_secret)"
MACAROON_SECRET_KEY="$(gen_secret)"
FORM_SECRET="$(gen_secret)"
PG_SYNAPSE_PASSWORD="$(gen_secret)"
COSMAC_DB_PASSWORD="$(gen_secret)"
# 域名转正则：点要转义（appservice 命名空间用，单引号 YAML 单反斜杠即可）
DOMAIN_REGEX="${DOMAIN//./\\.}"

mkdir -p data/synapse data/caddy

# —— AI 通道预填：有授权码=全部走母舰网关（凭证即授权码）；没有=echo 独立模式 ——
if [ -n "$OEM_KEY" ]; then
  LLM_PROVIDER="deepseek"
  LLM_MODEL="deepseek-v3.2"          # 以 GuDuu 网关实际开通的模型为准
  GW_ARK_BASE="$NEXUS_URL/gw/ark"
  GW_ANTH_BASE="$NEXUS_URL/gw/anthropic"
  GW_OPENAI_BASE="$NEXUS_URL/gw/openai"
  GW_KEY="$OEM_KEY"
else
  LLM_PROVIDER="echo"; LLM_MODEL=""
  GW_ARK_BASE=""; GW_ANTH_BASE=""; GW_OPENAI_BASE=""; GW_KEY=""
fi

render templates/dotenv.tpl .env \
  "DOMAIN=$DOMAIN" "ADMIN_USER=admin" "ADMIN_EMAIL=$ADMIN_EMAIL" "OEM_KEY=$OEM_KEY" \
  "NEXUS_URL=$NEXUS_URL" \
  "PG_SYNAPSE_PASSWORD=$PG_SYNAPSE_PASSWORD" "COSMAC_DB_PASSWORD=$COSMAC_DB_PASSWORD" \
  "AS_TOKEN=$AS_TOKEN" "HS_TOKEN=$HS_TOKEN" \
  "ADMIN_TOKEN=$ADMIN_TOKEN" "REGISTRATION_SHARED_SECRET=$REGISTRATION_SHARED_SECRET" \
  "SMTP_HOST=$SMTP_HOST" "SMTP_PORT=$SMTP_PORT" "SMTP_USER=$SMTP_USER" \
  "SMTP_PASSWORD=$SMTP_PASSWORD" "SMTP_FROM=$SMTP_FROM" "SMTP_FROM_NAME=$SMTP_FROM_NAME" \
  "LLM_PROVIDER=$LLM_PROVIDER" "LLM_MODEL=$LLM_MODEL" \
  "ARK_BASE_URL=$GW_ARK_BASE" "ARK_API_KEY=$GW_KEY" \
  "ANTHROPIC_BASE_URL=$GW_ANTH_BASE" "ANTHROPIC_API_KEY=$GW_KEY" \
  "OPENAI_BASE_URL=$GW_OPENAI_BASE" "OPENAI_API_KEY=$GW_KEY"
chmod 600 .env

render templates/appservice.yaml.tpl data/synapse/appservice-cosmac.yaml \
  "AS_TOKEN=$AS_TOKEN" "HS_TOKEN=$HS_TOKEN" "DOMAIN_REGEX=$DOMAIN_REGEX"
chmod 600 data/synapse/appservice-cosmac.yaml

if [ "$BEHIND_PROXY" -eq 1 ]; then
  # 共存模式：容器只出明文 HTTP，端口绑定收敛到 127.0.0.1（宿主反代转进来）
  render templates/Caddyfile-proxy.tpl data/caddy/Caddyfile "DOMAIN=$DOMAIN"
  cat >> .env <<EOF

# —— 共存模式（--behind-proxy）端口绑定：宿主反代 → 127.0.0.1:$PROXY_HTTP_PORT ——
COSMAC_WEB_HTTP=127.0.0.1:$PROXY_HTTP_PORT:80
COSMAC_WEB_HTTPS=127.0.0.1:1$PROXY_HTTP_PORT:443
COSMAC_WEB_HTTPS_UDP=127.0.0.1:1$PROXY_HTTP_PORT:443/udp
EOF
else
  render templates/Caddyfile.tpl data/caddy/Caddyfile \
    "DOMAIN=$DOMAIN" "ADMIN_EMAIL=$ADMIN_EMAIL"
fi

# ---------- 4. Synapse 初始化：先 generate 拿签名密钥，再换成我们的主配置 ----------
say "初始化 Synapse（生成签名密钥/日志配置）……"
docker compose run --rm \
  -e SYNAPSE_SERVER_NAME="$DOMAIN" \
  -e SYNAPSE_REPORT_STATS=no \
  synapse generate

# generate 产出的 homeserver.yaml 是官方默认版（SQLite），用我们的模板覆盖
render templates/homeserver.yaml.tpl data/synapse/homeserver.yaml \
  "DOMAIN=$DOMAIN" "PG_SYNAPSE_PASSWORD=$PG_SYNAPSE_PASSWORD" \
  "REGISTRATION_SHARED_SECRET=$REGISTRATION_SHARED_SECRET" \
  "MACAROON_SECRET_KEY=$MACAROON_SECRET_KEY" "FORM_SECRET=$FORM_SECRET"
chmod 600 data/synapse/homeserver.yaml

# 官方 Synapse 镜像内进程以 UID 991 运行；上面渲染出的配置是 root 属主 600，
# 不移交属主 Synapse 读不了配置直接起不来（首次 VM 实测踩的坑）。整目录一起交，
# generate 产物/媒体目录属主也统一，避免同类权限问题。
chown -R 991:991 data/synapse

# ---------- 5. 起全栈 ----------
say "构建并启动全部容器（首次构建前端约需几分钟）……"
docker compose up -d --build

say "等待 Synapse 就绪……"
for i in $(seq 1 60); do
  # 注意是 python3：官方 Synapse 镜像里没有 python 命令（VM 实测踩坑）
  if docker compose exec -T synapse python3 -c \
    "import urllib.request;urllib.request.urlopen('http://localhost:8008/_matrix/client/versions')" \
    >/dev/null 2>&1; then break; fi
  [ "$i" -eq 60 ] && die "Synapse 120 秒未就绪。查日志：docker compose logs synapse"
  sleep 2
done

# ---------- 6. 全新实例引导：管理员 / bot 账号 / 控制室 ----------
say "初始化实例（管理员账号 + 主 AI + 控制室）……"
BOOT_OUT=$(docker compose exec -T bot python /app/distro/bootstrap.py) \
  || { printf '%s\n' "$BOOT_OUT"; die "引导失败。查日志：docker compose logs bot"; }
# 展示引导输出（隐藏管理员令牌行——它是密钥，只进 .env 不上屏）
printf '%s\n' "$BOOT_OUT" | grep -v '^COSMAC_ADMIN_TOKEN='
# 捕获 bootstrap 铸造的**真实服务器管理员令牌**写回 .env（忘记密码/停用检查/
# 心跳用户数统计都靠它；模板里预填的随机值只是占位）
ADMIN_TOK=$(printf '%s\n' "$BOOT_OUT" | grep '^COSMAC_ADMIN_TOKEN=' | head -1 | cut -d= -f2-)
if [ -n "$ADMIN_TOK" ]; then
  sed -i.bak "s|^COSMAC_ADMIN_TOKEN=.*|COSMAC_ADMIN_TOKEN=$ADMIN_TOK|" .env && rm -f .env.bak
  say "已写入服务器管理员令牌，重建 bot 容器使其生效……"
  docker compose up -d bot >/dev/null 2>&1
fi

say "=============================================="
say "安装完成 ✅"
if [ "$BEHIND_PROXY" -eq 1 ]; then
  say "  共存模式：请在宿主反代加一条  $DOMAIN → 127.0.0.1:$PROXY_HTTP_PORT"
fi
say "  访问地址： https://$DOMAIN"
say "  管理员账号/初始密码见上方 bootstrap 输出（仅显示一次，登录后请修改）"
say "  管理后台： https://$DOMAIN/#/admin"
say "  体检：     ./doctor.sh    升级： ./update.sh"
say "  配置文件： distro/.env（密钥在内，妥善保管）"
say "=============================================="
