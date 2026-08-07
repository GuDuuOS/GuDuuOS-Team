#!/usr/bin/env bash
# ============================================================
# GuDuu OS 发行版 —— OEM 一键安装脚本（模块6 P0）
# ------------------------------------------------------------
# 目标：一台干净的 Ubuntu 22.04+/Debian 12 服务器 + 一个已审批域名，
#       跑一遍本脚本 = 一个完整 GuDuu OS 实例；DNS 生效后自动签发 HTTPS。
#
# 用法（在 distro/ 目录下）：
#   ./install.sh                # 交互式提问
#   ./install.sh --domain im.example.com --email admin@example.com  # 半自动
#
# 干了什么（顺序即依赖）：
#   1. 自动准备宿主依赖（基础工具 / Docker / Compose）
#   2. 收集基础设施配置（域名/管理员邮箱/OEM 授权码；业务配置安装后进网页填写）
#   3. 生成全部密钥 + 渲染配置（.env / homeserver.yaml / appservice / Caddyfile）
#   4. synapse generate（产出签名密钥、日志配置），再覆盖为我们的主配置
#   5. 从 Nexus 取得 CI 冻结摘要并拉取镜像（四个容器全起，不在客户机编译）
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
# 官网命令以 sudo 启动；干净 Ubuntu/Debian 会在这里自动安装基础工具、Docker Engine
# 与 Compose 插件。已有依赖的开发机不会重复改软件源。
[ -r ./ensure_host.sh ] || die "发行包缺少 ensure_host.sh，请重新下载官方安装器。"
# shellcheck source=ensure_host.sh
source ./ensure_host.sh
say "检查并准备宿主机依赖……"
guduu_ensure_host || exit 1

if [ -f .env ]; then
  die "检测到 .env —— 本机已装过实例。升级请用 ./update.sh；确要重装请先自行备份并删除 .env 与 data/。"
fi

# ---------- 1. 收集配置 ----------
DOMAIN="" ADMIN_EMAIL="" OEM_KEY="" REGION=""
# 共存模式（--behind-proxy）：本机已有宿主反代（Caddy/nginx）统一收 80/443 时用。
# 容器 Caddy 改为只出明文 HTTP、绑 127.0.0.1:8080，证书归宿主反代管。
BEHIND_PROXY=0
PROXY_HTTP_PORT=8080
# GuDuu Nexus 母舰地址（兑换授权 + 心跳 + LLM 网关都指它）；可用 --nexus 覆盖
NEXUS_URL="${NEXUS_URL:-https://dev-nexus.guduu.co}"
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
[ -n "$DOMAIN" ] || { read -rp "已审批的实例域名（如 im.example.com，DNS 可在安装后解析）: " DOMAIN; }
[ -n "$DOMAIN" ] || die "域名不能为空。"
case "$DOMAIN" in
  *[!a-zA-Z0-9.-]*|.*|*.) die "域名格式不合法：$DOMAIN" ;;
esac

[ -n "$ADMIN_EMAIL" ] || read -rp "管理员邮箱（接收证书通知 + 初始管理员账号）: " ADMIN_EMAIL
[ -n "$ADMIN_EMAIL" ] || die "管理员邮箱不能为空。"

[ -n "$OEM_KEY" ] || read -rp "OEM 授权码（请先在 Nexus OEM 门户申请并领取）: " OEM_KEY
[ -n "$OEM_KEY" ] || die "网页版部署必须使用 OEM 授权码；请前往 $NEXUS_URL/portal/#oem-licenses 申请。"
printf '%s' "$OEM_KEY" | grep -Eq '^CMK-[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+$' \
  || die "OEM 授权码格式不正确。"

