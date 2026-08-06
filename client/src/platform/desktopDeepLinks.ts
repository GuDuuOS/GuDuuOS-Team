import type { Router } from 'vue-router'

/**
 * Electron 深链的 Vue 平台适配层。
 * main 进程只负责把受白名单保护的 `guduu://` 转换为内部路由，
 * 真正的登录守卫、邀请加入和页面数据流仍完全由共享 Vue Router/LiveView 处理。
 */

/** 对 main 返回的路由再做一层防御性白名单校验。 */
function trustedDesktopRoute(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 768) return null
  const matched = value.match(/^\/join\/([^/]+)$/)
  if (!matched) return null

  try {
    const spaceId = decodeURIComponent(matched[1])
    const separator = spaceId.indexOf(':')
    if (
      !spaceId.startsWith('!') ||
      separator < 2 ||
      separator === spaceId.length - 1 ||
      /[\u0000-\u0020\u007f/?#\\]/u.test(spaceId)
    ) {
      return null
    }
    // 只接受 main 进程生成的标准编码，避免二次编码或编码斜杠绕过路由边界。
    const canonical = `/join/${encodeURIComponent(spaceId)}`
    return value === canonical ? canonical : null
  } catch {
    return null
  }
}

/**
 * 安装窗口全局深链导航。
 * 监听器先安装、再消费冷启动队列，从而没有“消费与订阅之间”的丢事件窗口。
 * 这个适配在 main.ts 挂载，因此用户停在登录页时也能保留 redirect 并在登录后加入。
 */
export async function installDesktopDeepLinkNavigation(router: Router): Promise<void> {
  const bridge = window.guduuDesktop?.deepLinks
  if (!bridge) return

  const navigate = (candidate: unknown) => {
    const route = trustedDesktopRoute(candidate)
    if (route) void router.push(route)
  }

  bridge.onNavigate(navigate)
  try {
    navigate(await bridge.consumePending())
  } catch {
    // 深链是辅助入口；IPC 暂时不可用不得阻止 App 正常启动。
  }
}
