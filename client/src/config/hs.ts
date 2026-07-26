/**
 * homeserver 地址解析（模块6 OEM 发行版 · 同源模式）
 * --------------------------------------------------------------
 * 主站（app.cosmac.cc）与本地开发：保持原行为，连 https://hs.cosmac.cc。
 * 其他任何域名 = OEM 自部实例：发行版的 Caddy 在**同一个域名**下同时服务
 * 前端静态与 /_matrix、/cosmac 反代（见 distro/templates/Caddyfile.tpl），
 * 所以 homeserver 就是页面自己的源（window.location.origin）——
 * OEM 换任何域名都零配置生效，客户端产物无需按租户重新构建。
 */

/** 走「主站 homeserver」的宿主名单：主站域名 + 本地开发 */
const MAIN_SITE_HOSTS = ['app.cosmac.cc', 'localhost', '127.0.0.1']

/** 当前部署环境的默认 homeserver 基址（不带尾斜杠） */
export function defaultHsUrl(): string {
  // 本地联调覆盖（仅 dev）：client/.env.local 设 VITE_HS_URL 可强制指定 homeserver——
  // 配合 vite.config 的 /_matrix、/cosmac 代理即可全链路连本机 Synapse+bot。
  // 生产构建不设该变量，走下面的正常解析，线上零影响。
  const override = (import.meta as any).env?.VITE_HS_URL
  if (override) return String(override).replace(/\/$/, '')
  if (MAIN_SITE_HOSTS.includes(window.location.hostname)) {
    return 'https://hs.cosmac.cc'
  }
  // OEM 自部：同源即 homeserver
  return window.location.origin
}
