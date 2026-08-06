/**
 * homeserver 地址解析（模块6 OEM 发行版 · 同源模式）
 * --------------------------------------------------------------
 * 当前主客户端（dev-app.guduu.co）与本地开发连接当前 Matrix API
 * https://dev-hs.guduu.co。
 * 其他任何域名 = OEM 自部实例：发行版的 Caddy 在**同一个域名**下同时服务
 * 前端静态与 /_matrix、/cosmac 反代（见 distro/templates/Caddyfile.tpl），
 * 所以 homeserver 就是页面自己的源（window.location.origin）——
 * OEM 换任何域名都零配置生效，客户端产物无需按租户重新构建。
 */

import { cachedActiveAccountSession } from '@/platform/sessionVault'

/** 走「主站 homeserver」的宿主名单：主站域名 + 本地开发 */
const MAIN_SITE_HOSTS = ['dev-app.guduu.co', 'localhost', '127.0.0.1']

/** 会话恢复前校验 homeserver URL，禁止凭据被发往非 HTTPS 或带参数的地址。 */
export function isSafeHomeserverUrl(value: unknown): value is string {
  if (typeof value !== 'string' || !value || value.length > 2048) return false
  try {
    const candidate = new URL(value)
    const isLocal = candidate.hostname === 'localhost' || candidate.hostname === '127.0.0.1'
    if (candidate.protocol !== 'https:' && !isLocal) return false
    return !candidate.username && !candidate.password && !candidate.search && !candidate.hash
  } catch {
    return false
  }
}

/** 当前部署环境的默认 homeserver 基址（不带尾斜杠） */
export function defaultHsUrl(): string {
  // 本地联调覆盖（仅 dev）：client/.env.local 设 VITE_HS_URL 可强制指定 homeserver——
  // 配合 vite.config 的 /_matrix、/cosmac 代理即可全链路连本机 Synapse+bot。
  // 生产构建不设该变量，走下面的正常解析，线上零影响。
  const override = (import.meta as any).env?.VITE_HS_URL
  if ((import.meta as any).env?.DEV && override) return String(override).replace(/\/$/, '')
  if (window.guduuDesktop?.isDesktop) {
    // 桌面 OEM 地址只从本次运行内存中已解密的 safeStorage 会话恢复，
    // 不从可篡改 localStorage 读取；首次切换在登录页当前内存内生效。
    const sessionBaseUrl = cachedActiveAccountSession()?.baseUrl
    if (isSafeHomeserverUrl(sessionBaseUrl)) return sessionBaseUrl.replace(/\/$/, '')
    return 'https://dev-hs.guduu.co'
  }
  if (MAIN_SITE_HOSTS.includes(window.location.hostname)) {
    return 'https://dev-hs.guduu.co'
  }
  // OEM 自部：同源即 homeserver
  return window.location.origin
}
