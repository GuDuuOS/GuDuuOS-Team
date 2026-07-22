import { computed, nextTick, reactive, ref, watch } from 'vue'
import {
  channelMembers,
  channelSkills,
  channelKnowledge,
  channelRules,
  type ChannelInfoItem
} from '@/data/channels'
import { tenant } from '@/config/tenant'
import type { Member } from '@/types/channel'
// 真实成员：频道管理「人员」标签接 Matrix 真后端（有 roomId 时用真数据，无则回退 demo mock）
import {
  listChannelMembers,
  inviteToRoom,
  kickFromRoom,
  normalizeUserId,
  getChannelConfig,
  setChannelConfig,
  claimChannelAdmin,
  kbRoomList,
  type ChannelMember
} from '@/matrix/client'

/** 频道管理弹窗的可见状态 */
const visible = ref(false)

/* ===== 隔离配置的类型 ===== */
export type Confidential = '公开' | '内部' | '机密'
export type AccessLevel = '禁用' | '只读' | '读写'

export interface DataScope { label: string; level: Confidential; access: AccessLevel }
export interface ChannelPersona { aiName: string; tone: string; prompt: string; agentSlug?: string }
export interface ChannelModel { model: string; tokenBudget: number; rateLimit: number }
export interface ChannelMemory { longTerm: boolean; scope: '仅本群' | '本工作室' | '全平台'; retentionDays: number; audit: boolean }

export const MODEL_OPTIONS = ['GuDuu OS-Pro', 'GuDuu OS-Lite', 'GuDuu OS-文案微调', 'GuDuu OS-Vision(封面识别)']

/** 成员可被本群调取的数据项 */
export interface MemberDatum { label: string; value: string; selected: boolean }
export type AdminMember = Member & { data: MemberDatum[] }

/** 一个群的完整隔离配置 */
export interface GroupConfig {
  members: AdminMember[]
  skills: ChannelInfoItem[]
  knowledge: ChannelInfoItem[]
  rules: ChannelInfoItem[]
  /** 频道规则文档(Markdown,负责人需求):像 CLAUDE.md 那样的整篇工作规范,每轮全文注入本频道 AI。 */
  ruleDoc: string
  dataScopes: DataScope[]
  persona: ChannelPersona
  model: ChannelModel
  memory: ChannelMemory
}

/* ===== 成员数据池（带领域标签，按群所属领域决定默认可调取项）===== */
interface PoolItem { label: string; value: string; dom: string[] } // dom 含 '*' 表示所有群
const MEMBER_POOL: Record<string, PoolItem[]> = {
  'GuDuu OS': [
    { label: 'AI 今日处理', value: '1,056 项', dom: ['*'] },
    { label: '自动起草', value: '38 篇', dom: ['*'] },
    { label: '节省工时', value: '6 小时', dom: ['*'] }
  ],
  '选题 Agent': [
    { label: '今日入库选题', value: '8 条', dom: ['*'] },
    { label: '热点命中', value: '3 条', dom: ['*'] },
    { label: '对标账号', value: '86 个', dom: ['*'] }
  ],
  '数据 Agent': [
    { label: '今日总播放', value: '8.6w', dom: ['*'] },
    { label: '本月涨粉', value: '+12,480', dom: ['*'] },
    { label: '平均完播率', value: '31%', dom: ['*'] }
  ],
  '文案 Agent': [
    { label: '生成标题', value: '42 个', dom: ['*'] },
    { label: '脚本初稿', value: '6 篇', dom: ['*'] },
    { label: '合规自检', value: '通过', dom: ['*'] }
  ],
  '安其': [
    { label: '全平台粉丝', value: '98.3w', dom: ['*'] },
    { label: '本月商单', value: '2 单', dom: ['*'] },
    { label: '本月收入', value: '¥ 4.8w', dom: ['*'] },
    { label: '待发布', value: '4 条', dom: ['*'] }
  ],
  '小鹿': [
    { label: '商单线索', value: '5 条', dom: ['*'] },
    { label: '在谈合作', value: '3 个', dom: ['*'] },
    { label: '私域社群', value: '1,480 人', dom: ['*'] }
  ],
  '老周': [
    { label: '本周拍摄', value: '3 条', dom: ['*'] },
    { label: '素材待剪', value: '5 条', dom: ['*'] }
  ],
  '阿杰': [
    { label: '本周交付', value: '4 条', dom: ['*'] },
    { label: '剪辑队列', value: '2 条', dom: ['*'] },
    { label: '平均工期', value: '1.5 天', dom: ['*'] }
  ]
}

