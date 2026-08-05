import { stat } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import {
  app,
  BrowserWindow,
  ipcMain,
  net,
  Notification,
  protocol,
  safeStorage,
  session,
  shell
} from 'electron'
import squirrelStartup from 'electron-squirrel-startup'

import { createSecureSessionStore } from './secure-session-store.mjs'
import { createDesktopNotificationService } from './desktop-notifications.mjs'

const APP_PROTOCOL = 'guduu-app'
const APP_HOST = 'app'
const APP_ID = 'co.guduu.os.desktop'
const CREDENTIAL_READ_CHANNEL = 'guduu:credentials:read'
const CREDENTIAL_WRITE_CHANNEL = 'guduu:credentials:write'
const CREDENTIAL_CLEAR_CHANNEL = 'guduu:credentials:clear'
const NOTIFICATION_SHOW_CHANNEL = 'guduu:notifications:show'
const ALLOWED_EXTERNAL_PROTOCOLS = new Set(['https:', 'mailto:'])
// renderer 当前不主动索取任何 Chromium 权限；系统通知由 main 进程的
// 最小受控桥实现，不需要把 `notifications` 权限开放给网页。
const ALLOWED_PERMISSIONS = new Set()

protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_PROTOCOL,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: false,
      codeCache: true
    }
  }
])

app.enableSandbox()

if (squirrelStartup) {
  app.quit()
}

let mainWindow = null
const desktopNotifications = createDesktopNotificationService({
  isSupported: () => Notification.isSupported(),
  createNotification: (options) => new Notification(options),
  getMainWindow: () => mainWindow
})
/**
 * 读取桌面开发服务器地址。
 * 生产包永远返回 null，只允许加载签名包内的 renderer；开发期也只接受本机 HTTP，
 * 避免环境变量被误配成远程网页后把 Electron 变成一个可远程换代码的浏览器壳。
 */
function getDevelopmentUrl() {
  if (app.isPackaged || !process.env.GUDUU_DESKTOP_DEV_URL) return null

  const candidate = new URL(process.env.GUDUU_DESKTOP_DEV_URL)
  const isLoopback = candidate.hostname === '127.0.0.1' || candidate.hostname === 'localhost'
  if (candidate.protocol !== 'http:' || !isLoopback) {
    throw new Error('GUDUU_DESKTOP_DEV_URL 只允许本机 HTTP 开发地址')
  }
  return candidate
}

/** 判断 URL 是否属于当前受信任的 renderer 来源。 */
function isTrustedRendererUrl(rawUrl) {
  try {
    const candidate = new URL(rawUrl)
    const developmentUrl = getDevelopmentUrl()
    if (developmentUrl) return candidate.origin === developmentUrl.origin
    return candidate.protocol === `${APP_PROTOCOL}:` && candidate.hostname === APP_HOST
  } catch {
    return false
  }
}

/**
 * 校验 IPC 是否由当前主窗口的顶层受信任页面发出。
 * 只看 sender 的历史 URL 不够，必须使用本次消息对应的 senderFrame，拒绝子 frame 和已导航页面。
 */
function isTrustedIpcSender(event) {
  return Boolean(
    mainWindow &&
      !mainWindow.isDestroyed() &&
      event.sender === mainWindow.webContents &&
      event.senderFrame === mainWindow.webContents.mainFrame &&
      isTrustedRendererUrl(event.senderFrame?.url)
  )
}

/**
 * 注册桌面凭据仓库的三个最小 IPC 方法。
 * renderer 只能整仓读取、写入或清除经过主进程校验的会话结构，拿不到文件路径和
 * safeStorage 本体；清除方法用于钥匙串暂不可用时仍能可靠退出本机账号。
 */
function installSecureCredentialIpc() {
  const credentialStore = createSecureSessionStore({
    safeStorage,
    userDataPath: app.getPath('userData')
  })

  ipcMain.handle(CREDENTIAL_READ_CHANNEL, async (event) => {
    if (!isTrustedIpcSender(event)) throw new Error('拒绝不受信任的桌面凭据读取请求')
    return credentialStore.read()
  })
  ipcMain.handle(CREDENTIAL_WRITE_CHANNEL, async (event, vault) => {
    if (!isTrustedIpcSender(event)) throw new Error('拒绝不受信任的桌面凭据写入请求')
    await credentialStore.write(vault)
  })
  ipcMain.handle(CREDENTIAL_CLEAR_CHANNEL, async (event) => {
    if (!isTrustedIpcSender(event)) throw new Error('拒绝不受信任的桌面凭据清除请求')
    await credentialStore.clear()
  })
}

/**
 * 注册只能展示纯文本的系统通知 IPC。
 * 参数校验、后台判定和限流都在 main 进程执行，renderer 无法指定图标、
 * 本地路径或点击后要打开的协议。
 */
function installDesktopNotificationIpc() {
  ipcMain.handle(NOTIFICATION_SHOW_CHANNEL, (event, payload) => {
    if (!isTrustedIpcSender(event)) throw new Error('拒绝不受信任的桌面通知请求')
    return desktopNotifications.show(payload)
  })
}

/**
 * 把允许的网页或邮件链接交给系统默认应用。
 * 这里只按协议放行，不执行自定义协议、文件路径或脚本 URL。
 */
async function openExternalUrl(rawUrl) {
  try {
    const candidate = new URL(rawUrl)
    if (!ALLOWED_EXTERNAL_PROTOCOLS.has(candidate.protocol)) return
    await shell.openExternal(candidate.toString())
  } catch {
    // 非法 URL 直接丢弃，绝不交给系统协议处理器。
  }
}

