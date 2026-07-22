#!/bin/bash
# ============================================================
# Postgres 首次初始化脚本（docker-entrypoint-initdb.d 机制，仅数据目录为空时跑一次）
# ------------------------------------------------------------
# 职责：在 Synapse 主库之外，为 GuDuu OS 业务层创建独立的库和账号，
# 并预装 pgvector 扩展（知识库向量检索用；这正是发行版选 pgvector 镜像的原因）。
# 密码来自容器环境变量 COSMAC_DB_PASSWORD（compose 从 .env 传入）。
# ============================================================
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	CREATE ROLE cosmac LOGIN PASSWORD '${COSMAC_DB_PASSWORD}';
	CREATE DATABASE cosmac OWNER cosmac;
EOSQL

# pgvector 扩展要装在 cosmac 库里（CREATE EXTENSION 是库级操作）
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname cosmac <<-EOSQL
	CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