# —— 兑换授权（P1③：有授权码就向 GuDuu Nexus 真兑换，失败即终止）——
NODE_ACTIVATION_REQUIRED="0"
if [ -n "$OEM_KEY" ]; then
  # 机房地域：用于 GuDuu 运营大屏在地图上标出实例位置。云服务器 IP 的注册地
  # 经常不等于真实机房，所以必须由部署人选择，不能留空后再让系统猜。
  if [ -z "${REGION:-}" ]; then
    echo "机房地域代码（必填，用于运营大屏地图标点）："
    echo "  中国大陆示例：CN-BJ 北京 / CN-SH 上海 / CN-ZJ 浙江 / CN-GD 广东 / CN-SC 四川"
    echo "  港澳台与境外：CN-HK 香港 / CN-TW 台湾 / SG 新加坡 / JP 日本 / US 美国 / DE 德国"
    read -rp "地域代码: " REGION
  fi
  [ -n "${REGION:-}" ] || die "机房地域不能为空；所有 OEM 节点都必须接入运营大屏。"
  REGIONS_RESP=$(curl -fsS --max-time 20 "$NEXUS_URL/nexus/regions") \
    || die "暂时无法读取 Nexus 地域列表，请检查网络后重试。"
  REGION=$(printf '%s' "$REGIONS_RESP" | python3 -c '
import json,sys
requested=sys.argv[1].strip().upper()
codes={str(item.get("code", "")).upper() for item in json.load(sys.stdin).get("regions", [])}
if requested not in codes:
    raise SystemExit(2)
print(requested)
' "$REGION") || die "不支持的机房地域代码：$REGION"
  say "向 GuDuu Nexus（$NEXUS_URL）兑换授权……"
  REDEEM_RESP=$(curl -sS --max-time 20 -X POST "$NEXUS_URL/nexus/redeem" \
    -A "GuDuu-Node-Installer/1.0" \
    -H "Content-Type: application/json" \
    -d "{\"key\":\"$OEM_KEY\",\"domain\":\"$DOMAIN\",\"admin_email\":\"$ADMIN_EMAIL\",\"region\":\"$REGION\"}") \
    || REDEEM_RESP=""
  if echo "$REDEEM_RESP" | grep -q '"instance_id"'; then
    say "兑换成功：$REDEEM_RESP"
  else
    # 继续安装但绝不开放业务入口：bot 会仅允许 bootstrap 管理员登录激活页，并由
    # 服务器从环境取 KEY 重试。这样 Cloudflare/反代短暂配置问题不会逼客户重装。
    NODE_ACTIVATION_REQUIRED="1"
    warn "Nexus 兑换暂未成功；节点将以受限模式启动，首次管理员登录后完成激活。"
  fi
fi

# —— 获取首次安装镜像（必须是平台已正式发布且与审批域名一致的精确摘要）——
# KEY 只通过 TLS 发给 Nexus；响应仅含公开 digest，不含仓库凭据。即使首次兑换因
# 严格 IP/反代暂时失败，也允许把节点装成受限态，之后由 bootstrap 管理员重试激活。
say "获取 GuDuu OS 正式版镜像清单……"
INSTALL_BODY=$(python3 -c 'import json,sys; print(json.dumps({"key":sys.argv[1],"domain":sys.argv[2]}))' "$OEM_KEY" "$DOMAIN")
INSTALL_RESP=$(curl -sS --max-time 20 -X POST "$NEXUS_URL/nexus/install/artifact" \
  -A "GuDuu-Node-Installer/1.0" \
  -H "Content-Type: application/json" --data "$INSTALL_BODY") || INSTALL_RESP=""
readarray -t INSTALL_FIELDS < <(printf '%s' "$INSTALL_RESP" | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)
    artifact = value["artifact"]
    fields = [
        value["version"],
        value.get("source", "unknown"),
        artifact["bot_dockerhub_image"], artifact["web_dockerhub_image"],
        artifact["bot_mirror_image"], artifact["web_mirror_image"],
        artifact["bot_image"], artifact["web_image"],
    ]
    if artifact.get("mode") != "container" or any("@sha256:" not in str(item) for item in fields[2:]):
        raise ValueError("invalid artifact")
    print("\n".join(str(item) for item in fields))
except Exception:
    raise SystemExit(1)
') || die "无法取得可安装镜像：$(printf '%s' "$INSTALL_RESP" | head -c 300)"
INSTALL_VERSION="${INSTALL_FIELDS[0]}"
INSTALL_MANIFEST_SOURCE="${INSTALL_FIELDS[1]}"
BOT_DOCKERHUB_IMAGE="${INSTALL_FIELDS[2]}"
WEB_DOCKERHUB_IMAGE="${INSTALL_FIELDS[3]}"
BOT_MIRROR_IMAGE="${INSTALL_FIELDS[4]}"
WEB_MIRROR_IMAGE="${INSTALL_FIELDS[5]}"
BOT_GHCR_IMAGE="${INSTALL_FIELDS[6]}"
WEB_GHCR_IMAGE="${INSTALL_FIELDS[7]}"

INSTALLER_VERSION="${GUDUU_INSTALLER_VERSION:-未知}"
if [ "$INSTALLER_VERSION" != "未知" ] && [ "$INSTALLER_VERSION" != "$INSTALL_VERSION" ]; then
  warn "安装工具为 $INSTALLER_VERSION，Nexus 新装基线为 $INSTALL_VERSION；将按平台已验收基线安装。"
fi

# Docker Hub 优先，方便国内服务器使用标准 Docker 镜像加速器；任一镜像失败就
# 整组回退自建仓，最后回退 GHCR，避免 bot/web 来自两套不一致来源。
say "拉取 GuDuu OS $INSTALL_VERSION 镜像（优先 Docker Hub）……"
if docker pull "$BOT_DOCKERHUB_IMAGE" && docker pull "$WEB_DOCKERHUB_IMAGE"; then
  BOT_IMAGE="$BOT_DOCKERHUB_IMAGE"; WEB_IMAGE="$WEB_DOCKERHUB_IMAGE"
  INSTALL_IMAGE_SOURCE="Docker Hub（首选）"; INSTALL_IMAGE_FALLBACK="否"
else
  warn "Docker Hub 拉取失败，回退平台镜像仓同摘要镜像……"
  if docker pull "$BOT_MIRROR_IMAGE" && docker pull "$WEB_MIRROR_IMAGE"; then
    BOT_IMAGE="$BOT_MIRROR_IMAGE"; WEB_IMAGE="$WEB_MIRROR_IMAGE"
    INSTALL_IMAGE_SOURCE="平台自建镜像仓"; INSTALL_IMAGE_FALLBACK="是：Docker Hub 失败"
  else
    warn "平台镜像仓拉取失败，回退 GHCR 同摘要镜像……"
    docker pull "$BOT_GHCR_IMAGE" && docker pull "$WEB_GHCR_IMAGE" \
      || die "Docker Hub、平台镜像仓和 GHCR 均拉取失败；请检查网络或镜像仓公开状态。"
    BOT_IMAGE="$BOT_GHCR_IMAGE"; WEB_IMAGE="$WEB_GHCR_IMAGE"
    INSTALL_IMAGE_SOURCE="GHCR"; INSTALL_IMAGE_FALLBACK="是：Docker Hub 与平台镜像仓失败"
  fi
fi

# SMTP、主 AI、支付与品牌统一由安装后的网页设置管理。安装器只负责把 OS
# 安全地拉起，避免客户在终端和网页各填一遍，也不让业务密钥留在 shell history。

# ---------- 2. DNS / 端口体检（只警告不拦截：可能在 LB/NAT 后面）----------
PUB_IP="$(curl -4fsS --max-time 8 https://ifconfig.me 2>/dev/null || true)"
DNS_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '$2=="STREAM"{print $1; exit}' || true)"
if curl -fsSI --max-time 10 "https://$DOMAIN/" 2>/dev/null \
    | tr -d '\r' | grep -Eiq '^server:[[:space:]]*cloudflare'; then
  say "  DNS：      $DOMAIN 已经 Cloudflare 代理"
