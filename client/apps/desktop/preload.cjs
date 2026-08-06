const { contextBridge, ipcRenderer } = require('electron')

const CREDENTIAL_READ_CHANNEL = 'guduu:credentials:read'
const CREDENTIAL_WRITE_CHANNEL = 'guduu:credentials:write'
const CREDENTIAL_CLEAR_CHANNEL = 'guduu:credentials:clear'
const NOTIFICATION_SHOW_CHANNEL = 'guduu:notifications:show'
const DEEP_LINK_CONSUME_CHANNEL = 'guduu:deep-links:consume-pending'
const DEEP_LINK_NAVIGATE_CHANNEL = 'guduu:deep-links:navigate'
const SERVER_DISCOVER_CHANNEL = 'guduu:servers:discover'

// renderer 只获得逐项命名的能力；绝不暴露 ipcRenderer、safeStorage、文件路径或任意 channel。
contextBridge.exposeInMainWorld(
  'guduuDesktop',
  Object.freeze({
    isDesktop: true,
    platform: process.platform,
    arch: process.arch,
    electronVersion: process.versions.electron,
    credentials: Object.freeze({
      read: () => ipcRenderer.invoke(CREDENTIAL_READ_CHANNEL),
      write: (vault) => ipcRenderer.invoke(CREDENTIAL_WRITE_CHANNEL, vault),
      clear: () => ipcRenderer.invoke(CREDENTIAL_CLEAR_CHANNEL)
    }),
    notifications: Object.freeze({
      show: (payload) => ipcRenderer.invoke(NOTIFICATION_SHOW_CHANNEL, payload)
    }),
    deepLinks: Object.freeze({
      consumePending: () => ipcRenderer.invoke(DEEP_LINK_CONSUME_CHANNEL),
      onNavigate: (callback) => {
        if (typeof callback !== 'function') throw new TypeError('桌面深链回调必须是函数')
        // 只转发 main 进程固定 channel 上的路由字符串，不暴露 event 或 ipcRenderer。
        ipcRenderer.on(DEEP_LINK_NAVIGATE_CHANNEL, (_event, route) => callback(route))
      }
    }),
    servers: Object.freeze({
      discover: (input) => ipcRenderer.invoke(SERVER_DISCOVER_CHANNEL, input)
    })
  })
)
