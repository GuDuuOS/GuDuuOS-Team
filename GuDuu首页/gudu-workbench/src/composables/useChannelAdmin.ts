import { computed, reactive, ref } from 'vue'
import {
  channelMembers,
  channelSkills,
  channelKnowledge,
  channelRules,
  type ChannelInfoItem
} from '@/data/channels'
import type { Member } from '@/types/channel'

/** 频道管理弹窗的可见状态 */
const visible = ref(false)

/* ===== 隔离配置的类型 ===== */
export type Confidential = '公开' | '内部' | '机密'
export type AccessLevel = '禁用' | '只读' | '读写'

export interface DataScope { label: string; level: Confidential; access: AccessLevel }
export interface ChannelPersona { aiName: string; tone: string; prompt: string }
export interface ChannelModel { model: string; tokenBudget: number; rateLimit: number }
export interface ChannelMemory { longTerm: boolean; scope: '仅本群' | '本部门' | '全公司'; retentionDays: number; audit: boolean }

export const MODEL_OPTIONS = ['GuDuu-Pro', 'GuDuu-Lite', 'GuDuu-行业微调', 'GuDuu-Vision']

/** 成员可被本群调取的数据项 */
export interface MemberDatum { label: string; value: string; selected: boolean }
export type AdminMember = Member & { data: MemberDatum[] }

/** 一个群的完整隔离配置 */
export interface GroupConfig {
  members: AdminMember[]
  skills: ChannelInfoItem[]
  knowledge: ChannelInfoItem[]
  rules: ChannelInfoItem[]
  dataScopes: DataScope[]
  persona: ChannelPersona
  model: ChannelModel
  memory: ChannelMemory
}

/* ===== 成员数据池（带领域标签，按群所属领域决定默认可调取项）===== */
interface PoolItem { label: string; value: string; dom: string[] } // dom 含 '*' 表示所有群
const MEMBER_POOL: Record<string, PoolItem[]> = {
  'GuDuu': [
    { label: 'AI 今日协同', value: '86 次', dom: ['*'] },
    { label: '货源匹配', value: '3 单', dom: ['general'] },
    { label: '跨环节调度', value: '23 次', dom: ['general'] }
  ],
  '捕捞分身': [
    { label: '今日渔获', value: '3,000 斤', dom: ['fish', 'general'] },
    { label: '在航渔船', value: '0 艘 (避风)', dom: ['fish'] },
    { label: '出海安全', value: '218 天', dom: ['fish'] }
  ],
  '养殖分身': [
    { label: '成品存塘', value: '5,000 斤', dom: ['farm', 'general'] },
    { label: '水质达标率', value: '98%', dom: ['farm'] },
    { label: '病害预警', value: '1 处', dom: ['farm'] }
  ],
  '加工分身': [
    { label: '单日产能', value: '6,000 斤', dom: ['proc', 'general'] },
    { label: '今日排产', value: '4,000 斤', dom: ['proc'] },
    { label: '加工损耗率', value: '1.2%', dom: ['proc'] }
  ],
  '销售分身': [
    { label: '本月订单', value: '1,284 单', dom: ['sale', 'general'] },
    { label: '行情指数', value: '92 点', dom: ['sale'] },
    { label: '加急在办', value: '2 单', dom: ['sale'] }
  ],
  '仓储物流分身': [
    { label: '冷库库存', value: '2,000 斤', dom: ['wh', 'general'] },
    { label: '冷库库容', value: '82%', dom: ['wh'] },
    { label: '在途冷链车', value: '3 辆', dom: ['wh'] }
  ],
  '质检分身': [
    { label: '今日抽检', value: '3 批次', dom: ['qc', 'general'] },
    { label: '抽检合格率', value: '100%', dom: ['qc'] },
    { label: '溯源上链', value: '12,840 条', dom: ['qc'] }
  ],
  '运维预警分身': [
    { label: '监测点位', value: '328 路', dom: ['*'] },
    { label: '今日预警', value: '3 起', dom: ['general'] },
    { label: '海况等级', value: '4 级', dom: ['fish'] }
  ],
  '林经理': [
    { label: '今日订单', value: '4,000 斤', dom: ['general'] },
    { label: '待裁定事项', value: '1 项', dom: ['general'] },
    { label: '本月营收', value: '1,860 万', dom: ['fin'] },
    { label: '全链路损耗率', value: '1.2%', dom: ['general'] }
  ],
  '赵船长': [
    { label: '船队规模', value: '6 艘', dom: ['fish', 'general'] },
    { label: '今日卸货', value: '1,000 斤', dom: ['fish'] },
    { label: '停航报备', value: '1 单', dom: ['fish'] }
  ],
  '钱厂长': [
    { label: '产线开动率', value: '67%', dom: ['proc', 'general'] },
    { label: '在岗人数', value: '12 人', dom: ['proc'] },
    { label: '今日完成', value: '3,952 斤', dom: ['proc'] }
  ],
  '孙库管': [
    { label: '冷库分区', value: '6 区', dom: ['wh', 'general'] },
    { label: '今日出入库', value: '8 单', dom: ['wh'] },
    { label: '温控告警', value: '1 起', dom: ['wh'] }
  ]
}

