const MAX_RAW_URL_LENGTH = 1024
const MAX_SPACE_ID_LENGTH = 512

/**
 * 把操作系统传入的 `guduu://` URL 转换成唯一允许的 Vue 内部路由。
 * 首期只支持 `guduu://join/<Matrix Space ID>`，不接受查询参数、hash、账号信息、
 * 文件路径或任意网页 URL。以后增加深链类型时必须在这里逐项扩充白名单。
 *
 * @param {unknown} rawUrl 命令行或 macOS `open-url` 事件传入的未信任值。
 * @returns {string | null} 已编码的 Vue 路由，非法输入返回 null。
 */
export function parseDesktopDeepLink(rawUrl) {
  if (typeof rawUrl !== 'string' || !rawUrl || rawUrl.length > MAX_RAW_URL_LENGTH) return null

  try {
    const candidate = new URL(rawUrl)
    if (
      candidate.protocol !== 'guduu:' ||
      candidate.hostname !== 'join' ||
      candidate.username ||
      candidate.password ||
      candidate.port ||
      candidate.search ||
      candidate.hash
    ) {
      return null
    }

    if (!candidate.pathname.startsWith('/') || candidate.pathname.startsWith('//')) return null
    const encodedSpaceId = candidate.pathname.slice(1)
    if (!encodedSpaceId || encodedSpaceId.includes('/')) return null

    const spaceId = decodeURIComponent(encodedSpaceId)
    const separator = spaceId.indexOf(':')
    const localpart = separator > 0 ? spaceId.slice(1, separator) : ''
    const serverName = separator > 0 ? spaceId.slice(separator + 1) : ''
    if (
      !spaceId.startsWith('!') ||
      spaceId.length > MAX_SPACE_ID_LENGTH ||
      !localpart ||
      !serverName ||
      /[\u0000-\u0020\u007f/?#\\]/u.test(spaceId) ||
      localpart.includes(':')
    ) {
      return null
    }

    return `/join/${encodeURIComponent(spaceId)}`
  } catch {
    return null
  }
}

/**
 * 创建桌面深链交付器。
 * renderer 还没完成路由订阅时，最新一条合法深链会留在 main 进程内存；
 * renderer 通过受信任 IPC 明确消费后，后续深链才会实时推送。
 *
 * @param {{ focusMainWindow: () => void, sendRoute: (route: string) => boolean }} options
 * 主窗口聚焦和定向 renderer 发送能力。
 */
export function createDesktopDeepLinkBroker(options) {
  let pendingRoute = null
  let rendererReady = false

  return {
    /** 校验并交付深链；非法 URL 无任何副作用。 */
    deliver(rawUrl) {
      const route = parseDesktopDeepLink(rawUrl)
      if (!route) return false

      options.focusMainWindow()
      if (!rendererReady || !options.sendRoute(route)) pendingRoute = route
      return true
    },

    /**
     * renderer 订阅完成后消费冷启动队列。
     * 只保留最新一条，避免外部程序在启动期间堆积大量导航任务。
     */
    consumePending() {
      rendererReady = true
      const route = pendingRoute
      pendingRoute = null
      return route
    },

    /** renderer 重载或崩溃后回到排队模式，防止深链在无监听器时丢失。 */
    markRendererUnavailable() {
      rendererReady = false
    }
  }
}