elif [ -n "$PUB_IP" ] && [ -n "$DNS_IP" ] && [ "$PUB_IP" != "$DNS_IP" ]; then
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
else
  case "$PROXY_HTTP_PORT" in
    ''|*[!0-9]*) die "--proxy-port 必须是 1024-65535 之间的数字。" ;;
  esac
  [ "$PROXY_HTTP_PORT" -ge 1024 ] && [ "$PROXY_HTTP_PORT" -le 65535 ] \
    || die "--proxy-port 必须在 1024-65535 之间。"
  REQUESTED_PROXY_PORT="$PROXY_HTTP_PORT"
  # 面板/nginx 经常已占用默认 8080。只在 loopback TCP 端口真实被监听时
  # 逐一向后选择，并在安装结果中明确告知宿主反代应该转发到哪里。
  while ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PROXY_HTTP_PORT\$"; do
    [ "$PROXY_HTTP_PORT" -lt 65535 ] || die "1024-65535 中没有可用的反代端口。"
    PROXY_HTTP_PORT=$((PROXY_HTTP_PORT + 1))
  done
  if [ "$PROXY_HTTP_PORT" != "$REQUESTED_PROXY_PORT" ]; then
    warn "反代端口 $REQUESTED_PROXY_PORT 已被占用，已自动改用 127.0.0.1:$PROXY_HTTP_PORT。"
  fi
fi

# ---------- 3. 生成密钥 + 渲染配置 ----------
say "生成密钥并渲染配置……"
AS_TOKEN="$(gen_secret)"
HS_TOKEN="$(gen_secret)"
REGISTRATION_SHARED_SECRET="$(gen_secret)"
ADMIN_TOKEN="$(gen_secret)"
NODE_SETTINGS_SECRET="$(gen_secret)"
MACAROON_SECRET_KEY="$(gen_secret)"
FORM_SECRET="$(gen_secret)"
PG_SYNAPSE_PASSWORD="$(gen_secret)"
COSMAC_DB_PASSWORD="$(gen_secret)"
# 域名转正则：点要转义（appservice 命名空间用，单引号 YAML 单反斜杠即可）
DOMAIN_REGEX="${DOMAIN//./\\.}"

