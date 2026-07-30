# GuDuu OS 发行版（OEM 自部版）

> 模块6 P0 产物：把整套 GuDuu OS（Matrix homeserver + 主 AI + 客户端 + HTTPS）
> 打包成 OEM 可以装在**自己服务器、自己域名**上的一键安装栈。
> 装完后在管理后台换 logo / 颜色 / 产品名（P1 皮肤系统），即成 OEM 自己品牌的产品。

## 服务器要求

- 一台**干净**的 Ubuntu 22.04+ / Debian 12 服务器（建议 2 核 4G 起，磁盘 40G+）
- 一个域名，**A 记录已解析**到这台服务器的公网 IP（如 `im.example.com`）
- 防火墙放行 **80 / 443** 端口（Caddy 自动签发 HTTPS 证书要用）
- 一个发信邮箱的 SMTP 账号（可选；用户「邮箱验证码注册」需要它）
- OEM 授权码（向 GuDuu 获取；P0 阶段仅登记，P1 起是 AI 服务的硬凭证）

## 安装（三条命令）

```bash
# 1. 装 Docker（已装可跳过）
curl -fsSL https://get.docker.com | sh

# 2. 获取发行版（P1 起改为凭授权码从 GuDuu Nexus 下载）
git clone <发行版仓库地址> cosmac && cd cosmac/distro

# 3. 一键安装（按提示输入域名/邮箱/SMTP/授权码）
./install.sh
```

装完后：

- 访问 `https://你的域名` 即为完整产品；
- 初始管理员账号密码在安装输出末尾（**仅显示一次**，登录后立即改密）；
- 管理后台在 `https://你的域名/#/admin`（AI 配置 / 技能 / 会员 / 门控等）。

## 日常运维

| 事项 | 命令 |
|---|---|
| 体检（装完必跑 / 出问题先跑） | `./doctor.sh` |
| 升级到最新版 | `./update.sh` |
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
└── docker-compose.yml
```

## 架构与边界（给技术负责人）

- 4 个容器：`postgres`（pgvector）/ `synapse`（Matrix homeserver）/ `bot`（GuDuu OS 主 AI）/ `web`（Caddy）。
  仅 `web` 对公网开放 80/443；其余全部走容器内网。
- 账号身份是 `@用户名:你的域名` —— 数据与身份完全归属本实例（数据主权在 OEM）。
- 联邦范围：GuDuu 生态内互通（P2 起由 GuDuu Nexus 下发成员名单）；不与公网 Matrix 联邦。
- AI 模型：P0 过渡期在 `.env` 里直连厂商；**P1 起统一经 GuDuu Nexus 的 LLM 网关**
  （按授权码计量、token 钱包扣费，实例侧不再出现任何厂商 key）。
