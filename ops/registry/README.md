# GuDuu 自建镜像仓

本目录是 Nexus 宿主机的双仓部署清单，不包含任何真实凭据。

生产安装前必须确认 `/srv/guduu-registry` 是单独的 Google Cloud
Persistent Disk，而不是 Nexus 系统盘上的普通目录。Registry 只绑定
`127.0.0.1:5000`，对外 TLS 由宿主 Caddy 终止。

凭据分为两类：宿主同步账号可写，仅保存在 root 权限的
`/etc/guduu-registry/skopeo-auth.json`；OEM 节点使用可撤销的只读账号。
初次登录应在服务器终端执行 `skopeo login --authfile ...`，不要把密码
写入 Git、Nexus 数据库或 systemd 命令行。

部署后启用 `guduu-registry-sync.timer`。每次任务通过 Nexus 本机
PostgreSQL 读取已签名登记的 GHCR 摘要，用 `skopeo copy --all
--preserve-digests` 复制，并对自建仓 manifest 重算 SHA-256。任一校验
失败都会让 systemd 任务失败，不会把可移动 tag 当成发布物。
