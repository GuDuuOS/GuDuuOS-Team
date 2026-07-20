/**
 * 租户/品牌配置层
 * --------------------------------------------------------------
 * 这里集中维护所有"主理人/品牌相关"的显示字符串，让 CosMac 工作台从
 * "某个创作者的专属 Demo" 抽象为可换皮的「个人创业者 AI 工作台模板」。
 *
 * 使用约定：
 *   - 任何 UI 文案、AI prompt、报表标题、对话欢迎语中出现的
 *     "主理人名 / 工作室名 / 产品名" 一律从这里读取。
 *   - 不可在源码里写死主理人标识；JSON / HTML title 等无法 import 的
 *     场合，使用与本文件保持一致的占位值，并在 README 里注明。
 *   - 换一个创作者接入时，理论上**只改本文件**即可完成换皮。
 */
export const tenant = {
  /** 工作室/品牌显示名 */
  name: '安其影视工作室',
  /** 主理人短名 */
  shortName: '安其',
  /** 产品名 */
  productName: 'AI 制作中台',
  /** 主工作区 label / title */
  hqLabel: '安其',
  hqTitle: '安其影视工作室',
  /** 主工作区 ID（默认 workspace id）*/
  hqId: 'hq',
  /** 顶栏 "CosMac OS × XXX" 后缀（保留品牌联名样式）*/
  topbarSuffix: '安其影视工作室',
  /** AI 角色称呼里"你是 XX 的助手"中的 XX */
  aiOwner: '安其影视工作室'
} as const

/** 衍生：板块 brand 字段统一模板，如 "内容运营 · 创作工作台" */
export function brandOf(dept: string): string {
  return `${dept} · ${tenant.productName}`
}

/** 衍生：工作室 brand 字段，如 "安其影视工作室 · 创作工作台" */
export const tenantBrand = `${tenant.name} · ${tenant.productName}`
