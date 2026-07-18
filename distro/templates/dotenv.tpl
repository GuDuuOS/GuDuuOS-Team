# ============================================================
# CosMac 发行版 —— .env 模板（install.sh 渲染生成，docker compose 自动读取）
# ------------------------------------------------------------
# ⚠️ 渲染后的 .env 含全部密钥：权限 600、绝不入 git、绝不外传。
# 改完任何值后：docker compose up -d 使其生效。
# ============================================================

# —— 实例身份 ——
DOMAIN={{DOMAIN}}
COSMAC_ADMIN_USER={{ADMIN_USER}}
COSMAC_ADMIN_EMAIL={{ADMIN_EMAIL}}

# —— OEM 授权码（P0 只登记；P1 起是 LLM 网关的硬凭证，没它 AI 不通）——
COSMAC_OEM_KEY={{OEM_KEY}}

# —— 数据库口令（install.sh 随机生成；首次初始化后改这里不会自动改库，别乱动）——
PG_SYNAPSE_PASSWORD={{PG_SYNAPSE_PASSWORD}}
COSMAC_DB_PASSWORD={{COSMAC_DB_PASSWORD}}

# —— appservice 双向密钥（与 data/synapse/appservice-cosmac.yaml 必须一致）——
COSMAC_AS_TOKEN={{AS_TOKEN}}
COSMAC_HS_TOKEN={{HS_TOKEN}}

# —— 管理/注册密钥 ——
COSMAC_ADMIN_TOKEN={{ADMIN_TOKEN}}
COSMAC_REGISTRATION_SHARED_SECRET={{REGISTRATION_SHARED_SECRET}}

# —— OEM 自己的发信邮箱（注册验证码从这里发出；留空则邮箱注册不可用）——
COSMAC_SMTP_HOST={{SMTP_HOST}}
COSMAC_SMTP_PORT={{SMTP_PORT}}
COSMAC_SMTP_USER={{SMTP_USER}}
COSMAC_SMTP_PASSWORD={{SMTP_PASSWORD}}
COSMAC_SMTP_FROM={{SMTP_FROM}}
COSMAC_SMTP_FROM_NAME={{SMTP_FROM_NAME}}

# —— AI 模型 ——
# P0 过渡：直连厂商（在下面填 key）；P1 起统一走 GuDuu Nexus LLM 网关，
# 原厂 key 不再出现在实例侧，此段将被网关地址取代。
# 可选 provider：echo(占位)/claude/openai/deepseek(方舟)/gemini
COSMAC_LLM_PROVIDER=echo
COSMAC_LLM_MODEL=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
ARK_API_KEY=
