#!/usr/bin/env bash
# ============================================================
# GuDuu OS 发行版 —— 自诊断脚本（OEM 排障第一入口）
# ------------------------------------------------------------
# 逐项体检并打 ✓/✗，最后汇总。哪项 ✗ 就按提示处理；仍搞不定时，
# 把本脚本完整输出发给技术支持（不含密钥，可放心转发）。
# ============================================================
set -uo pipefail
cd "$(dirname "$0")"

PASS=0; FAIL=0
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '  \033[1;31m✗\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }

echo "== GuDuu OS 实例体检 =="

# ---------- 基础环境 ----------
command -v docker >/dev/null 2>&1 && ok "docker 已安装" || bad "docker 未安装"
[ -f .env ] && ok "配置文件 .env 存在" || bad ".env 不存在——尚未安装？先跑 ./install.sh"
DOMAIN="$(grep -E '^DOMAIN=' .env 2>/dev/null | cut -d= -f2- || true)"
[ -n "$DOMAIN" ] && ok "实例域名：$DOMAIN" || bad ".env 里读不到 DOMAIN"

# ---------- 磁盘 ----------
AVAIL_KB="$(df -Pk . | awk 'NR==2{print $4}')"
if [ "${AVAIL_KB:-0}" -gt 2097152 ]; then ok "磁盘剩余 $((AVAIL_KB/1024/1024)) GB"
else bad "磁盘剩余不足 2GB——媒体/数据库会写满，尽快扩容或清理"; fi

# ---------- 容器状态 ----------
for svc in postgres synapse bot web; do
  state="$(docker compose ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="$svc" '$1==s{print $2}')"
  if [ "$state" = "running" ]; then ok "容器 $svc 运行中"
  else bad "容器 $svc 状态异常（$state）——看日志：docker compose logs $svc"; fi
done

# ---------- DNS ----------
PUB_IP="$(curl -4fsS --max-time 8 https://ifconfig.me 2>/dev/null || true)"
DNS_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '$2=="STREAM"{print $1; exit}' || true)"
if [ -n "$DNS_IP" ] && { [ -z "$PUB_IP" ] || [ "$DNS_IP" = "$PUB_IP" ]; }; then
  ok "DNS 解析正常（$DOMAIN → $DNS_IP）"
elif curl -fsSI --max-time 10 "https://$DOMAIN/" 2>/dev/null \
    | tr -d '\r' | grep -Eiq '^server:[[:space:]]*cloudflare'; then
  # 开启 Cloudflare 橙云后，DNS 本来就应该返回边缘 IP，而不是源站 IP。
  # 继续把两者不同判为故障会导致正常发布被自动回撤。
  ok "DNS 经 Cloudflare 代理（$DOMAIN → ${DNS_IP:-边缘网络}）"
else
  bad "DNS 异常：解析到「${DNS_IP:-无}」，本机公网 IP「${PUB_IP:-未知}」——检查域名 A 记录"
fi

# ---------- HTTPS / 证书（经公网全链路，同时验证 Caddy 与证书）----------
code="$(curl -so /dev/null -w '%{http_code}' --max-time 10 "https://$DOMAIN/" 2>/dev/null || true)"
if [ "$code" = "200" ]; then ok "HTTPS 前端可访问（证书有效）"
else bad "HTTPS 访问异常（HTTP ${code:-超时}）——证书未签出？看日志：docker compose logs web"; fi

# ---------- Matrix API ----------
code="$(curl -so /dev/null -w '%{http_code}' --max-time 10 "https://$DOMAIN/_matrix/client/versions" 2>/dev/null || true)"
[ "$code" = "200" ] && ok "Matrix API 正常" || bad "Matrix API 异常（HTTP ${code:-超时}）——看日志：docker compose logs synapse"

# ---------- Matrix 服务发现 ----------
# 不能只看 HTTP 200：面板的静态兜底页也可能返回 200 HTML。客户端发现还必须带 CORS，
# 否则浏览器从其它域名登录时会拿到 JSON 却被同源策略拦住，表面仍是“找不到服务器”。
client_doc="$(curl -fsS --max-time 10 "https://$DOMAIN/.well-known/matrix/client" 2>/dev/null || true)"
client_headers="$(curl -fsSI --max-time 10 "https://$DOMAIN/.well-known/matrix/client" 2>/dev/null || true)"
if printf '%s' "$client_doc" | grep -Fq '"m.homeserver"' \
    && printf '%s' "$client_doc" | grep -Fq '"base_url"' \
    && printf '%s\n' "$client_headers" | tr -d '\r' \
      | grep -Eiq '^access-control-allow-origin:[[:space:]]*\*'; then
  ok "客户端服务发现正常（JSON + CORS）"
else
  bad "客户端 well-known 异常——应返回 m.homeserver/base_url JSON，并带 Access-Control-Allow-Origin: *"
fi

# 联邦发现同样核对关键 JSON 字段，避免把 nginx/面板的 HTML 成功页误判为正常。
server_doc="$(curl -fsS --max-time 10 "https://$DOMAIN/.well-known/matrix/server" 2>/dev/null || true)"
if printf '%s' "$server_doc" | grep -Fq '"m.server"'; then
  ok "联邦服务发现正常（m.server）"
else
  bad "联邦 well-known 异常——应返回 m.server JSON"
fi

# ---------- GuDuu OS bot ----------
# 任何非 502/超时的响应（含 401/404）都说明 bot 进程活着且路由通
code="$(curl -so /dev/null -w '%{http_code}' --max-time 10 "https://$DOMAIN/cosmac/onboarding/templates" 2>/dev/null || true)"
if [ -n "$code" ] && [ "$code" != "502" ] && [ "$code" != "000" ]; then ok "GuDuu OS 主 AI 服务可达（HTTP $code）"
else bad "GuDuu OS 主 AI 服务不可达——看日志：docker compose logs bot"; fi

# ---------- P1 预留：GuDuu Nexus 网关连通性检查加在这里 ----------

echo "== 结果：$PASS 项通过，$FAIL 项异常 =="
[ "$FAIL" -eq 0 ]
