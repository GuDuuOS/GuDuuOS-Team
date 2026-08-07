import { reactive } from 'vue'

import defaultLogo from '@/assets/cosmac-logo.png'
import { defaultHsUrl } from '@/config/hs'

/** 节点运行时品牌。公开接口只含名称/Logo，任何 SMTP/API/支付密钥都不会进入这里。 */
export const instanceBrand = reactive({
  productName: 'GuDuu OS',
  companyName: '',
  logoUrl: defaultLogo,
  reservedBrandAllowed: true,
  setupCompleted: true,
  loaded: false,
})

/** 公开官网字段；仅文本与安全链接，绝不接收远程 HTML/CSS/脚本。 */
export const instanceWebsite = reactive({
  headline: '让沟通、协作与智能助手在一个地方完成',
  description: '面向团队的一体化沟通与智能协作平台。',
  contactEmail: '',
  contactPhone: '',
  contactAddress: '',
  supportUrl: '',
  privacyUrl: '',
  footerText: '',
})

export interface PublicInstanceConfig {
  setup_completed: boolean
  brand?: { product_name?: string; company_name?: string; logo_data_url?: string }
  website?: {
    headline?: string
    description?: string
    contact_email?: string
    contact_phone?: string
    contact_address?: string
    support_url?: string
    privacy_url?: string
    footer_text?: string
  }
  brand_policy?: { reserved_brand_allowed?: boolean }
}

function text(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.trim().slice(0, limit) : ''
}

function publicUrl(value: unknown): string {
  const clean = text(value, 500)
  if (/^\/(?!\/)/.test(clean)) return clean
  try {
    const parsed = new URL(clean)
    return parsed.protocol === 'https:' && !parsed.username && !parsed.password ? clean : ''
  } catch {
    return ''
  }
}

/**
 * 从节点读取真实公开配置。
 *
 * 这一层不做“旧后端兼容”降级，便于路由门禁在网络或服务异常时
 * 明确失败，不把“读取不到”误当成“配置已完成”。
 */
async function fetchInstanceConfig(baseUrl: string): Promise<PublicInstanceConfig> {
  const base = baseUrl.replace(/\/$/, '')
  const response = await fetch(`${base}/cosmac/instance/config`, { cache: 'no-store' })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload?.error || '无法读取节点配置')
  return applyInstanceConfig(payload)
}

/** 严格读取实例配置，专供首次配置路由门禁使用。 */
export async function loadRequiredInstanceConfig(
  baseUrl = defaultHsUrl(),
): Promise<PublicInstanceConfig> {
  try {
    return await fetchInstanceConfig(baseUrl)
  } finally {
    instanceBrand.loaded = true
  }
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
  const reservedBrandAllowed = payload?.brand_policy?.reserved_brand_allowed !== false
  instanceBrand.productName = productName || (reservedBrandAllowed ? 'GuDuu OS' : 'OEM 协作平台')
  instanceBrand.companyName = companyName
  instanceBrand.logoUrl = safeLogo || (reservedBrandAllowed ? defaultLogo : '')
  instanceBrand.reservedBrandAllowed = reservedBrandAllowed
  instanceBrand.setupCompleted = Boolean(payload?.setup_completed)
  instanceBrand.loaded = true
  instanceWebsite.headline = text(payload?.website?.headline, 120)
    || '让沟通、协作与智能助手在一个地方完成'
  instanceWebsite.description = text(payload?.website?.description, 500)
    || '面向团队的一体化沟通与智能协作平台。'
  instanceWebsite.contactEmail = text(payload?.website?.contact_email, 320)
  instanceWebsite.contactPhone = text(payload?.website?.contact_phone, 80)
  instanceWebsite.contactAddress = text(payload?.website?.contact_address, 300)
  instanceWebsite.supportUrl = publicUrl(payload?.website?.support_url)
  instanceWebsite.privacyUrl = publicUrl(payload?.website?.privacy_url)
  instanceWebsite.footerText = text(payload?.website?.footer_text, 240)
  document.title = instanceBrand.productName
  let favicon = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (instanceBrand.logoUrl) {
    if (!favicon) {
      favicon = document.createElement('link')
      favicon.rel = 'icon'
      document.head.appendChild(favicon)
    }
    favicon.href = instanceBrand.logoUrl
  } else {
    favicon?.remove()
  }
  return {
    setup_completed: instanceBrand.setupCompleted,
    brand: {
      product_name: instanceBrand.productName,
      company_name: instanceBrand.companyName,
      logo_data_url: safeLogo,
    },
    website: {
      headline: instanceWebsite.headline,
      description: instanceWebsite.description,
      contact_email: instanceWebsite.contactEmail,
      contact_phone: instanceWebsite.contactPhone,
      contact_address: instanceWebsite.contactAddress,
      support_url: instanceWebsite.supportUrl,
      privacy_url: instanceWebsite.privacyUrl,
      footer_text: instanceWebsite.footerText,
    },
    brand_policy: { reserved_brand_allowed: reservedBrandAllowed },
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
    return await fetchInstanceConfig(baseUrl)
  } catch {
    // 本地开发或旧后端没有端点时保持历史品牌，并且不强制跳向导。
    instanceBrand.setupCompleted = true
    return { setup_completed: true, brand: { product_name: 'GuDuu OS' } }
  } finally {
    instanceBrand.loaded = true
  }
}
