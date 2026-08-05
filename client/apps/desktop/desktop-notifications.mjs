const MAX_TITLE_LENGTH = 80
const MAX_BODY_LENGTH = 280
const MIN_INTERVAL_MS = 1500
const MAX_ACTIVE_NOTIFICATIONS = 4

/**
 * 把 renderer 传来的系统通知数据收紧为唯一允许的结构。
 * 这里不接受图标路径、点击 URL 或任意选项，避免 renderer 把本地文件或
 * 系统协议塞进 Notification。
 *
 * @param {unknown} payload IPC 收到的未信任数据。
 * @returns {{ title: string, body: string }} 可安全交给 Electron Notification 的文本。
 */
export function validateDesktopNotificationPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('桌面通知参数无效')
  }

  const keys = Object.keys(payload)
  if (keys.length !== 2 || !keys.includes('title') || !keys.includes('body')) {
    throw new Error('桌面通知字段无效')
  }

  const title = typeof payload.title === 'string' ? payload.title.trim() : ''
  const body = typeof payload.body === 'string' ? payload.body.trim() : ''
  if (!title || title.length > MAX_TITLE_LENGTH) {
    throw new Error('桌面通知标题无效')
  }
  if (!body || body.length > MAX_BODY_LENGTH) {
    throw new Error('桌面通知正文无效')
  }

  return { title, body }
}

/**
 * 创建桌面系统通知服务。
 * 服务在 main 进程决定是否展示：窗口已聚焦时保留页内 toast，只有应用
 * 处于后台时才调用操作系统。这样 Web 与 Desktop 的业务规则不会被复制到 main。
 *
 * @param {{
 *   isSupported: () => boolean,
 *   createNotification: (options: { title: string, body: string, silent: boolean }) => {
 *     once: (event: string, listener: () => void) => void,
 *     show: () => void,
 *     close: () => void
 *   },
 *   getMainWindow: () => null | {
 *     isDestroyed: () => boolean,
 *     isFocused: () => boolean,
 *     isMinimized: () => boolean,
 *     restore: () => void,
 *     show: () => void,
 *     focus: () => void
 *   },
 *   now?: () => number
 * }} options Electron 能力与可测试时钟。
 */
export function createDesktopNotificationService(options) {
  const activeNotifications = new Set()
  const now = options.now ?? Date.now
  let lastShownAt = Number.NEGATIVE_INFINITY

  return {
    /**
     * 展示一条系统通知，并返回真实处理结果供 renderer 诊断。
     * @param {unknown} payload 未信任 IPC 数据。
     * @returns {'shown' | 'suppressed' | 'unsupported'} 展示、抑制或平台不支持。
     */
    show(payload) {
      const normalized = validateDesktopNotificationPayload(payload)
      const window = options.getMainWindow()

      if (!options.isSupported()) return 'unsupported'
      if (!window || window.isDestroyed() || window.isFocused()) return 'suppressed'

      const currentTime = now()
      if (
        currentTime - lastShownAt < MIN_INTERVAL_MS ||
        activeNotifications.size >= MAX_ACTIVE_NOTIFICATIONS
      ) {
        return 'suppressed'
      }

      const notification = options.createNotification({
        ...normalized,
        silent: false
      })
      activeNotifications.add(notification)
      lastShownAt = currentTime

      const release = () => activeNotifications.delete(notification)
      notification.once('close', release)
      notification.once('failed', release)
      notification.once('click', () => {
        release()
        // Windows 最小化窗口先 restore 再 show/focus，否则通知点击可能只让
        // 任务栏闪烁，却没把用户带回工作台。
        if (window.isMinimized()) window.restore()
        window.show()
        window.focus()
        notification.close()
      })
      notification.show()
      return 'shown'
    }
  }
}
