/**
 * 桌面系统通知的共享平台适配层。
 * Vue 业务页只表达“这里有一条值得提醒的消息”，是否处于后台、是否支持
 * 系统通知及限流策略都由 Electron main 进程决定。Web 端没有桌面桥时安静返回，
 * 不会因为复用同一份 LiveView 而弹浏览器授权框。
 */

export type DesktopNotificationResult = 'shown' | 'suppressed' | 'unsupported'

export interface DesktopNotificationPayload {
  title: string
  body: string
}

/**
 * 请求桌面系统通知；非 Electron 或桥调用失败时按 unsupported 处理。
 * 通知是辅助提醒，不得阻断 Matrix sync 和页内 toast。
 */
export async function showDesktopNotification(
  payload: DesktopNotificationPayload
): Promise<DesktopNotificationResult> {
  const bridge = window.guduuDesktop?.notifications
  if (!bridge) return 'unsupported'

  try {
    return await bridge.show(payload)
  } catch {
    return 'unsupported'
  }
}
