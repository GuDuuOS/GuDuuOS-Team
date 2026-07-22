# ============================================================
# GuDuu OS 发行版 —— 主 AI Application Service 注册模板
# ------------------------------------------------------------
# install.sh 渲染后写到 data/synapse/appservice-cosmac.yaml（Synapse 读），
# 同一对 token 也写进 .env 喂给 bot 容器——两边必须一致，否则事件推送/调用全挂。
# ⚠️ 渲染后的文件是高权限凭证，权限 600、绝不入 git。
# ============================================================

id: cosmac-master-ai

# Synapse 往哪推事件：bot 容器的内网地址（不出宿主机）
url: "http://bot:9000"

# bot → Synapse 的身份凭证 / Synapse → bot 的来源校验凭证（install.sh 随机生成）
as_token: "{{AS_TOKEN}}"
hs_token: "{{HS_TOKEN}}"

# 主 AI 账号 localpart（@guduu:<域名>）。
# ⚠️ 与 cosmac/config.py 强耦合（bot_user_id 默认值/前端引用），stage2 品牌迁移
# 前保持 guduu，别单独在发行版改（见 config.py 顶部注释）。
sender_localpart: guduu

namespaces:
  users:
    # 本 appservice 拥有 @guduu 及 @guduu_xxx 形式的 AI 子账号
    # （单引号 YAML：\. 就是正则转义点，无需双写反斜杠）
    - exclusive: false
      regex: '@guduu.*:{{DOMAIN_REGEX}}'
  aliases:
    # 预留控制室别名：bootstrap 以 bot 身份创建 #cosmac-ctrl 需要它，
    # 否则 Synapse 报 M_EXCLUSIVE 拒绝（首次 VM 实测踩坑）。
    - exclusive: true
      regex: '#cosmac-ctrl.*'
  rooms: []

# 主 AI 不限速（它要服务全实例的对话）
rate_limited: false