/**
 * 将 guduu-app URL 安全映射到打包后的 renderer 文件。
 * path.resolve 后再次验证根目录，防止编码路径或 `..` 读取 ASAR 中的其他文件。
 */
async function resolveRendererFile(requestUrl) {
  const rendererRoot = path.resolve(app.getAppPath(), 'renderer')
  const requestedPath = decodeURIComponent(new URL(requestUrl).pathname).replace(/^\/+/, '')
  const relativePath = requestedPath || 'index.html'
  let candidatePath = path.resolve(rendererRoot, relativePath)

  if (candidatePath !== rendererRoot && !candidatePath.startsWith(`${rendererRoot}${path.sep}`)) {
    return null
  }

  try {
    const fileStat = await stat(candidatePath)
    if (fileStat.isDirectory()) candidatePath = path.join(candidatePath, 'index.html')
    return candidatePath
  } catch {
    // Vue history 路由回退到入口页；静态资源缺失仍返回 404。
    if (path.extname(relativePath)) return null
    return path.join(rendererRoot, 'index.html')
  }
}

/** 注册只读取本地 renderer 的安全自定义协议。 */
async function registerLocalRendererProtocol() {
  protocol.handle(APP_PROTOCOL, async (request) => {
    const filePath = await resolveRendererFile(request.url)
    if (!filePath) return new Response('Not found', { status: 404 })
    return net.fetch(pathToFileURL(filePath).toString())
  })
}

/**
 * 给本地页面附加 CSP。
 * Matrix/OEM API 允许 HTTPS/WSS 数据连接，但脚本、字体与 frame 仍只能来自安装包。
 */
function installContentSecurityPolicy() {
  session.defaultSession.webRequest.onHeadersReceived(
    { urls: [`${APP_PROTOCOL}://*/*`] },
    (details, callback) => {
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          'Content-Security-Policy': [
            "default-src 'self'; " +
              "script-src 'self'; " +
              "style-src 'self' 'unsafe-inline'; " +
              "img-src 'self' data: blob: https:; " +
              "media-src 'self' blob: https:; " +
              "connect-src 'self' https: wss:; " +
              "font-src 'self' data:; " +
              "object-src 'none'; frame-src 'none'; base-uri 'none'; " +
              "form-action 'self'; worker-src 'self' blob:"
          ]
        }
      })
    }
  )
}

/**
 * 默认拒绝 Chromium 的全部系统权限。
 * 新功能确实需要摄像头、麦克风或通知时，必须同时补白名单、平台声明和真机测试。
 */
function installPermissionPolicy() {
  session.defaultSession.setPermissionCheckHandler(
    (webContents, permission, requestingOrigin) =>
      Boolean(webContents) &&
      isTrustedRendererUrl(requestingOrigin) &&
      ALLOWED_PERMISSIONS.has(permission)
  )

  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(isTrustedRendererUrl(webContents.getURL()) && ALLOWED_PERMISSIONS.has(permission))
  })
}

/**
 * 接受操作系统传入的 GuDuu 深链并唤醒既有窗口。
 * 当前阶段不把未经校验的深链内容送入 renderer；具体业务路由启用时再定义显式契约。
 */
function deliverDeepLink(rawUrl) {
  try {
    const candidate = new URL(rawUrl)
    if (candidate.protocol !== 'guduu:') return
    if (mainWindow) {
      mainWindow.show()
      mainWindow.focus()
    }
  } catch {
    // 忽略畸形深链。
  }
}

/** 创建唯一主窗口，并把所有导航和新窗口行为收口到白名单。 */
function createMainWindow() {
  mainWindow = new BrowserWindow({
    title: 'GuDuu OS',
    width: 1360,
    height: 860,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    backgroundColor: '#f7f8fa',
    autoHideMenuBar: process.platform !== 'darwin',
    webPreferences: {
      preload: path.join(import.meta.dirname, 'preload.cjs'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      navigateOnDragDrop: false,
      spellcheck: true,
      devTools: !app.isPackaged
    }
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void openExternalUrl(url)
    return { action: 'deny' }
  })

  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (isTrustedRendererUrl(url)) return
    event.preventDefault()
    void openExternalUrl(url)
  })

  mainWindow.webContents.on('will-attach-webview', (event) => {
    event.preventDefault()
  })

  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  const developmentUrl = getDevelopmentUrl()
  void mainWindow.loadURL(developmentUrl?.toString() ?? `${APP_PROTOCOL}://${APP_HOST}/index.html`)
}

const singleInstanceLock = !squirrelStartup && app.requestSingleInstanceLock()
if (!singleInstanceLock) {
  app.quit()
} else {
  app.on('second-instance', (_event, commandLine) => {
    const deepLink = commandLine.find((argument) => argument.startsWith('guduu://'))
    if (deepLink) deliverDeepLink(deepLink)
    mainWindow?.show()
    mainWindow?.focus()
  })

  app.on('open-url', (event, url) => {
    event.preventDefault()
    deliverDeepLink(url)
  })

  app.whenReady().then(async () => {
    app.setAppUserModelId(APP_ID)
    app.setAsDefaultProtocolClient('guduu')
    await registerLocalRendererProtocol()
    installContentSecurityPolicy()
    installPermissionPolicy()
    installSecureCredentialIpc()
    installDesktopNotificationIpc()
    createMainWindow()
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow()
  })

  app.on('window-all-closed', () => app.quit())
}
