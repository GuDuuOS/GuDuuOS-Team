const { contextBridge } = require('electron')

// renderer 只需要判断当前平台来选择交互样式；不暴露 ipcRenderer、文件系统或任意调用能力。
contextBridge.exposeInMainWorld(
  'guduuDesktop',
  Object.freeze({
    isDesktop: true,
    platform: process.platform,
    arch: process.arch,
    electronVersion: process.versions.electron
  })
)