/** 由频道名判断所属场景（决定成员默认可调取哪些数据）*/
function domainOf(g: string): string {
  if (/数据|涨粉|复盘|播放|增长/.test(g)) return 'data'
  if (/选题|灵感|热点|对标/.test(g)) return 'topic'
  if (/商单|合作|合同|报价|私域|社群|品牌/.test(g)) return 'biz'
  if (/脚本|文案|分镜|成片|标题|交付/.test(g)) return 'content'
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
  { label: '抖音创作者后台', level: '内部', access: '只读' },
  { label: '小红书蒲公英',   level: '内部', access: '只读' },
  { label: '视频号助手',     level: '内部', access: '只读' },
  { label: '公众号后台',     level: '内部', access: '只读' },
  { label: '商单合同库',     level: '机密', access: '禁用' },
  { label: '私域用户数据',   level: '机密', access: '禁用' }
]
const BASE_PERSONA: ChannelPersona = {
  aiName: 'GuDuu OS',
  tone: '懂内容 · 数据优先',
  prompt: `你是${tenant.aiOwner}的${tenant.productName}助手，基于接入的各平台数据与创作素材作答；给出建议须标注数据依据，发布、商单报价等对外动作必须经${tenant.shortName}确认后执行。`,
  agentSlug: '', // 本群绑定的全局智能体 slug（空 = 不绑定，用上面的自定义人设）
}
const BASE_MODEL: ChannelModel = { model: 'GuDuu OS-Pro', tokenBudget: 500, rateLimit: 60 }
const BASE_MEMORY: ChannelMemory = { longTerm: true, scope: '仅本群', retentionDays: 90, audit: true }

