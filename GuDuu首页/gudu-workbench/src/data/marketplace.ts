export type MarketCat = 'agent' | 'skill' | 'prompt' | 'workflow' | 'knowledge' | 'mcp'

export interface MarketItem {
  id: string
  name: string
  cat: MarketCat
  author: string
  desc: string
  installs: string
  /** 价格（元）；0 表示免费 */
  price: number
  tag?: string
  installed?: boolean
}

/** 分类元信息：标签 + 主题色 */
export const CAT_META: Record<MarketCat, { label: string; color: string }> = {
  agent:     { label: 'AI Agent',   color: '#c96442' },
  skill:     { label: 'Skill',      color: '#6b8e4e' },
  prompt:    { label: 'Prompt',     color: '#4a7a8c' },
  workflow:  { label: '工作流',     color: '#b58932' },
  knowledge: { label: '知识库',     color: '#8a6a8a' },
  mcp:       { label: 'MCP 连接器', color: '#5a7a8a' }
}

export const marketItems: MarketItem[] = [
  /* AI Agent */
  { id: 'a1', name: '行情预测分身', cat: 'agent', author: 'GuDuu 官方', desc: '抓取批发市场价格，预测走势并给出产销策略', installs: '3.2k', price: 199, installed: true },
  { id: 'a2', name: '病害识别分身', cat: 'agent', author: 'GuDuu 官方', desc: '塘口照片 + 水质数据识别病害，给出防治方案', installs: '2.1k', price: 99 },
  { id: 'a3', name: '合规审查分身', cat: 'agent', author: '销售公司', desc: '出口报关 / 食安法规风险研判，红线预警', installs: '1.4k', price: 0 },
  { id: 'a4', name: '排产优化分身', cat: 'agent', author: '加工中心', desc: '产线 / 人员 / 订单优先级联动排产建议', installs: '980', price: 99 },
  { id: 'a5', name: '渔获估产分身', cat: 'agent', author: '捕捞船队', desc: '依据海况与历史航次预测渔获量', installs: '760', price: 49 },

  /* Skill */
  { id: 's1', name: '产销日报汇总', cat: 'skill', author: 'GuDuu 官方', desc: '汇总捕捞 / 出塘 / 加工 / 销售数据自动成日报', installs: '1.8k', price: 0, tag: '/report', installed: true },
  { id: 's2', name: '批次溯源查询', cat: 'skill', author: 'GuDuu 官方', desc: '扫码回溯海域 / 塘口 / 加工 / 冷链全链路', installs: '1.1k', price: 19.9, tag: '/trace' },
  { id: 's3', name: '货源智能调度', cat: 'skill', author: '总控中心', desc: '库存 → 养殖 → 捕捞优先级自动匹配', installs: '920', price: 19.9, tag: '/dispatch' },
  { id: 's4', name: '知识库问答检索', cat: 'skill', author: 'GuDuu 官方', desc: '自然语言检索作业规范与质量标准', installs: '2.4k', price: 0, tag: '/kb', installed: true },
  { id: 's5', name: '行情趋势解读', cat: 'skill', author: '销售公司', desc: '抓取并解读水产批发价趋势', installs: '640', price: 9.9, tag: '/market' },

  /* Prompt */
  { id: 'p1', name: '产销日报模板', cat: 'prompt', author: '销售公司', desc: '标准化产销日报结构与口径', installs: '1.5k', price: 0 },
  { id: 'p2', name: '损耗分析五问 (5 Why)', cat: 'prompt', author: '加工中心', desc: '逐层追问定位损耗根因', installs: '870', price: 0 },
  { id: 'p3', name: '病害诊断引导', cat: 'prompt', author: '养殖基地', desc: '症状问答式引导定位病害', installs: '540', price: 9.9 },
  { id: 'p4', name: '订单复盘报告框架', cat: 'prompt', author: '总控中心', desc: '货源 / 时效 / 损耗 / 成本复盘提纲', installs: '430', price: 9.9 },

  /* 工作流 */
  { id: 'w1', name: '海况预警分级联动', cat: 'workflow', author: 'GuDuu 官方', desc: '预警 → 停航 → 调整接单 → 养殖补供', installs: '760', price: 49 },
  { id: 'w2', name: '渔获入厂必检流转', cat: 'workflow', author: '质检实验室', desc: '到货 → 抽检 → 报告 → 放行自动流转', installs: '520', price: 29 },
  { id: 'w3', name: '加急订单全链路', cat: 'workflow', author: '总控中心', desc: '接单 → 货源匹配 → 加工 → 冷链发货', installs: '410', price: 49 },

  /* 知识库 */
  { id: 'k1', name: '渔业作业规范库', cat: 'knowledge', author: 'GuDuu 官方', desc: '860 篇 · 出海 / 养殖 / 加工 SOP', installs: '2.0k', price: 0, installed: true },
  { id: 'k2', name: '水产品标准库', cat: 'knowledge', author: '质检实验室', desc: 'GB / 行业标准 / 模板 · 实时同步', installs: '1.3k', price: 0 },
  { id: 'k3', name: '渠道客户档案', cat: 'knowledge', author: '销售公司', desc: '商超 / 餐饮 / 电商 8,600 条客户数据', installs: '990', price: 0 },

  /* MCP 连接器 */
  { id: 'm1', name: '渔船 AIS 连接器', cat: 'mcp', author: 'GuDuu 官方', desc: '接入渔船定位与航迹数据', installs: '1.1k', price: 0, installed: true },
  { id: 'm2', name: '水质物联网连接器', cat: 'mcp', author: 'GuDuu 官方', desc: '溶氧 / pH / 水温 36 点位实时数据', installs: '880', price: 0 },
  { id: 'm3', name: '冷链温控连接器', cat: 'mcp', author: 'GuDuu 官方', desc: '冷库 / 冷链车厢温实时监控', installs: '670', price: 0 },
  { id: 'm4', name: '电商订单 API', cat: 'mcp', author: '第三方', desc: '电商平台订单与物流状态同步', installs: '350', price: 19.9 }
]
