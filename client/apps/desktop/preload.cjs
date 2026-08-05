const { contextBridge, ipcRenderer } = require('electron')

const CREDENTIAL_READ_CHANNEL = 'guduu:credentials:read'
const CREDENTIAL_WRITE_CHANNEL = 'guduu:credentials:write'
const CREDENTIAL_CLEAR_CHANNEL = 'guduu:credentials:clear'

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
    })
  })
)
