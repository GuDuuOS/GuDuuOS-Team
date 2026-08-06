# GuDuu OS Desktop

桌面端复用 `client/` 的 Vue 3 + TypeScript 页面和业务逻辑，Electron 只提供安全的系统壳。
它不加载线上网页，不在 main/preload 中复制 Matrix 或 GuDuu OS 业务规则。

## 当前包装目标

- macOS 官网直装：`.app` + DMG，发布期使用 Developer ID 签名和 notarization。
- Mac App Store：Electron `mas` 构建 + App Sandbox；商城更新，不启用自有 updater。
- Windows 官网直装：Squirrel 用户级安装，不请求管理员权限。
- Microsoft Store：MSIX；正式 Identity/Publisher 在发布期由 Partner Center 注入。

四个目标共享同一版本、Git commit 和 Vue renderer，签名、权限、更新通道彼此隔离。

## 会话安全

- Matrix access token、多账号会话和 device ID 只由 Electron main 进程使用异步
  `safeStorage` 加密后写入应用私有 `userData`。
- renderer 只通过校验 sender 的最小 IPC 读写完整会话仓库，拿不到文件路径、
  `safeStorage` 或任意 IPC channel。
- `localStorage` 仅保存 userId 和显示名等非敏感界面元数据；发现旧版明文会话时，
  必须在安全写入成功后才删除旧值。系统钥匙串不可用时禁止回退明文。

## 系统通知

- 现有“新私信”业务提醒复用同一份 Vue 逻辑；Web 保留页内 toast，Electron
  在主窗口不聚焦时由 main 进程补充操作系统通知。
- preload 只暴露纯文本 `show` 方法；main 进程校验 sender、字段和长度，并限流与
  限制同时存活数量，不允许 renderer 传图标路径、URL 或任意 Notification 选项。
- 点击系统通知只恢复并聚焦 GuDuu OS 主窗口，不打开外部协议。本阶段不接入
  后台推送；App 完全退出后的离线通知属于后续 APNs/FCM/Matrix push gateway 模块。

## 安全深链

- 首期只接受 `guduu://join/<Matrix Space ID>`，映射到共享 Vue 客户端已有的
  `/join/:space` 路由；登录、邀请验证和真正加入仍由共享业务层执行。
- main 进程拒绝其他协议、深链类型、查询参数、hash、路径穿越和畸形
  Space ID；preload 只提供消费待处理路由和订阅导航两个命名能力。
- 冷启动、已运行的第二实例、macOS `open-url` 和 renderer 重载都经过 main 内存队列；
  登录页也持续订阅，未登录用户会在登录后继续进入邀请流程。

## 服务器请求路由

- Electron renderer 从 `guduu-app://` 本地协议加载，所有 Matrix 与
  `/cosmac` 业务请求必须使用已解析的 homeserver 绝对地址。
- 实例品牌、节点设置和节点更新应与当前登录的 Matrix 服务器同源；
  未登录时的鉴权请求禁止降级为相对 URL。
- `npm run check` 会静态拦截业务层新增的相对 `fetch('/cosmac...')`
  调用，避免 Web 端正常、安装包内失效的回归。

## OEM 服务器发现

- 登录页可输入 OEM 域名，main 进程依次读取
  `/.well-known/matrix/client`、`/_matrix/client/versions` 与
  `/cosmac/instance/config`，确认该域名同时具备 Matrix 和 GuDuu OS 能力。
- 发现 IPC 只接收域名、只返回受限的公开品牌数据；生产强制
  HTTPS，限制超时和响应大小，拒绝带凭据/参数的 URL 与非图片 Logo。
- 未登录时的选择不写入 `localStorage`；登录成功后 homeserver 才随会话
  进入 `safeStorage`。桌面冷启动先解密活动会话，再加载对应 OEM 品牌。
- 兼容旧节点：仅当新品牌端点明确返回 404，并经现有 GuDuu 公开认证
  配置端点确认后，才使用通用品牌；网络、TLS、大小等错误不会被降级掩盖。

## 本地开发

在本目录安装依赖后：

```bash
npm install
npm run check
npm run dev
```

构建未签名的本机 macOS 包：

```bash
npm run package:mac
```

Windows 的 Squirrel/MSIX maker 以及 Windows App Certification Kit 必须在 Windows
环境运行。当前阶段禁止运行商店提交、公开下载、正式签名和自动更新流程。
