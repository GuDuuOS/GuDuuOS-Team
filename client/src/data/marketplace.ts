/** AI Agent 商城的分类/文案元信息。
 *  ⚠️ 商品数据不在这里——商城列的是平台**真实资源**（全局智能体/技能/工作流/平台知识库），
 *  由 bot 端点 /cosmac/market/catalog 按登录人实时返回（含解锁状态），见 client.ts fetchMarketCatalog。 */

export type MarketCat = 'agent' | 'skill' | 'workflow' | 'knowledge' | 'cagent' | 'cskill'

/** 分类元信息：标签 + 主题色（与后端 item.kind 一一对应） */
export const CAT_META: Record<MarketCat, { label: string; color: string }> = {
  agent:     { label: 'AI 同事',  color: '#c96442' },
  skill:     { label: '技能',     color: '#6b8e4e' },
  workflow:  { label: '工作流',   color: '#b58932' },
  knowledge: { label: '知识库',   color: '#8a6a8a' },
  // 创作者商城(Token 经济 P2):加入个人名册时不扣，实际使用按次扣 token；UI 禁止称“免费获取”
  cagent:    { label: '创作者',   color: '#4a7b9d' },
  // 创作者上架的技能:一次性买断(获取时付清、之后永久用)
  cskill:    { label: '创作者技能', color: '#5b7f6b' }
}

/** 解锁要求（后端 access 字段）→ 商城卡片上的徽标文案与颜色。
 *  变现模型是会员订阅：付费项不标单价，标「所需会员等级」，点击引导升级会员。 */
export function accessBadge(access: string): { label: string; cls: 'free' | 'tier' | 'scoped' } {
  const a = (access || '').trim()
  if (!a || a === 'public') return { label: '免费', cls: 'free' }
  if (a === 'paid') return { label: '付费会员', cls: 'tier' }
  if (a === 'creator') return { label: '创作者会员', cls: 'tier' }
  if (a.startsWith('tpl:')) return { label: '入驻模板专属', cls: 'scoped' }
  if (a === 'admin') return { label: '仅管理员', cls: 'scoped' }
  return { label: '免费', cls: 'free' } // 未知取值与服务端容错口径一致：按所有人可用
}