/** 由群名判断所属领域（决定成员默认可调取哪些数据）*/
function domainOf(g: string): string {
  if (/财务|成本|经营|核算|预算|资金|利润/.test(g)) return 'fin'
  if (/捕捞|渔船|出海|渔获|海况|码头/.test(g)) return 'fish'
  if (/养殖|塘|水质|病害|苗种|网箱/.test(g)) return 'farm'
  if (/加工|车间|排产|分拣|预制|产线/.test(g)) return 'proc'
  if (/销售|订单|行情|渠道|客户|报价/.test(g)) return 'sale'
  if (/仓储|冷库|冷链|物流|配送/.test(g)) return 'wh'
  if (/质检|溯源|抽检|检测/.test(g)) return 'qc'
  return 'general'
}

function memberDataForGroup(groupName: string, name: string): MemberDatum[] {
  const dom = domainOf(groupName)
  const pool = MEMBER_POOL[name] ?? []
  const items = pool.map((d) => ({ label: d.label, value: d.value, selected: d.dom.includes('*') || d.dom.includes(dom) }))
  if (items.length && !items.some((d) => d.selected)) items[0].selected = true
  return items
}

/* ===== 其余配置的基础模板（各群独立克隆一份）===== */
const BASE_DATASCOPES: DataScope[] = [
  { label: '渔船定位 / AIS',   level: '内部', access: '只读' },
  { label: '水质传感物联网',   level: '内部', access: '只读' },
  { label: 'MES 加工执行',     level: '内部', access: '只读' },
  { label: '冷链温控平台',     level: '内部', access: '只读' },
  { label: '溯源存证平台',     level: '内部', access: '只读' },
  { label: 'ERP 订单财务',     level: '机密', access: '禁用' }
]
const BASE_PERSONA: ChannelPersona = {
  aiName: 'GuDuu',
  tone: '严谨 · 数据优先',
  prompt: '你是蓝湾渔业的岗位智能分身，基于渔船定位、水质传感、MES 加工、冷链温控、溯源平台等系统数据作答；给出操作建议须标注数据依据，紧急调货、停产、出海审批等关键动作必须经人工确认后执行。'
}
const BASE_MODEL: ChannelModel = { model: 'GuDuu-Pro', tokenBudget: 500, rateLimit: 60 }
const BASE_MEMORY: ChannelMemory = { longTerm: true, scope: '仅本群', retentionDays: 90, audit: true }

/** 为某个群生成一份独立配置（成员数据按群领域预选）*/
function seedConfig(groupName: string): GroupConfig {
  return {
    members: channelMembers.map((m) => ({ ...m, data: memberDataForGroup(groupName, m.name) })) as AdminMember[],
    skills: channelSkills.map((s) => ({ ...s })),
    knowledge: channelKnowledge.map((k) => ({ ...k })),
    rules: channelRules.map((r) => ({ ...r })),
    dataScopes: BASE_DATASCOPES.map((d) => ({ ...d })),
    persona: { ...BASE_PERSONA },
    model: { ...BASE_MODEL },
    memory: { ...BASE_MEMORY }
  }
}

/* ===== 按群名存储的配置（每个群一份，互不影响）===== */
const configs = reactive<Record<string, GroupConfig>>({ 本群: seedConfig('本群') })
/** 当前正在查看/管理的群名 */
const currentKey = ref('本群')
const current = computed(() => configs[currentKey.value] ?? configs['本群'])

function ensure(name: string) {
  if (!configs[name]) configs[name] = seedConfig(name)
}
/** 切换当前群（频道视图挂载、或打开弹窗时调用）*/
function setCurrent(name?: string) {
  const k = name?.trim()
  if (!k) return
  ensure(k)
  currentKey.value = k
}

/** 代理到当前群配置，使既有消费方（用 state.xxx）无需改动 */
const state = {
  get members() { return current.value.members },
  get skills() { return current.value.skills },
  get knowledge() { return current.value.knowledge },
  get rules() { return current.value.rules },
  get dataScopes() { return current.value.dataScopes },
  get persona() { return current.value.persona },
  get model() { return current.value.model },
  get memory() { return current.value.memory }
}

const AVATAR_COLORS = ['#7a5a3a', '#5a7a8a', '#a07050', '#7a8a5a', '#8a6a8a', '#6a8a7a']

export function useChannelAdmin() {
  return {
    visible,
    state,
    /** 当前群名（用于文案"被本群调取"）*/
    groupName: currentKey,
    setCurrent,
    open: (name?: string) => {
      setCurrent(name)
      visible.value = true
    },
    close: () => { visible.value = false },

    addMember(name: string, role: string) {
      const n = name.trim()
      if (!n) return
      current.value.members.push({
        name: n,
        role: role.trim() || '成员',
        avatar: [...n][0] ?? '?',
        color: AVATAR_COLORS[current.value.members.length % AVATAR_COLORS.length],
        online: true,
        data: []
      })
    },
    removeMember(i: number) { current.value.members.splice(i, 1) },

    addItem(kind: 'skills' | 'knowledge' | 'rules', label: string, desc: string, tag?: string) {
      const l = label.trim()
      if (!l) return
      const item: ChannelInfoItem = { label: l }
      if (desc.trim()) item.desc = desc.trim()
      if (tag && tag.trim()) item.tag = tag.trim()
      current.value[kind].push(item)
    },
    removeItem(kind: 'skills' | 'knowledge' | 'rules', i: number) { current.value[kind].splice(i, 1) },

    addScope(label: string, level: Confidential, access: AccessLevel) {
      const l = label.trim()
      if (!l) return
      current.value.dataScopes.push({ label: l, level, access })
    },
    removeScope(i: number) { current.value.dataScopes.splice(i, 1) }
  }
}
