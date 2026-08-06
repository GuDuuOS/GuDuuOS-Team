import { reactive } from 'vue'

import defaultLogo from '@/assets/cosmac-logo.png'
import { defaultHsUrl } from '@/config/hs'

/** 节点运行时品牌。公开接口只含名称/Logo，任何 SMTP/API/支付密钥都不会进入这里。 */
export const instanceBrand = reactive({
  productName: 'GuDuu OS',
  companyName: '',
  logoUrl: defaultLogo,
  setupCompleted: true,
  loaded: false,
})

export interface PublicInstanceConfig {
  setup_completed: boolean
  brand?: { product_name?: string; company_name?: string; logo_data_url?: string }
}

/** 把服务器公开品牌数据收口后应用到界面，不接受远程脚本或 CSS。 */
export function applyInstanceConfig(payload: PublicInstanceConfig): PublicInstanceConfig {
  const productName = typeof payload?.brand?.product_name === 'string'
    ? payload.brand.product_name.slice(0, 80)
    : ''
  const companyName = typeof payload?.brand?.company_name === 'string'
    ? payload.brand.company_name.slice(0, 160)
    : ''
  const logo = typeof payload?.brand?.logo_data_url === 'string' ? payload.brand.logo_data_url : ''
  const safeLogo = logo.length <= 1536 * 1024 && /^data:image\/(?:png|jpe?g|webp);base64,/i.test(logo)
    ? logo
    : ''
  instanceBrand.productName = productName || 'GuDuu OS'
  instanceBrand.companyName = companyName
  instanceBrand.logoUrl = safeLogo || defaultLogo
  instanceBrand.setupCompleted = Boolean(payload?.setup_completed)
  instanceBrand.loaded = true
  document.title = instanceBrand.productName
  return {
    setup_completed: instanceBrand.setupCompleted,
    brand: {
      product_name: instanceBrand.productName,
      company_name: instanceBrand.companyName,
      logo_data_url: safeLogo,
    },
  }
}

export async function loadInstanceConfig(
  force = false,
  baseUrl = defaultHsUrl(),
): Promise<PublicInstanceConfig> {
  if (instanceBrand.loaded && !force) {
    return {
      setup_completed: instanceBrand.setupCompleted,
      brand: {
        product_name: instanceBrand.productName,
        company_name: instanceBrand.companyName,
        logo_data_url: instanceBrand.logoUrl === defaultLogo ? '' : instanceBrand.logoUrl,
      },
    }
  }
  try {
    // Electron 的 renderer 由 guduu-app:// 本地协议加载，相对 /cosmac 会错误地
    // 请求本地 App 协议。统一使用已解析的 homeserver 绝对地址，Web/OEM 同样适用。
    const base = baseUrl.replace(/\/$/, '')
    const response = await fetch(`${base}/cosmac/instance/config`, { cache: 'no-store' })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload?.error || '实例配置不可用')
    return applyInstanceConfig(payload)
  } catch {
    // 本地开发或旧后端没有端点时保持历史品牌，并且不强制跳向导。
    instanceBrand.setupCompleted = true
    return { setup_completed: true, brand: { product_name: 'GuDuu OS' } }
  } finally {
    instanceBrand.loaded = true
  }
}
