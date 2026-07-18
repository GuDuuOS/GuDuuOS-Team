# ============================================================
# CosMac 发行版 —— Synapse homeserver 配置模板
# ------------------------------------------------------------
# install.sh 会把 {{占位符}} 替换成真实值后写到 data/synapse/homeserver.yaml。
# 签名密钥 / 日志配置由「synapse generate」预先生成（install.sh 负责编排顺序），
# 本模板只接管主配置文件。
# ⚠️ 渲染后的文件包含数据库密码和注册密钥，权限 600、绝不入 git。
# ============================================================

# 协议层身份：OEM 自己的域名（账号形如 @xxx:{{DOMAIN}}，联邦身份即 OEM 品牌）
server_name: "{{DOMAIN}}"
public_baseurl: "https://{{DOMAIN}}"

pid_file: /data/homeserver.pid

listeners:
  # 容器内明文 8008：TLS 由 Caddy 终结（x_forwarded 信任反代传来的真实 IP/协议）
  - port: 8008
    tls: false
    type: http
    x_forwarded: true
    bind_addresses: ['0.0.0.0']
    resources:
      - names: [client, federation]
        compress: false

database:
  name: psycopg2
  args:
    user: synapse
    password: "{{PG_SYNAPSE_PASSWORD}}"
    dbname: synapse
    host: postgres
    port: 5432
    cp_min: 5
    cp_max: 10

log_config: "/data/{{DOMAIN}}.log.config"
media_store_path: /data/media_store
max_upload_size: 50M

signing_key_path: "/data/{{DOMAIN}}.signing.key"

# —— 注册策略：开放注册关闭，建号统一走 cosmac 后端的「邮箱验证码 + 共享密钥」——
enable_registration: false
registration_shared_secret: "{{REGISTRATION_SHARED_SECRET}}"

macaroon_secret_key: "{{MACAROON_SECRET_KEY}}"
form_secret: "{{FORM_SECRET}}"

# —— 联邦范围（模块6 已拍板：GuDuu 生态内互通，不接公网 Matrix）——
# P0 白名单只有自己 = 事实上的隔离运行；P2 由 GuDuu Nexus 下发生态成员名单后，
# update 流程会把名单追加到这里（届时此段由 Nexus 数据渲染）。
federation_domain_whitelist:
  - "{{DOMAIN}}"

trusted_key_servers:
  - server_name: "matrix.org"
suppress_key_server_warning: true

# CosMac 主 AI 的 appservice 注册（install.sh 渲染生成）
app_service_config_files:
  - /data/appservice-cosmac.yaml

# 与生产行为对齐：媒体不启用鉴权访问（客户端按此实现）
enable_authenticated_media: false

report_stats: false
