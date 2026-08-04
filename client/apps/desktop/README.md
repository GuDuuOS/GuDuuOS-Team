# GuDuu OS Desktop

桌面端复用 `client/` 的 Vue 3 + TypeScript 页面和业务逻辑，Electron 只提供安全的系统壳。
它不加载线上网页，不在 main/preload 中复制 Matrix 或 GuDuu OS 业务规则。

## 当前包装目标

- macOS 官网直装：`.app` + DMG，发布期使用 Developer ID 签名和 notarization。
- Mac App Store：Electron `mas` 构建 + App Sandbox；商城更新，不启用自有 updater。
- Windows 官网直装：Squirrel 用户级安装，不请求管理员权限。
- Microsoft Store：MSIX；正式 Identity/Publisher 在发布期由 Partner Center 注入。

四个目标共享同一版本、Git commit 和 Vue renderer，签名、权限、更新通道彼此隔离。

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
