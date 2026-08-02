# OEM 节点 Docker 发布

## 发布链路

1. 严格 `vX.Y.Z` tag 触发 `.github/workflows/release-images.yml`。
2. GitHub Actions 校验 tag、`cosmac.__version__` 与客户端版本完全一致。
3. CI 构建 `linux/amd64`、`linux/arm64` 的 bot/web 镜像并推送 GHCR。
4. CI 把两个多架构 manifest digest、源码 commit 和平台列表用 HMAC 登记到 Nexus。
5. 超管版本中心选择“OEM 节点”时，只能保存已经登记镜像清单的版本。
6. 灰度或全量发布后，宿主更新代理主动领取精确 `仓库@sha256:digest`。
7. 节点先备份数据库并保留当前镜像，再拉取、校验、切换 bot/web；`doctor.sh`
   失败会自动恢复旧镜像并把任务标记失败。

严格 Git tag 更新继续存在，但只用于第一次把旧节点升级到新更新器、升级
Compose/宿主代理自身，或 Docker 发布链路故障时救援。

## 一次性平台配置

### Nexus

在 `/etc/nexus.env` 添加一个至少 32 字符的独立随机值：

```text
NEXUS_RELEASE_WEBHOOK_SECRET=<随机高强度值>
```

重启 Nexus 后，清单入口是：

```text
https://dev-nexus.guduu.co/nexus/release/manifest
```

它不使用管理员 Cookie，只接受五分钟内有效的 HMAC；同版本不同摘要会返回冲突。

### GitHub Actions

在仓库 `Settings → Secrets and variables → Actions` 设置：

- Repository variable `NEXUS_RELEASE_MANIFEST_URL`：上面的 HTTPS 清单入口；
- Repository secret `NEXUS_RELEASE_WEBHOOK_SECRET`：必须与 Nexus 完全一致。

工作流使用仓库自带 `GITHUB_TOKEN` 写入 GHCR，不需要另存上传 PAT。

### OEM 宿主机拉取权限

默认把 GHCR 包保持私有。每台节点在 `/etc/guduu-registry.env` 直接填写一个只具备
`read:packages` 的 GitHub classic PAT，并保持文件权限 `0600`：

```text
GUDUU_REGISTRY_USER=<只读机器账号>
GUDUU_REGISTRY_TOKEN=<read:packages token>
```

不要把令牌写入 `distro/.env`、Nexus、聊天或版本公告。若以后明确把两个镜像包设为
public，可以保持两个值为空，更新器会匿名拉取。

## 灰度与回撤

- 新节点版本先选当前测试节点灰度；安装成功并观察后再推送全部节点。
- 同一发布失败后不会无限重试，需超管点击“重试失败节点”。
- 镜像切换失败会先做单机自动回撤；Nexus 的“历史版本回撤”用于全舰队统一回到旧版。
- 回撤到尚未使用 Docker 清单的历史版本会走严格 Git 救援通道；之后应再次安装一个
  含新版更新器的 bootstrap 版本，恢复日常摘要发布。

## 数据与安全边界

- 镜像只含应用代码和前端静态文件，不含 OEM 域名、KEY、SMTP、数据库或证书。
- `postgres`、`synapse`、Caddy 数据卷和 `.env` 不随应用镜像切换。
- Nexus 不持有 SSH、GHCR 拉取令牌或 Docker socket。
- bot 容器不挂载 Docker socket，无法自行更新宿主机。
- 发布清单只下发受信 GHCR 仓库的完整 SHA-256 摘要，拒绝任意 registry、tag 或命令。
