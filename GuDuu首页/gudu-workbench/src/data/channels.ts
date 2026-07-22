import { reactive } from 'vue'
import type { ChannelItem, DmItem, Member, PinnedItem } from '@/types/channel'

/** 顶部固定项：所有工作区共用 */
export const pinnedItems: PinnedItem[] = [
  { id: 'topic', label: '全链路驾驶舱', routeName: 'dashboard', icon: 'topic' },
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
    memoryScope: '仅本部门' | '全公司'
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
  { id: 'hq',   label: '总控', title: '蓝湾渔业（总控中心）', active: true },
  { id: 'fish', label: '捕捞', title: '捕捞船队' },
  { id: 'farm', label: '养殖', title: '养殖基地' },
  { id: 'proc', label: '加工', title: '加工中心' },
  { id: 'sale', label: '销售', title: '销售公司' }
])

/** 每个工作区的频道 + 私信 */
export interface WorkspaceData {
  name: string
  channels: ChannelItem[]
  dms: DmItem[]
}

export const workspaceDataMap: Record<string, WorkspaceData> = reactive({
  /** ===== 总控中心 · 全链路协同 ===== */
  hq: {
    name: '蓝湾渔业',
    channels: [
      { id: 'order-flow', label: '总控-订单全链路',  routeName: 'ops', routeParams: { id: 'order-flow' }, visibility: 'public',  unread: 3, emphasized: true },
      { id: 'risk-alert', label: '预警-风险联动',    routeName: 'ops', routeParams: { id: 'risk-alert' }, visibility: 'public',  unread: 2 },
      { id: 'conflict',   label: '协商-货源冲突',    routeName: 'ops', routeParams: { id: 'conflict' },   visibility: 'public',  unread: 1 },
      { id: 'approvals',  label: '审批-异常裁定',    routeName: 'ops', routeParams: { id: 'approvals' },  visibility: 'private' },
      { id: 'trace-sync', label: '数据-溯源同步',    routeName: 'ops', routeParams: { id: 'trace-sync' }, visibility: 'public' }
    ],
    dms: [
      { id: 'duu',     label: 'GuDuu 总控',   routeName: 'duu',       avatar: 'G', bot: true, online: true },
      { id: 'a-alert', label: '运维预警分身', routeName: 'safety',    avatar: '警', bot: true, online: true },
      { id: 'a-sale',  label: '销售分身',     routeName: 'energy',    avatar: '销', bot: true, online: true },
      { id: 'a-qc',    label: '质检分身',     routeName: 'office',    avatar: '质', bot: true, online: true },
      { id: 'lin',     label: '林经理',       routeName: 'dashboard', avatar: '林', avatarColor: '#7a5a3a' },
      { id: 'zhao',    label: '赵船长',       routeName: 'dashboard', avatar: '赵', avatarColor: '#5a7a8a' }
    ]
  },

  /** ===== 捕捞船队 ===== */
  fish: {
    name: '捕捞船队',
    channels: [
      { id: 'fish-dispatch', label: '捕捞-渔船调度', routeName: 'ops', routeParams: { id: 'fish-dispatch' }, visibility: 'public', unread: 3, emphasized: true },
      { id: 'fish-catch',    label: '捕捞-渔获上报', routeName: 'ops', routeParams: { id: 'fish-catch' },    visibility: 'public' },
      { id: 'fish-safety',   label: '捕捞-出海安全', routeName: 'ops', routeParams: { id: 'fish-safety' },   visibility: 'public' },
      { id: 'fish-maint',    label: '捕捞-设备维护', routeName: 'ops', routeParams: { id: 'fish-maint' },    visibility: 'private' }
    ],
    dms: [
      { id: 'fish-agent', label: '捕捞分身', routeName: 'duu', avatar: '捕', bot: true, online: true },
      { id: 'zhao-cap',   label: '赵船长',   routeName: 'duu', avatar: '赵', avatarColor: '#5a7a8a' },
      { id: 'wu-mate',    label: '吴大副',   routeName: 'duu', avatar: '吴', avatarColor: '#7a8a5a' }
    ]
  },

  /** ===== 养殖基地 ===== */
  farm: {
    name: '养殖基地',
    channels: [
      { id: 'farm-pond',    label: '养殖-塘口日常', routeName: 'ops', routeParams: { id: 'farm-pond' },    visibility: 'public', unread: 2, emphasized: true },
      { id: 'farm-water',   label: '养殖-水质监测', routeName: 'ops', routeParams: { id: 'farm-water' },   visibility: 'public' },
      { id: 'farm-disease', label: '养殖-病害防治', routeName: 'ops', routeParams: { id: 'farm-disease' }, visibility: 'public' },
      { id: 'farm-harvest', label: '养殖-出塘报备', routeName: 'ops', routeParams: { id: 'farm-harvest' }, visibility: 'private' }
    ],
    dms: [
      { id: 'farm-agent', label: '养殖分身', routeName: 'duu', avatar: '养', bot: true, online: true },
      { id: 'huang-farm', label: '黄塘长',   routeName: 'duu', avatar: '黄', avatarColor: '#7a8a5a' },
      { id: 'xu-tech',    label: '徐技术员', routeName: 'duu', avatar: '徐', avatarColor: '#8a6a8a' }
    ]
  },

  /** ===== 加工中心 ===== */
  proc: {
    name: '加工中心',
    channels: [
      { id: 'proc-plan',  label: '加工-车间排产', routeName: 'ops', routeParams: { id: 'proc-plan' },  visibility: 'public', unread: 2, emphasized: true },
      { id: 'proc-line',  label: '加工-生产进度', routeName: 'ops', routeParams: { id: 'proc-line' },  visibility: 'public' },
      { id: 'proc-qc',    label: '加工-质量管控', routeName: 'ops', routeParams: { id: 'proc-qc' },    visibility: 'public' },
      { id: 'proc-equip', label: '加工-设备保养', routeName: 'ops', routeParams: { id: 'proc-equip' }, visibility: 'private' }
    ],
    dms: [
      { id: 'proc-agent', label: '加工分身',     routeName: 'duu', avatar: '加', bot: true, online: true },
      { id: 'qc-agent',   label: '质检分身',     routeName: 'duu', avatar: '质', bot: true, online: true },
      { id: 'qian-fac',   label: '钱厂长',       routeName: 'duu', avatar: '钱', avatarColor: '#a07050' }
    ]
  },

  /** ===== 销售公司 ===== */
  sale: {
    name: '销售公司',
    channels: [
      { id: 'sale-orders',  label: '销售-订单接龙', routeName: 'ops', routeParams: { id: 'sale-orders' },  visibility: 'public', unread: 4, emphasized: true },
      { id: 'sale-market',  label: '销售-行情分析', routeName: 'ops', routeParams: { id: 'sale-market' },  visibility: 'public' },
      { id: 'sale-channel', label: '销售-渠道对接', routeName: 'ops', routeParams: { id: 'sale-channel' }, visibility: 'public' },
      { id: 'sale-after',   label: '销售-售后客服', routeName: 'ops', routeParams: { id: 'sale-after' },   visibility: 'private' }
    ],
    dms: [
      { id: 'sale-agent', label: '销售分身',     routeName: 'duu', avatar: '销', bot: true, online: true },
      { id: 'wl-agent',   label: '仓储物流分身', routeName: 'duu', avatar: '仓', bot: true, online: true },
      { id: 'zhou-sale',  label: '周专员',       routeName: 'duu', avatar: '周', avatarColor: '#8a6a8a' }
    ]
  }
})

