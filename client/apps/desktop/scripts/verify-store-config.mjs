import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const desktopRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const webRoot = path.resolve(desktopRoot, '../..')

// 这些断言是开发期的快速门禁；正式上架阶段还必须补真实签名、WACK 和商店审核验证。
const files = {
  package: await readFile(path.join(desktopRoot, 'package.json'), 'utf8'),
  webPackage: await readFile(path.join(webRoot, 'package.json'), 'utf8'),
  main: await readFile(path.join(desktopRoot, 'main.mjs'), 'utf8'),
  preload: await readFile(path.join(desktopRoot, 'preload.cjs'), 'utf8'),
  forge: await readFile(path.join(desktopRoot, 'forge.config.cjs'), 'utf8'),
  vite: await readFile(path.join(webRoot, 'vite.config.ts'), 'utf8'),
  index: await readFile(path.join(webRoot, 'index.html'), 'utf8'),
  homeserver: await readFile(path.join(webRoot, 'src/config/hs.ts'), 'utf8'),
  masEntitlements: await readFile(
    path.join(desktopRoot, 'store/macos/entitlements.mas.plist'),
    'utf8'
  )
}

const desktopPackage = JSON.parse(files.package)
const webPackage = JSON.parse(files.webPackage)

const assertions = [
  [files.main.includes('app.enableSandbox()'), 'Electron 全局 sandbox'],
  [files.main.includes('contextIsolation: true'), 'contextIsolation'],
  [files.main.includes('nodeIntegration: false'), 'renderer 禁用 Node'],
  [files.main.includes('webSecurity: true'), 'webSecurity'],
  [files.main.includes("will-attach-webview"), 'webview 拦截'],
  [files.main.includes("const ALLOWED_PERMISSIONS = new Set()"), '默认拒绝系统权限'],
  [files.main.includes("const APP_PROTOCOL = 'guduu-app'"), '本地安全协议'],
  [files.main.includes("Content-Security-Policy"), '桌面 CSP'],
  [files.preload.includes('contextBridge.exposeInMainWorld'), '最小 preload bridge'],
  [files.forge.includes('MakerMSIX'), 'Windows Store MSIX 包装'],
  [files.forge.includes('MakerDMG'), 'macOS 官网 DMG 包装'],
  [files.forge.includes('FuseV1Options.RunAsNode'), 'Electron fuses'],
  [files.forge.includes('stripUnusedMacPermissionDescriptions'), '移除未使用的 macOS 权限说明'],
  [files.forge.includes("'requested-execution-level': 'asInvoker'"), 'Windows 标准用户权限'],
  [files.vite.includes("base: './'"), '本地静态资源相对路径'],
  [files.masEntitlements.includes('com.apple.security.app-sandbox'), 'Mac App Sandbox'],
  [!files.masEntitlements.includes('device.camera'), '未提前索取摄像头权限'],
  [!files.masEntitlements.includes('device.audio-input'), '未提前索取麦克风权限'],
  [!files.index.includes('fonts.googleapis.com'), '不加载远程字体 CSS'],
  [files.homeserver.includes('env?.DEV && override'), '生产构建不读取本地 homeserver 覆盖'],
  [desktopPackage.version === webPackage.version, 'Web/Desktop 版本一致'],
  [!files.package.includes('publish'), '开发期没有发布脚本']
]

const failed = assertions.filter(([passed]) => !passed)
for (const [passed, label] of assertions) {
  console.log(`${passed ? '✓' : '✗'} ${label}`)
}

if (failed.length) process.exitCode = 1
