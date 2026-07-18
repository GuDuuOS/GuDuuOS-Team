#!/usr/bin/env bash
# ============================================================
# CosMac 发行版 —— 升级脚本
# ------------------------------------------------------------
# 拉最新代码 → 重建镜像 → 滚动重启。数据（data/ 与数据库卷）不动。
# 发行版承诺「买断永久含升级」（模块6 拍板），OEM 定期跑这一条即可。
# P1 起：GuDuu Nexus 网关会设「最低兼容版本」，太旧的实例 AI 调用
# 会收到"请先升级"——收到那个提示就来跑本脚本。
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "[失败] 未找到 .env——本机尚未安装，先跑 ./install.sh" >&2; exit 1; }

echo "[CosMac] 拉取最新版本……"
git -C .. pull --ff-only

echo "[CosMac] 重建镜像（前端构建约需几分钟）……"
docker compose build

echo "[CosMac] 滚动重启……"
docker compose up -d

echo "[CosMac] 清理旧镜像……"
docker image prune -f >/dev/null

echo "[CosMac] 升级完成 ✅ 建议跑 ./doctor.sh 体检一遍。"