/** 默认工作区（页面初始化用）*/
export const defaultWorkspaceId = 'hq'

/** 向后兼容：直接导出当前展示的工作区数据，按 useActiveWorkspace 取 */
export const workspaceName = workspaceDataMap[defaultWorkspaceId].name
export const channels      = workspaceDataMap[defaultWorkspaceId].channels
export const dms           = workspaceDataMap[defaultWorkspaceId].dms

export const currentUser: Member = {
  name: '林经理',
  role: 'admin',
  avatar: '林',
  color: '#7a5a3a',
  online: true
}

export const channelMembers: Member[] = [
  { name: 'GuDuu',         role: '总控',     avatar: 'G', bot: true, online: true },
  { name: '捕捞分身',      role: 'bot',      avatar: '捕', bot: true, online: true },
  { name: '养殖分身',      role: 'bot',      avatar: '养', bot: true, online: true },
  { name: '加工分身',      role: 'bot',      avatar: '加', bot: true, online: true },
  { name: '销售分身',      role: 'bot',      avatar: '销', bot: true, online: true },
  { name: '仓储物流分身',  role: 'bot',      avatar: '仓', bot: true, online: true },
  { name: '质检分身',      role: 'bot',      avatar: '质', bot: true, online: true },
  { name: '运维预警分身',  role: 'bot',      avatar: '警', bot: true, online: true },
  { name: '林经理',        role: 'admin',    avatar: '林', color: '#7a5a3a', online: true },
  { name: '赵船长',        role: '捕捞队长', avatar: '赵', color: '#5a7a8a', online: true },
  { name: '钱厂长',        role: '加工厂长', avatar: '钱', color: '#a07050' },
  { name: '孙库管',        role: '仓储主管', avatar: '孙', color: '#7a8a5a' }
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
  { label: '货源智能调度', tag: '/dispatch', desc: '按「库存→养殖→捕捞」优先级自动匹配货源' },
  { label: '批次溯源查询', tag: '/trace',    desc: '一键回溯海域 / 塘口 / 加工 / 冷链全链路' },
  { label: '行情分析建议', tag: '/market',   desc: '抓取市场价格波动，给出产销策略' },
  { label: '质检报告生成', tag: '/qc',       desc: '汇总抽检数据自动出具质检报告' }
]

/** 频道接入的知识库来源 */
export const channelKnowledge: ChannelInfoItem[] = [
  { label: '渔业作业规范',     desc: '出海 / 养殖 / 加工 SOP · 860 篇' },
  { label: '水产品质量标准',   desc: '农残 / 鲜度 / 冷链 · 实时同步' },
  { label: '海域与渔船档案',   desc: '6 艘渔船 · 12 处塘口 / 网箱' },
  { label: '历史产销行情库',   desc: '近 5 年价格与产量数据' }
]

/** 频道生效的自动化规则 */
export const channelRules: ChannelInfoItem[] = [
  { label: '渔获入厂必检',       desc: '未出质检报告不得流入加工' },
  { label: '出海计划人工双签',   desc: '海况预警期出海须负责人确认' },
  { label: '冷链温度越限告警',   desc: '厢温 / 库温超阈值秒级推送' },
  { label: '紧急调货负责人终审', desc: '分身协商方案须人工批准执行' }
]
