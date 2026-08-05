import { reactive } from 'vue'

import defaultLogo from '@/assets/cosmac-logo.png'

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

export async function loadInstanceConfig(force = false): Promise<PublicInstanceConfig> {
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
    const response = await fetch('/cosmac/instance/config', { cache: 'no-store' })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload?.error || '实例配置不可用')
    instanceBrand.productName = payload?.brand?.product_name || 'GuDuu OS'
    instanceBrand.companyName = payload?.brand?.company_name || ''
    instanceBrand.logoUrl = payload?.brand?.logo_data_url || defaultLogo
    instanceBrand.setupCompleted = !!payload?.setup_completed
    document.title = instanceBrand.productName
    return payload
  } catch {
    // 本地开发或旧后端没有端点时保持历史品牌，并且不强制跳向导。
    instanceBrand.setupCompleted = true
    return { setup_completed: true, brand: { product_name: 'GuDuu OS' } }
  } finally {
    instanceBrand.loaded = true
  }
}
