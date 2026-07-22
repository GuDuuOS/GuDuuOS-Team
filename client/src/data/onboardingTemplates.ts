/**
 * 首次引导 · 行业模板
 * --------------------------------------------------------------
 * 新用户在「主 AI 问答」引导里先选一个行业，按模板预填：初始频道、主 AI 人设、口径提示。
 * 纯前端数据，引导执行时把这些真建到 Matrix（建 Space + 频道 + 写 AI 人设）。
 * 加新行业就往这里加一条（key 唯一）。
 */
export interface OnboardingTemplate {
  key: string
  label: string          // 行业名（选项展示）
  icon: string
  desc: string           // 一句话说明
  channels: string[]     // 预填的初始频道名（用户可增删）
  aiName: string         // 主 AI 默认名字
  aiPersona: string      // 主 AI 默认人设（一句话，写进 system_prompt 基底）
  /** 工作区名输入框的占位示例 */
  workspacePlaceholder: string
}

export const ONBOARDING_TEMPLATES: OnboardingTemplate[] = [
  {
    key: 'film',
    label: '影视 / 内容工作室',
    icon: '🎬',
    desc: '剧集/短视频制作、虚拟明星、粉丝运营',
    channels: ['制作中心', '分镜与脚本', '选题策划', '商单与合作'],
    aiName: '中枢 AI',
    aiPersona: '你是这家影视内容工作室的制作中枢助手，擅长拆解制作任务、跟进剧集进度、协助粉丝运营。',
    workspacePlaceholder: '如：安其影视工作室',
  },
  {
    key: 'ecommerce',
    label: '电商 / 品牌运营',
    icon: '🛍️',
    desc: '选品、上架、客服、投放与复盘',
    channels: ['选品与上架', '订单管理', '投放与增长', '数据复盘'],
    aiName: '运营助手',
    aiPersona: '你是这家电商品牌的运营助手，擅长选品分析、客服话术、投放复盘与增长建议。',
    workspacePlaceholder: '如：某某品牌旗舰店',
  },
  {
    key: 'creator',
    label: '自媒体 / 博主',
    icon: '📱',
    desc: '选题、脚本、多平台分发、粉丝互动',
    channels: ['选题库', '脚本与拍摄', '多平台分发', '数据复盘'],
    aiName: '创作搭子',
    aiPersona: '你是这位博主的创作搭子，擅长找选题、写脚本、规划多平台分发与粉丝互动。',
    workspacePlaceholder: '如：小王的频道',
  },
  {
    key: 'education',
    label: '教育 / 知识付费',
    icon: '📚',
    desc: '课程研发、招生、学员服务、社群',
    channels: ['课程研发', '招生与转化', '教务运营', '数据复盘'],
    aiName: '教务助手',
    aiPersona: '你是这家教育机构的教务助手，擅长课程设计、招生话术、学员答疑与社群运营。',
    workspacePlaceholder: '如：某某学堂',
  },
  {
    key: 'general',
    label: '通用团队',
    icon: '🧩',
    desc: '不限行业，先建几个通用频道，之后再调',
    channels: ['综合讨论', '项目协作', '资料共享'],
    aiName: '中枢 AI',
    aiPersona: '你是这个团队的中枢 AI 助手，帮助协调任务、整理信息、推进项目。',
    workspacePlaceholder: '如：我的工作区',
  },
]

export function templateOf(key: string): OnboardingTemplate {
  return ONBOARDING_TEMPLATES.find((t) => t.key === key) || ONBOARDING_TEMPLATES[ONBOARDING_TEMPLATES.length - 1]
}
