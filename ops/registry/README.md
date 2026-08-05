# GuDuu 自建镜像仓

本目录是 Nexus 宿主机的双仓部署清单，不包含任何真实凭据。

生产安装前必须确认 `/srv/guduu-registry` 是单独的 Google Cloud
Persistent Disk，而不是 Nexus 系统盘上的普通目录。Registry 只绑定
`127.0.0.1:5000`，对外 TLS 由宿主 Caddy 终止。

Registry 自身不启用全局认证：它只监听宿主回环地址，唯一公网入口 Caddy
只允许 `GET/HEAD/OPTIONS`，因此 OEM 和标准 Docker 工具可以匿名拉取，公网
无法发起上传或删除。宿主同步任务直连 `127.0.0.1:5000` 写入，不保存仓库
密码；Nexus Web、节点容器和浏览器都不能访问这个回环写入口。

部署后启用 `guduu-registry-sync.timer`。每次任务通过 Nexus 本机
PostgreSQL 读取已签名登记的 GHCR 摘要，用 `skopeo copy --all
--preserve-digests` 复制，同时建立 `vX.Y.Z` 与 `X.Y.Z` 两个版本 Tag，并对
自建仓 manifest 重算 SHA-256。任一校验失败都会让 systemd 任务失败；节点
安装和回撤始终使用数据库冻结的摘要，不会把 Tag 当成发布物。
