import { reactive } from 'vue'
import type { ChannelItem, DmItem, Member, PinnedItem } from '@/types/channel'
import { tenant } from '@/config/tenant'

/** 顶部固定项：所有工作区共用 */
export const pinnedItems: PinnedItem[] = [
  { id: 'topic', label: tenant.productName, routeName: 'dashboard', icon: 'topic' },
  { id: 'draft', label: '待办事宜',     routeName: 'todo',      icon: 'draft', badge: 3 }
]

/** 部门级限制（含 AI 限制）*/
export interface DeptLimits {
  /** 成员上限 */
  memberCap: number
  /** 频道可见性默认 */
  visibility: '公开' | '受邀'
  ai: {
    /** 是否启用部门 AI */
    enabled: boolean
    model: string
    /** 月度 Token 预算（万）*/
    tokenBudget: number
    /** 速率限制（次 / 分）*/
    rateLimit: number
    /** AI 可访问的最高数据密级 */
    maxLevel: '公开' | '内部' | '机密'
    /** 上下文 / 记忆范围 */
    memoryScope: '仅本工作区' | '全平台'
    /** 允许 AI 执行控制类动作（高风险）*/
    allowControl: boolean
    /** 审计日志 */
    audit: boolean
  }
}

/** 工作区元数据（部门图标）*/
export interface WorkspaceMeta {
  id: string
  label: string
  title: string
  active?: boolean
  /** 新建部门时设定的限制；内置部门可不带 */
  limits?: DeptLimits
}

export const workspaces: WorkspaceMeta[] = reactive([
  { id: tenant.hqId, label: tenant.hqLabel, title: tenant.hqTitle, active: true }
])

/** 每个工作区的频道 + 私信 */
export interface WorkspaceData {
  name: string
  channels: ChannelItem[]
  dms: DmItem[]
}

export const workspaceDataMap: Record<string, WorkspaceData> = reactive({
  /** ===== 安其影视工作室 · 10 个创作运营场景 ===== */
  [tenant.hqId]: {
    name: tenant.name,
    channels: [
      { id: 'dcs-coord',        label: '选题-灵感库',        routeName: 'ops', routeParams: { id: 'dcs-coord' },        visibility: 'public',  unread: 5, emphasized: true },
      { id: 'emergency',        label: '舆情-评论预警',      routeName: 'ops', routeParams: { id: 'emergency' },        visibility: 'public',  warn: true },
      { id: 'grid-dispatch',    label: '发布-排期日历',      routeName: 'ops', routeParams: { id: 'grid-dispatch' },    visibility: 'public' },
      { id: 'plant-startup',    label: '拍摄-脚本分镜',      routeName: 'ops', routeParams: { id: 'plant-startup' },    visibility: 'private' },
      { id: 'wind-remote',      label: '数据-涨粉复盘',      routeName: 'ops', routeParams: { id: 'wind-remote' },      visibility: 'public',  unread: 2 },
      { id: 'shift-handover',   label: '商单-品牌合作',      routeName: 'ops', routeParams: { id: 'shift-handover' },   visibility: 'public' },
      { id: 'work-permit',      label: '合作-合同报价',      routeName: 'ops', routeParams: { id: 'work-permit' },      visibility: 'private' },
      { id: 'utility-coord',    label: '私域-社群运营',      routeName: 'ops', routeParams: { id: 'utility-coord' },    visibility: 'public' },
      { id: 'safety-briefing',  label: '选题-每周选题会',    routeName: 'ops', routeParams: { id: 'safety-briefing' },  visibility: 'public' },
      { id: 'process-handover', label: '成片-审核交付',      routeName: 'ops', routeParams: { id: 'process-handover' }, visibility: 'public' }
    ],
    dms: [
      { id: 'duu',    label: 'GuDuu OS',     routeName: 'duu',    avatar: 'G', bot: true, online: true },
      { id: 'a-safe', label: '选题 Agent', routeName: 'safety', avatar: '题', bot: true, online: true },
      { id: 'a-en',   label: '数据 Agent', routeName: 'energy', avatar: '数', bot: true, online: true },
      { id: 'a-doc',  label: '文案 Agent', routeName: 'office', avatar: '文', bot: true, online: true },
      { id: 'li',     label: '阿杰',       routeName: 'dashboard', avatar: '杰', avatarColor: '#7a5a3a' },
      { id: 'chen',   label: '小鹿',       routeName: 'dashboard', avatar: '鹿', avatarColor: '#5a7a8a' }
    ]
  },
})

/** 默认工作区（页面初始化用）*/
export const defaultWorkspaceId = tenant.hqId

/** 向后兼容：直接导出当前展示的工作区数据，按 useActiveWorkspace 取 */
export const workspaceName = workspaceDataMap[defaultWorkspaceId].name
export const channels      = workspaceDataMap[defaultWorkspaceId].channels
export const dms           = workspaceDataMap[defaultWorkspaceId].dms

export const currentUser: Member = {
  name: '安其',
  role: 'admin',
  avatar: '安',
  color: '#7a5a3a',
  online: true
}

export const channelMembers: Member[] = [
  { name: 'GuDuu OS',     role: '主控',     avatar: 'G', bot: true, online: true },
  { name: '选题 Agent', role: 'bot',     avatar: '题', bot: true, online: true },
  { name: '数据 Agent', role: 'bot',     avatar: '数', bot: true, online: true },
  { name: '文案 Agent', role: 'bot',     avatar: '文', bot: true, online: true },
  { name: '安其',      role: 'admin',    avatar: '安', color: '#7a5a3a', online: true },
  { name: '小鹿',      role: '商务运营', avatar: '鹿', color: '#5a7a8a', online: true },
  { name: '老周',      role: '摄影',     avatar: '周', color: '#a07050' },
  { name: '阿杰',      role: '视频剪辑', avatar: '杰', color: '#7a8a5a' }
]

/** 右栏「关于此频道」里的能力/资源条目 */
export interface ChannelInfoItem {
  label: string
  desc?: string
  /** 关联的斜杠命令，如 /report */
  tag?: string
}

/** 频道挂载的技能（由接入的 Agent 提供）*/
export const channelSkills: ChannelInfoItem[] = [
  { label: '爆款标题生成',     tag: '/title',  desc: '结合平台热点与历史爆款，一次给 10 个标题' },
  { label: '短视频脚本起草',   tag: '/script', desc: '选题 → 钩子 → 正文 → 分镜，一键成稿' },
  { label: '评论区智能回复',   tag: '/reply',  desc: '批量生成高赞回复，自动标记争议评论' },
  { label: '全平台数据复盘',   tag: '/report', desc: '汇总各平台播放 / 涨粉 / 转化与变现' }
]

/** 频道接入的知识库来源 */
export const channelKnowledge: ChannelInfoItem[] = [
  { label: '我的爆款素材库',   desc: '328 条 · 标题 / 脚本 / 封面' },
  { label: '对标账号拆解',     desc: '86 个账号 · 选题 / 节奏 / 数据' },
  { label: '平台规则与避雷',   desc: '各平台社区规范 · 实时更新' },
  { label: '历史数据看板',     desc: '近 12 个月 · 全平台' }
]

/** 频道生效的自动化规则 */
export const channelRules: ChannelInfoItem[] = [
  { label: '爆款苗子自动提醒', desc: '发布 2 小时播放破万即推送' },
  { label: '差评 / 争议评论预警', desc: '负面情绪超阈值通知安其' },
  { label: '发布前合规自检',   desc: '违禁词 / 版权风险拦截' },
  { label: '商单到期自动跟进', desc: '合作交付前 3 天提醒' }
]
