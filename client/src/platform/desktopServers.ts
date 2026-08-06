import type { PublicInstanceConfig } from '@/config/instance'

export interface DesktopServerDiscovery extends PublicInstanceConfig {
  entryUrl: string
  homeserverUrl: string
}

function safeHttpsBaseUrl(value: unknown): string {
  if (typeof value !== 'string' || !value || value.length > 2048) return ''
  try {
    const candidate = new URL(value)
    const isLocal = candidate.hostname === 'localhost' || candidate.hostname === '127.0.0.1'
    if (candidate.protocol !== 'https:' && !(import.meta.env.DEV && isLocal)) return ''
    if (candidate.username || candidate.password || candidate.search || candidate.hash) return ''
    return candidate.toString().replace(/\/$/, '')
  } catch {
    return ''
  }
}

/** renderer 不信任 IPC 回传对象，再做一次形状和 URL 校验。 */
function normalizeDiscovery(value: unknown): DesktopServerDiscovery {
  const payload = value as any
  const entryUrl = safeHttpsBaseUrl(payload?.entryUrl)
  const homeserverUrl = safeHttpsBaseUrl(payload?.homeserverUrl)
  if (!entryUrl || !homeserverUrl || !payload?.brand || typeof payload.brand !== 'object') {
    throw new Error('服务器发现结果无效')
  }
  const productName = typeof payload.brand.product_name === 'string'
    ? payload.brand.product_name.slice(0, 80)
    : 'GuDuu OS'
  const companyName = typeof payload.brand.company_name === 'string'
    ? payload.brand.company_name.slice(0, 160)
    : ''
  const logo = typeof payload.brand.logo_data_url === 'string' ? payload.brand.logo_data_url : ''
  if (logo && (logo.length > 1536 * 1024 || !/^data:image\/(?:png|jpe?g|webp);base64,/i.test(logo))) {
    throw new Error('OEM Logo 格式无效')
  }
  return {
    entryUrl,
    homeserverUrl,
    setup_completed: Boolean(payload.setup_completed),
    brand: {
      product_name: productName || 'GuDuu OS',
      company_name: companyName,
      logo_data_url: logo,
    },
  }
}

/** 桌面通用 App 通过 main 进程发现 OEM，全程不传密码或 token。 */
export async function discoverDesktopHomeserver(input: string): Promise<DesktopServerDiscovery> {
  const bridge = window.guduuDesktop?.servers
  if (!bridge) throw new Error('当前客户端不支持切换服务器')
  return normalizeDiscovery(await bridge.discover(input))
}