mkdir -p data/synapse data/caddy data/cosmac
chmod 0770 data/cosmac

render templates/dotenv.tpl .env \
  "DOMAIN=$DOMAIN" "ADMIN_USER=admin" "ADMIN_EMAIL=$ADMIN_EMAIL" "OEM_KEY=$OEM_KEY" "NODE_ACTIVATION_REQUIRED=$NODE_ACTIVATION_REQUIRED" \
  "INSTALL_VERSION=$INSTALL_VERSION" "BOT_IMAGE=$BOT_IMAGE" "WEB_IMAGE=$WEB_IMAGE" \
  "NEXUS_URL=$NEXUS_URL" "NODE_REGION=$REGION" \
  "PG_SYNAPSE_PASSWORD=$PG_SYNAPSE_PASSWORD" "COSMAC_DB_PASSWORD=$COSMAC_DB_PASSWORD" \
  "AS_TOKEN=$AS_TOKEN" "HS_TOKEN=$HS_TOKEN" \
  "ADMIN_TOKEN=$ADMIN_TOKEN" "REGISTRATION_SHARED_SECRET=$REGISTRATION_SHARED_SECRET" \
  "NODE_SETTINGS_SECRET=$NODE_SETTINGS_SECRET"
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
# 共存模式下容器 Caddy 只监听 :80；Compose 仍有 443 容器端口声明，
# 让 Docker 给它分配随机 loopback 端口，避免构造 18080 一类可冲突固定端口。
COSMAC_WEB_HTTPS=127.0.0.1::443
COSMAC_WEB_HTTPS_UDP=127.0.0.1::443/udp
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
say "启动全部容器（使用已校验的不可变镜像，不在本机编译）……"
docker compose up -d --no-build

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

# ---------- 7. 宿主更新代理 ----------
# 自动升级必须在宿主执行 docker compose，不能把 Docker socket 暴露给 bot 容器。
# systemd timer 只主动出站访问 Nexus，不开放端口，也不需要平台保存客户 SSH 凭据。
if [ "$(id -u)" -eq 0 ] && command -v systemctl >/dev/null 2>&1; then
  DISTRO_DIR="$(pwd -P)"
  # GHCR 发行包允许匿名只读，客户无需 GitHub 账号或 Token。
  # 仅自建仓需要时才在这个 root 文件配置可撤销的只读凭据。
  if [ ! -f /etc/guduu-registry.env ]; then
    install -m 0600 templates/guduu-registry.env.example /etc/guduu-registry.env
  fi
  say "安装 Nexus 版本更新代理（每 5 分钟检查一次）……"
  render templates/guduu-update-agent.service.tpl \
    /etc/systemd/system/guduu-update-agent.service "DISTRO_DIR=$DISTRO_DIR"
  install -m 0644 templates/guduu-update-agent.timer.tpl \
    /etc/systemd/system/guduu-update-agent.timer
  systemctl daemon-reload
  systemctl enable --now guduu-update-agent.timer >/dev/null
  if ! systemctl start guduu-update-agent.service; then
    warn "更新代理首次检查未成功；timer 已保留，会在 5 分钟内自动重试。"
    warn "排障：journalctl -u guduu-update-agent.service -n 50 --no-pager"
  fi
else
  warn "当前环境没有 root/systemd，未安装自动更新 timer；可继续手动运行 ./update.sh。"
fi

say "=============================================="
say "安装完成 ✅"
say "  安装工具： $INSTALLER_VERSION    实际应用： $INSTALL_VERSION（清单来源：$INSTALL_MANIFEST_SOURCE）"
say "  镜像来源： $INSTALL_IMAGE_SOURCE    发生回退：$INSTALL_IMAGE_FALLBACK"
if [ "$BEHIND_PROXY" -eq 1 ]; then
  say "  共存模式：请在宿主反代加一条  $DOMAIN → 127.0.0.1:$PROXY_HTTP_PORT"
  say "  若宿主 nginx/面板拦截 /.well-known/，请按 templates/nginx-matrix-well-known.conf.tpl 配精确路由"
fi
say "  访问地址： https://$DOMAIN"
say "  管理员账号/初始密码见上方 bootstrap 输出（仅显示一次，登录后请修改）"
say "  管理后台： https://$DOMAIN/#/admin"
say "  体检：     ./doctor.sh    升级： ./update.sh"
say "  更新检查： systemctl status guduu-update-agent.timer（客户节点默认不自动安装）"
say "  配置文件： distro/.env（密钥在内，妥善保管）"
say "=============================================="