/** 为某个群生成一份独立配置（成员数据按群领域预选）*/
function seedConfig(groupName: string): GroupConfig {
  return {
    members: channelMembers.map((m) => ({ ...m, data: memberDataForGroup(groupName, m.name) })) as AdminMember[],
    skills: channelSkills.map((s) => ({ ...s })),
    knowledge: channelKnowledge.map((k) => ({ ...k })),
    rules: channelRules.map((r) => ({ ...r })),
    ruleDoc: '',
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

/* ===== 真实成员（「人员」标签用 Matrix 真后端）===== */
// 当前频道的真实 room id；为空 = demo 场景（无真后端），此时「人员」标签回退到 mock。
const currentRoomId = ref('')
// 当前频道真实成员快照（打开弹窗 / 邀请 / 移除后刷新）
const liveMembers = ref<ChannelMember[]>([])
/** 有真实 room id 即走真数据 */
const isLive = computed(() => !!currentRoomId.value)
/** 重新从 Matrix 读当前频道成员 */
function refreshLiveMembers() {
  liveMembers.value = currentRoomId.value ? listChannelMembers(currentRoomId.value) : []
}

/* ===== 频道知识库真实文档（模块级共享：频道管理弹窗与右侧「关于此频道」同一份数据,
 * 弹窗里上传/删除后 loadRoomKbDocs 刷新,右侧面板即时同步——负责人报的"维护后右侧未同步"）===== */
const roomKbDocs = ref<{ id: number; title: string; source: string }[]>([])
async function loadRoomKbDocs() {
  if (!currentRoomId.value) { roomKbDocs.value = []; return }
  try { roomKbDocs.value = await kbRoomList(currentRoomId.value) } catch { roomKbDocs.value = [] }
}
// 切频道就拉一次:右侧面板不经过弹窗也要能看到已入库文档
watch(currentRoomId, () => { loadRoomKbDocs() })

/* ===== 配置持久化（真实频道：存进 cosmac.channel_config state event）=====
 * 加载时把房间里已存的配置 merge 进当前 reactive config；
 * suppressPersist 在加载期间为 true，避免"加载即触发回写"的回声。
 * saveState 给 UI 显示：保存中 / 已保存 / 出错（一般是无权限）。
 */
let suppressPersist = false
const saveState = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')

/** 从房间 state event 读配置，merge 进内存 config（仅接已落地的标签页：persona）*/
function loadConfigFromRoom(name: string, roomId: string) {
  const saved = getChannelConfig(roomId)
  const cfg = configs[name]
  suppressPersist = true
  // 单值配置：**先重置为中性基线再套已存的**——增量 Object.assign 会把上一次加载的残留键
  // (如别的配置里的 agentSlug)留在内存里、随下次编辑一起写进本房 state event(审查 bug#4)。
  cfg.persona = { ...BASE_PERSONA, ...(saved.persona || {}) } as any
  cfg.model = { ...BASE_MODEL, ...(saved.model || {}) } as any
  cfg.memory = { ...BASE_MEMORY, ...(saved.memory || {}) } as any
  // 列表配置：真实频道一律以"已存的为准、没存就空"——清掉 seedConfig 里的 demo mock，内容由用户真填
  cfg.skills = Array.isArray(saved.skills) ? saved.skills : []
  cfg.knowledge = Array.isArray(saved.knowledge) ? saved.knowledge : []
  cfg.rules = Array.isArray(saved.rules) ? saved.rules : []
  cfg.ruleDoc = typeof saved.ruleDoc === 'string' ? saved.ruleDoc : ''
  cfg.dataScopes = Array.isArray(saved.dataScopes) ? saved.dataScopes : []
  nextTick(() => { suppressPersist = false })
}

function ensure(key: string, displayName?: string) {
  if (!configs[key]) configs[key] = seedConfig(displayName || key)
}
/** 切换当前群（频道视图挂载、或打开弹窗时调用）。roomId 可选：传了就启用真实成员+配置持久化。
 *  ⚠️ 真实频道的内存 key 用 **roomId**（不用频道名）——两个工作区的同名频道（如都叫「综合」）
 *  若按名字共享一份配置，A 的人设会被静默带进 B 并写进 B 的 state event（审查 bug#4）。
 *  demo 场景（无 roomId）仍按名字，保留 mock 行为。 */
function setCurrent(name?: string, roomId?: string) {
  const display = name?.trim()
  const k = (roomId || display || '').trim()
  if (!k) return
  ensure(k, display)
  currentKey.value = k
  currentRoomId.value = roomId || ''
  saveState.value = 'idle'
  if (roomId) loadConfigFromRoom(k, roomId)
  refreshLiveMembers()
}

/** 防抖把 patch 写回当前频道的 state event。
 *  ⚠️ 700ms 窗口内的多次编辑**累积合并**——原实现只保留最后一个 patch,连改「人设+模型」时
 *  先改的那份被静默丢弃、UI 还显示"已保存"(审查 bug#3)。写入用 inflight 链**串行化**,
 *  避免两个并发的「读本地-合并-写回」互相覆盖。 */
let saveTimer: ReturnType<typeof setTimeout> | null = null
let pendingPatch: Record<string, any> = {}   // 防抖窗口内累积的所有编辑
let pendingRid = ''                           // pendingPatch 属于哪个房间
let inflight: Promise<void> = Promise.resolve()  // 写入串行链

async function writePatch(rid: string, batch: Record<string, any>): Promise<void> {
  try {
    await setChannelConfig(rid, batch)
    saveState.value = 'saved'
  } catch {
    // 保存被拒(多半 power 不够)。若本人是平台管理员,后端用 make_room_admin 给我在本频道授权,
    // 然后重试一次;非管理员 claim 返回 false,退回错误提示(bug14)。
    let ok = false
    try {
      if (await claimChannelAdmin(rid)) {
        await setChannelConfig(rid, batch)
        ok = true
      }
    } catch { /* 重试仍失败 */ }
    saveState.value = ok ? 'saved' : 'error'
    // 【回滚·负责人实报】保存失败时本地乐观更新必须撤销——非管理员点「添加来源」,
    // 提示"保存失败没权限"但列表里新条目还挂着,看起来"实际写入成功"了(假象,
    // state 里根本没有)。从房间 state 重读一遍,把本地假象冲掉、恢复真实配置。
    if (!ok && rid === currentRoomId.value) {
      loadConfigFromRoom(currentKey.value, rid)
    }
  }
}

function persist(patch: Record<string, any>) {
  const rid = currentRoomId.value
  if (!rid) return
  // 700ms 内切换了房间：把上一个房间攒的 patch 立刻冲出去,别混进新房间的批里
  if (pendingRid && pendingRid !== rid && Object.keys(pendingPatch).length) {
    const oldRid = pendingRid
    const oldBatch = pendingPatch
    inflight = inflight.then(() => writePatch(oldRid, oldBatch))
    pendingPatch = {}
  }
  pendingRid = rid
  pendingPatch = { ...pendingPatch, ...patch }
  if (saveTimer) clearTimeout(saveTimer)
  saveState.value = 'saving'
  saveTimer = setTimeout(() => {
    const batch = pendingPatch
    pendingPatch = {}
    inflight = inflight.then(() => writePatch(rid, batch))
  }, 700)
}

// 人设 / 模型 / 记忆 变更 → 自动持久化（深度监听；加载期 suppress；demo 无 roomId 不写）
watch(
  () => current.value.persona,
  (p) => {
    if (suppressPersist || !currentRoomId.value) return
    persist({ persona: { ...p } })
  },
  { deep: true },
)
watch(
  () => current.value.model,
  (m) => {
    if (suppressPersist || !currentRoomId.value) return
    persist({ model: { ...m } })
  },
  { deep: true },
)
watch(
  () => current.value.memory,
  (mem) => {
    if (suppressPersist || !currentRoomId.value) return
    persist({ memory: { ...mem } })
  },
  { deep: true },
)
// 列表型配置（技能/知识库/规则/数据权限）：增删改 → 防抖整列表写回
watch(
  () => current.value.skills,
  (v) => { if (!suppressPersist && currentRoomId.value) persist({ skills: v.map((x) => ({ ...x })) }) },
  { deep: true },
)
watch(
  () => current.value.knowledge,
  (v) => { if (!suppressPersist && currentRoomId.value) persist({ knowledge: v.map((x) => ({ ...x })) }) },
  { deep: true },
)
watch(
  () => current.value.rules,
  (v) => { if (!suppressPersist && currentRoomId.value) persist({ rules: v.map((x) => ({ ...x })) }) },
  { deep: true },
)
watch(
  () => current.value.ruleDoc,
  (v) => { if (!suppressPersist && currentRoomId.value) persist({ ruleDoc: v }) },
)
watch(
  () => current.value.dataScopes,
  (v) => { if (!suppressPersist && currentRoomId.value) persist({ dataScopes: v.map((x) => ({ ...x })) }) },
  { deep: true },
)

/** 代理到当前群配置，使既有消费方（用 state.xxx）无需改动 */
const state = {
  get members() { return current.value.members },
  get skills() { return current.value.skills },
  get knowledge() { return current.value.knowledge },
  get rules() { return current.value.rules },
  // v-model 直接绑编辑区,要有 setter(其余列表型都是引用可变,单值字符串必须显式 set)
  get ruleDoc() { return current.value.ruleDoc },
  set ruleDoc(v: string) { current.value.ruleDoc = v },
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
    open: (name?: string, roomId?: string) => {
      setCurrent(name, roomId)
      visible.value = true
    },
    close: () => { visible.value = false },

    /* ===== 真实成员 / 配置持久化 API ===== */
    roomId: currentRoomId,  // 当前频道 room_id（频道知识库上传等真后端操作用）
    isLive,            // true = 当前频道有真后端，「人员」标签走真实成员、配置写进房间
    saveState,         // 配置保存状态：idle/saving/saved/error（UI 提示用）
    liveMembers,       // 真实成员快照
    refreshLiveMembers,
    roomKbDocs,        // 频道知识库真实文档(弹窗与右侧面板共享)
    loadRoomKbDocs,
    /** 真邀请已有用户进当前频道 */
    async inviteLiveMember(userIdRaw: string) {
      if (!currentRoomId.value) return
      const uid = normalizeUserId(userIdRaw.trim())
      if (!uid) return
      await inviteToRoom(currentRoomId.value, uid)
      // 邀请后 sync 需一点时间才反映到本地，稍候刷新
      setTimeout(refreshLiveMembers, 600)
    },
    /** 真把某用户移出当前频道（kick） */
    async removeLiveMember(userId: string) {
      if (!currentRoomId.value) return
      await kickFromRoom(currentRoomId.value, userId)
      setTimeout(refreshLiveMembers, 300)
    },

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

    addItem(kind: 'skills' | 'knowledge' | 'rules', label: string, desc: string, tag?: string): boolean {
      const l = label.trim()
      if (!l) return false
      // 同名查重(负责人实报:知识库来源重名能反复添加,列表堆一串相同记录)——
      // 技能/规则同理,同名条目没有第二条的意义。返回 false 让调用方提示。
      if (current.value[kind].some((x) => (x.label || '').trim() === l)) return false
      const item: ChannelInfoItem = { label: l }
      if (desc.trim()) item.desc = desc.trim()
      if (tag && tag.trim()) item.tag = tag.trim()
      current.value[kind].push(item)
      return true
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
