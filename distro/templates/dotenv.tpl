# ============================================================
# GuDuu OS 发行版 —— .env 模板（install.sh 渲染生成，docker compose 自动读取）
# ------------------------------------------------------------
# ⚠️ 渲染后的 .env 含全部密钥：权限 600、绝不入 git、绝不外传。
# 改完任何值后：docker compose up -d 使其生效。
# ============================================================

# —— 实例身份 ——
DOMAIN={{DOMAIN}}
COSMAC_ADMIN_USER={{ADMIN_USER}}
COSMAC_ADMIN_EMAIL={{ADMIN_EMAIL}}

# —— OEM 授权码（一码两用：装机兑换凭证 + LLM 网关/心跳的运行时凭证）——
COSMAC_OEM_KEY={{OEM_KEY}}
# GuDuu Nexus 母舰地址（心跳上报 + LLM 网关都指它）
COSMAC_NEXUS_URL={{NEXUS_URL}}

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

# —— AI 模型（OEM 模式：全部经 GuDuu Nexus 网关，API key 就是你的授权码）——
# install.sh 已按是否有授权码自动填好；独立模式(无授权码)默认 echo 占位。
# 可选 provider：echo(占位)/claude/openai/deepseek(方舟)/gemini
COSMAC_LLM_PROVIDER={{LLM_PROVIDER}}
COSMAC_LLM_MODEL={{LLM_MODEL}}
# 经网关的通道地址与凭证（凭证=OEM 授权码；原厂 key 永远不在实例侧出现）
ARK_BASE_URL={{ARK_BASE_URL}}
ARK_API_KEY={{ARK_API_KEY}}
ANTHROPIC_BASE_URL={{ANTHROPIC_BASE_URL}}
ANTHROPIC_API_KEY={{ANTHROPIC_API_KEY}}
OPENAI_BASE_URL={{OPENAI_BASE_URL}}
OPENAI_API_KEY={{OPENAI_API_KEY}}
