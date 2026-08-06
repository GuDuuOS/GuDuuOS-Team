# GuDuu OS 发行版（OEM 自部版）

> 模块6 P0 产物：把整套 GuDuu OS（Matrix homeserver + 主 AI + 客户端 + HTTPS）
> 打包成 OEM 可以装在**自己服务器、自己域名**上的一键安装栈。
> 装完后在管理后台换 logo / 颜色 / 产品名（P1 皮肤系统），即成 OEM 自己品牌的产品。

## 服务器要求

- 一台**干净**的 Ubuntu 22.04+ / Debian 12 服务器（建议 2 核 4G 起，磁盘 40G+）
- 一个已经审批的部署域名（如 `im.example.com`）；A 记录可以在安装前或
  安装后解析到服务器公网 IP，但解析生效前 HTTPS 无法签发
- 防火墙放行 **80 / 443** 端口（Caddy 自动签发 HTTPS 证书要用）
- 一个发信邮箱的 SMTP 账号（可选；安装后在首次网页向导配置）
- 已审批并领取的 OEM 授权码；授权码与审批域名严格绑定

## 安装（一条命令）

```bash
curl -fsSL https://dev-nexus.guduu.co/portal/install.sh | sudo bash -s -- --domain im.example.com
```

请从 Nexus OEM 门户“我的 KEY”页面复制完整命令；系统会自动带入该 KEY
审批的域名。命令不携带长期 OEM KEY，安装过程会在 SSH 终端交互询问，
避免授权码留在 shell history。

干净 Ubuntu 22.04+ / Debian 12+ 上不需要预装 Docker：安装器会自动准备
基础工具、Docker Engine 和 Compose 插件。节点镜像默认从
Docker Hub `guduu/` 按不可变 digest 匿名拉取，便于使用标准镜像加速器；失败时
依次回退 `registry.guduu.co` 和同摘要 GHCR；
客户不需要 GitHub 账号或镜像仓 Token。

装完后：

- 如果 DNS 还没有解析，先在域名服务商添加指向服务器公网 IP 的 A 记录；
- DNS 生效后 Caddy 会自动签发 HTTPS，访问 `https://你的域名`；
- 初始管理员账号密码在安装输出末尾（**仅显示一次**，登录后立即改密）；
- 初次登录必须完成网页向导，配置产品名称与 Logo、发信邮箱、主 AI API；
- OEM 节点支付渠道当前暂停接入，向导中仅显示“待接入”，不对客户开放收款；
- 完成后可从 `https://你的域名/#/admin` 进入管理后台。

## 日常运维

| 事项 | 命令 |
|---|---|
| 体检（装完必跑 / 出问题先跑） | `./doctor.sh` |
| 检查可用更新 | 宿主代理定时拉取 Nexus 更新信息，普通 OEM 不会自动安装 |
| 安装新版/回撤 | 由节点管理员确认后按不可变 digest 拉取；失败自动切回原镜像 |
| 更新器引导或故障救援 | `./update.sh --ref vX.Y.Z`（严格 Git tag，现场构建） |
| 查看自动更新计划 | `systemctl status guduu-update-agent.timer` |
| 查看最近更新日志 | `journalctl -u guduu-update-agent.service -n 100` |
| 看某个组件日志 | `docker compose logs -f synapse\|bot\|web\|postgres` |
| 重启全栈 | `docker compose restart` |
| 备份 | 停机备份 `distro/data/` 整个目录 + `distro/.env` |

## 宿主反代与 Matrix 服务发现

使用 `install.sh --behind-proxy` 时，宿主 nginx/Caddy 应把整个域名反代到安装时指定的
本地端口，`/.well-known/matrix/client` 和 `/.well-known/matrix/server` 也必须到达容器。

宝塔等面板经常自动生成 `location /.well-known/`，把这段路径当成本地静态目录；目录里
没有 Matrix JSON 时就会返回 404，导致标准客户端无法通过域名发现登录服务器。处理方式：

- 实例公开域名与 Synapse `server_name` 相同：删除该静态拦截，让请求继续反代到容器；
- 公开域名是实例别名：渲染并 include
  `templates/nginx-matrix-well-known.conf.tpl`，分别填写公开域名和真实 `server_name`；
- 改完先执行 `nginx -t`，成功后再 reload，最后运行 `./doctor.sh`。体检会同时校验
  客户端 JSON、CORS 和联邦 `m.server`，不再只凭 HTTP 200 判断。

## 目录结构（装完后）

```
distro/
├── .env                    # 全部密钥与配置（600 权限，绝不外传/入 git）
├── data/
│   ├── postgres/           # 数据库（Synapse + cosmac 两库）
│   ├── synapse/            # homeserver.yaml / 签名密钥 / 媒体文件
│   └── caddy/              # Caddyfile / HTTPS 证书
├── install.sh / doctor.sh / update.sh
├── update_agent.py         # 每 5 分钟向 Nexus 检查已分配版本并上报结果
├── apply_images.py         # 按摘要切换 bot/web，体检失败自动回撤
└── docker-compose.yml
```

## 架构与边界（给技术负责人）

- 4 个容器：`postgres`（pgvector）/ `synapse`（Matrix homeserver）/ `bot`（GuDuu OS 主 AI）/ `web`（Caddy）。
  仅 `web` 对公网开放 80/443；其余全部走容器内网。
- 账号身份是 `@用户名:你的域名` —— 数据与身份完全归属本实例（数据主权在 OEM）。
- 联邦范围：GuDuu 生态内互通（P2 起由 GuDuu Nexus 下发成员名单）；不与公网 Matrix 联邦。
- AI 模型：首次网页向导可自由选择 API 接入方；密钥用节点主密钥加密保存，
  不写入镜像、日志或浏览器存储。
- 版本更新：GitHub Actions 从严格 `vX.Y.Z` tag 构建 bot/web 多架构镜像，Nexus 冻结
  `ghcr.io/...@sha256:...`；宿主机 systemd timer 主动领取后先备份数据库、保留旧镜像、
  只切换 bot/web 并运行 `doctor.sh`，失败自动回撤。更新器/Compose 自身引导或救援才走
  严格 Git tag。Nexus 不保存 OEM SSH/仓库凭据，bot 容器也不接触 Docker socket。
- Docker Hub、GHCR 与 `registry.guduu.co` 都必须允许匿名只读，同时提供
  `vX.Y.Z` 和 `X.Y.Z` 两个人工排障 Tag。安装和更新始终使用发布清单冻结的
  `@sha256:digest`，不依赖可移动 Tag。
