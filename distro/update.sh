#!/usr/bin/env bash
# ============================================================
# GuDuu OS 发行版 —— 升级脚本
# ------------------------------------------------------------
# 拉最新代码 → 重建镜像 → 滚动重启。数据（data/ 与数据库卷）不动。
# 发行版承诺「买断永久含升级」（模块6 拍板），OEM 定期跑这一条即可。
# P1 起：GuDuu Nexus 网关会设「最低兼容版本」，太旧的实例 AI 调用
# 会收到"请先升级"——收到那个提示就来跑本脚本。
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "[失败] 未找到 .env——本机尚未安装，先跑 ./install.sh" >&2; exit 1; }

TARGET_REF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) TARGET_REF="${2:-}"; shift 2 ;;
    *) echo "[失败] 未知参数：$1（仅支持 --ref vX.Y.Z）" >&2; exit 1 ;;
  esac
done

if [ -n "$TARGET_REF" ]; then
  # 自动更新端只允许固定形态的版本 tag。这里再次校验（不能只信 Python 代理），
  # 避免未来其他调用方把 ref 当成任意 git 参数注入。
  case "$TARGET_REF" in
    v[0-9]*.[0-9]*.[0-9]*) ;;
    *) echo "[失败] 更新目标必须是 vX.Y.Z tag。" >&2; exit 1 ;;
  esac
  if ! printf '%s' "$TARGET_REF" | grep -Eq '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'; then
    echo "[失败] 更新目标必须是严格的 vX.Y.Z tag。" >&2
    exit 1
  fi
  # 只检查 tracked 文件；.env/data 本来就是实例本地数据。若有人手改了源码，宁可
  # 停下让管理员处理，也不能 merge 后把定制内容悄悄覆盖。
  git -C .. diff --quiet && git -C .. diff --cached --quiet \
    || { echo "[失败] 仓库存在未提交的源码改动，自动升级已停止。" >&2; exit 1; }
  echo "[GuDuu OS] 拉取已发布版本 $TARGET_REF……"
  # 不加 --force：发布 tag 一旦存在就应视为不可变；远端若被移动，本机应报冲突停下，
  # 不能悄悄把同一个版本号换成另一份代码。
  git -C .. fetch origin "refs/tags/$TARGET_REF:refs/tags/$TARGET_REF"
  # 每次都精确检出不可变 tag，而不是 merge：普通升级与“回撤到旧 tag”走同一条受限
  # 路径。detached HEAD 是有意设计——实例只运行发行 tag，不在服务器上开发；以后再
  # 升级到新 tag 仍可直接切换，也不会误改 main 分支指针。
  git -C .. checkout --detach "refs/tags/$TARGET_REF"
else
  echo "[GuDuu OS] 拉取 main 最新版本……"
  git -C .. pull --ff-only
fi

# 1.6.24 以前安装生成的 Caddyfile 没有安全头 import。升级不能整份重渲染，
# 因为 OEM 可能已经改过反代规则；这里只在明确识别到站点块时插入一行，
# 并用固定 import 文本保证重复执行仍然幂等。
SECURITY_IMPORT='    import /etc/caddy/security-headers.caddy'
if ! grep -Fq 'import /etc/caddy/security-headers.caddy' data/caddy/Caddyfile; then
  DOMAIN="$(sed -n 's/^DOMAIN=//p' .env | head -n 1)"
  TARGET_BLOCK=''
  if grep -Fqx ':80 {' data/caddy/Caddyfile; then
    TARGET_BLOCK=':80 {'
  elif [ -n "$DOMAIN" ] && grep -Fqx "$DOMAIN {" data/caddy/Caddyfile; then
    TARGET_BLOCK="$DOMAIN {"
  fi

  if [ -z "$TARGET_BLOCK" ]; then
    echo "[失败] 无法识别 Caddy 站点块，未敢自动修改；请检查 data/caddy/Caddyfile。" >&2
    exit 1
  fi

  # awk 只在第一个精确匹配的站点块后插入，临时文件成功生成后再原子替换，
  # 避免升级中断留下半份配置。
  TEMP_CADDY="$(mktemp data/caddy/Caddyfile.XXXXXX)"
  awk -v target="$TARGET_BLOCK" -v import_line="$SECURITY_IMPORT" '
    { print }
    !inserted && $0 == target { print import_line; inserted = 1 }
    END { if (!inserted) exit 2 }
  ' data/caddy/Caddyfile > "$TEMP_CADDY"
  mv "$TEMP_CADDY" data/caddy/Caddyfile
  echo "[GuDuu OS] 已为旧部署补入网站安全响应头。"
fi

echo "[GuDuu OS] 重建镜像（前端构建约需几分钟）……"
docker compose build

# 先用刚构建的 web 镜像完整解析 Caddyfile（包括上面挂载的安全头片段）。
# 配置有误就在这里停下，不能先把仍在正常服务的旧 web 容器替换掉。
echo "[GuDuu OS] 校验网站网关配置……"
docker compose run --rm --no-deps web caddy validate --config /etc/caddy/Caddyfile

echo "[GuDuu OS] 滚动重启……"
docker compose up -d

echo "[GuDuu OS] 清理旧镜像……"
docker image prune -f >/dev/null

echo "[GuDuu OS] 升级完成 ✅ 建议跑 ./doctor.sh 体检一遍。"
