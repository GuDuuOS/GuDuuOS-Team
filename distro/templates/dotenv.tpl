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
# 机房地域是大屏地图的定位真值；由安装器强制选择，激活重试必须继续携带。
COSMAC_NODE_REGION={{NODE_REGION}}
# 仅当安装阶段 Nexus 兑换暂时失败时由 install.sh 置 1；激活成功会写入 data/cosmac，
# 不把 KEY 或激活结果交给浏览器。
COSMAC_NODE_ACTIVATION_REQUIRED={{NODE_ACTIVATION_REQUIRED}}
# 首次安装由 Nexus 正式发布记录下发；始终冻结到不可变 digest，禁止使用 latest。
COSMAC_VERSION={{INSTALL_VERSION}}
COSMAC_BOT_IMAGE={{BOT_IMAGE}}
COSMAC_WEB_IMAGE={{WEB_IMAGE}}
# 客户节点默认 0：只接收更新通知，管理员在 OS 后台确认后才安装。
# 公司内部灰度节点 #2 可由技术人员明确改成 1。
COSMAC_AUTO_UPDATE=0

# —— 数据库口令（install.sh 随机生成；首次初始化后改这里不会自动改库，别乱动）——
PG_SYNAPSE_PASSWORD={{PG_SYNAPSE_PASSWORD}}
COSMAC_DB_PASSWORD={{COSMAC_DB_PASSWORD}}

# —— appservice 双向密钥（与 data/synapse/appservice-cosmac.yaml 必须一致）——
COSMAC_AS_TOKEN={{AS_TOKEN}}
COSMAC_HS_TOKEN={{HS_TOKEN}}

# —— 管理/注册密钥 ——
COSMAC_ADMIN_TOKEN={{ADMIN_TOKEN}}
COSMAC_REGISTRATION_SHARED_SECRET={{REGISTRATION_SHARED_SECRET}}
# 首次配置向导的密钥加密主密钥；丢失后数据库里的 SMTP/API/支付密钥无法解密。
COSMAC_NODE_SETTINGS_SECRET={{NODE_SETTINGS_SECRET}}

# —— OEM 自己的发信邮箱（注册验证码从这里发出；留空则邮箱注册不可用）——
COSMAC_SMTP_HOST={{SMTP_HOST}}
COSMAC_SMTP_PORT={{SMTP_PORT}}
COSMAC_SMTP_USER={{SMTP_USER}}
COSMAC_SMTP_PASSWORD={{SMTP_PASSWORD}}
COSMAC_SMTP_FROM={{SMTP_FROM}}
COSMAC_SMTP_FROM_NAME={{SMTP_FROM_NAME}}

# —— Cloudflare Turnstile 人机验证（可选；防机器人恶意刷验证码/注册）——
# 两个值都填才生效:去 Cloudflare 控制台 → Turnstile 新建一个小组件,
# 「域名(Hostname)」里必须包含本实例域名(如 {{DOMAIN}}),拿到 Site Key + Secret Key。
# 留空=不启用(注册/找回密码不弹人机验证,仅靠 IP 限频)。填好后 docker compose up -d 生效。
COSMAC_TURNSTILE_SITE_KEY=
COSMAC_TURNSTILE_SECRET=

# —— 单端在线（可选）——
# 留空=多设备可同时在线（标准 Matrix 行为，默认）。填 1=同一账号后登录的踢掉先登录的。
COSMAC_SINGLE_SESSION=

# —— AI 模型（OEM 模式：全部经 GuDuu Nexus 网关，API key 就是你的授权码）——
# 网页发行版强制 OEM 授权，install.sh 会统一填入 Nexus 网关。
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

# —— Claude Agent SDK 执行引擎（可选，默认关）——
# 开启后主 AI 用 Claude Code 同款 harness 跑工具循环（更强的多步执行/自动重试），
# 模型可插拔：Anthropic 官方 或 任何 Anthropic 协议兼容端点（如 DeepSeek /anthropic）。
# 引擎任何失败自动回退内置循环，不影响基础问答。镜像已带 CLI 依赖。
#COSMAC_AGENT_ENGINE=claude_sdk
#COSMAC_SDK_BASE_URL=https://api.deepseek.com/anthropic
#COSMAC_SDK_API_KEY=
#COSMAC_SDK_MODEL=deepseek-chat
