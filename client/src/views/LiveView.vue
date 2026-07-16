<!--
  CosMac Star 真实客户端驾驶舱（按键布局 + 尺寸 1:1 对齐安其演示版 · 暖色皮肤 · 真实后端）
  --------------------------------------------------------------------
  布局/尺寸/按键全部按演示版那套 CSS（topbar/sidebar/channel/composer/plugin-rail/ai-panel）
  的精确数值还原：
    · 顶栏 46 高、品牌按键 36 高、搜索 360 绝对居中、升级会员渐变胶囊、ic-btn 32、头像 28
    · 三块「浮卡」：channels(250) / main(flex) / ai-panel(360) 都 圆角12 + margin8，灰底从缝里透出
    · WorkspaceRail 60 宽、ws-icon 40×40 圆角10、工具图标锚定栏底；PluginRail 40 宽、pr-icon 32 圆形
    · 频道条 active = 白底 + 左侧橙条（非深色填充）；分组头常规 13px
    · 频道头 50 高、★/ic-btn、成员堆叠；消息流为演示版扁平 Slack 风（头像+名+正文，非气泡）
    · Composer 工具条 tb-btn 28、发送键 28 圆形；右侧中枢 AI 面板 head 50、圆形发送
  真实能力（登录/频道/消息/中枢AI/退出/筛选/Markdown 工具）全部接 Synapse；
  纯装饰按钮（升级/提及/收藏/附件等）弹轻量 toast。配色沿用 CosMac 暖色（米白+橙+暖墨），走 tokens.css。
-->
<script setup lang="ts">
import { ref, computed, reactive, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  listCachedAccounts,
  switchToAccount,
  restoreSession,
  onSessionExpired,
  logout,
  onUpdate,
  onTyping,
  roomTyping,
  listRooms,
  listMessages,
  listReactions,
  react,
  unreact,
  sendReply,
  editMessage,
  sendText,
  sendImageFile,
  sendFileAttachment,
  ensureBotDm,
  listAiSessions,
  createAiSession,
  deleteAiSession,
  type AiSession,
  listSpaces,
  roomIdsInSpace,
  aiSessionRoomIds,
  createSpace,
  createChannelInSpace,
  linkRoomToSpace,
  moveRoomToSpace,
  spaceJoinRule,
  setSpaceOpenJoin,
  spaceJoinLink,
  createDirectMessage,
  listDirectMessages,
  isDirectRoom,
  acceptRoomInvite,
  markRoomRead,
  joinSpaceByLink,
  listChannelMembers,
  myPowerIn,
  setMemberPower,
  kickFromSpace,
  banFromSpace,
  unbanFromSpace,
  listBannedMembers,
  type ChannelMember,
  updateSpace,
  updateRoom,
  claimChannelAdmin,
  leaveAndForget,
  uploadMedia,
  mxcToHttp,
  inviteToRoom,
  listRoomMembers,
  isFavourite,
  setFavourite,
  normalizeUserId,
  userExists,
  dmPeerStatus,
  checkUserDeactivated,
  storageCheck,
  isServerAdmin,
  ensureControlRoomMembership,
  acceptPendingInvites,
  isProjectArchived,
  botId,
  aiWorkerSlug,
  contactAlias,
  setContactAlias,
  getChannelConfig,
  fetchMarketCatalog,
  fetchMarketAcquired,
  myAgentsList,
  type LiveRoom,
  type LiveMsg,
  type LiveSpace,
} from '@/matrix/client'
import { tenant } from '@/config/tenant'
import logoUrl from '@/assets/cosmac-logo.png'

// ── 复刻 DEMO 的按键功能：直接复用演示版的弹窗/面板组件 + 它们的 composable ──
// 这些组件都是"常驻挂载、内部 v-if(visible)"模式；按键只需调对应 composable 的 open()。
import MarketplaceModal from '@/components/layout/MarketplaceModal.vue'
import PluginStoreModal from '@/components/layout/PluginStoreModal.vue'
import CustomAssetsModal from '@/components/layout/CustomAssetsModal.vue'
import UserSettingsModal from '@/components/layout/UserSettingsModal.vue'
import ProfileHome from '@/components/layout/ProfileHome.vue'
import CliConsole from '@/components/layout/CliConsole.vue'
// 平台管理后台（覆盖层；仅服务器管理员可入）
import AdminView from '@/views/AdminView.vue'
import MembershipModal from '@/components/membership/MembershipModal.vue'
import ChannelAdminModal from '@/components/channel/ChannelAdminModal.vue'
import KnowledgeModal from '@/components/layout/KnowledgeModal.vue'
import ChoiceCard from '@/components/chat/ChoiceCard.vue'
import AttachmentView from '@/components/chat/AttachmentView.vue'
import MyStudioModal from '@/components/chat/MyStudioModal.vue'
import MyPeopleModal from '@/components/chat/MyPeopleModal.vue'
import MyUsageModal from '@/components/layout/MyUsageModal.vue'
import { useKnowledge } from '@/composables/useKnowledge'
import { useMyPeople } from '@/composables/useMyPeople'
import { useToast } from '@/composables/useToast'
import { useMyUsage } from '@/composables/useMyUsage'
import RightPanel from '@/components/layout/RightPanel.vue'
import { useRightPanel } from '@/composables/useRightPanel'
import BoardSourcePanel from '@/components/layout/BoardSourcePanel.vue'
import { useBoardSources } from '@/composables/useBoardSources'
import SocialSourceModal from '@/components/board/SocialSourceModal.vue'
import { useSocialSources, platformLabel, platformIcon } from '@/composables/useSocialSources'
import OnboardingWizard from '@/components/onboarding/OnboardingWizard.vue'
import DocReader from '@/components/doc/DocReader.vue'
import OrgView from '@/components/org/OrgView.vue'
import { useOnboarding } from '@/composables/useOnboarding'
import { useMarketplace } from '@/composables/useMarketplace'
import { useCli } from '@/composables/useCli'
import { useProfileHome } from '@/composables/useProfileHome'
import { usePluginStore } from '@/composables/usePluginStore'
import { usePlugins } from '@/composables/usePlugins'
import { useCustomAssets, clearCustomAssetsStorage } from '@/composables/useCustomAssets'
import { useUserProfile, type UserSettingsTab } from '@/composables/useUserProfile'
import { useChannelAdmin } from '@/composables/useChannelAdmin'

const { open: openMarket } = useMarketplace()
// 频道头「成员/管理」按钮：复刻 DEMO，点了打开「频道管理」富面板（人设/人员/技能/知识库/规则/数据隔离/模型/记忆）
const { open: openAdmin, setCurrent: setAdminChannel } = useChannelAdmin()
// 频道头 ℹ 按钮：复刻 DEMO，点了开/关右侧「关于此频道」面板（真实成员 + 真实技能/知识库/规则总览）
const { visible: rightPanelVisible, toggle: toggleRightPanel, hide: hideRightPanel } = useRightPanel()
// 看板数据源：数据看板/任务看板的数据源展示(展开列表) + 编辑(弹窗)，按工作区持久化
const { sources, panelOpen: boardPanelOpen, toggleSourcePanel, closeSourcePanel: closeBoardSrcPanel, setSpace: setBoardSpace } = useBoardSources()
// 社媒数据源：看板「社媒数据」组读这份配置渲染（用户配的平台），数值待采集器接入
const { sources: socialSources, openModal: openSocialModal, setSpace: setSocialSpace } = useSocialSources()
// 首次引导：注册/登录后的「主 AI 问答」向导（建工作区/频道/AI人设）
const { maybeAutoStart: maybeStartOnboarding } = useOnboarding()
let onbChecked = false // 首屏只检测一次是否要弹引导
const { open: openCli } = useCli()
// profileVisible 接入 URL 同步（个人主页是页面级覆盖层，给它 /me 地址）
const { open: openProfileHome, visible: profileVisible } = useProfileHome()
const { open: openPluginStore, restore: restorePlugins } = usePluginStore()
// 右侧插件栏渲染的「已装插件」——内置 'ai' 有自己的常驻按钮(智),这里只列商城装的
const { plugins: pluginRail } = usePlugins()
const installedPlugins = computed(() => pluginRail.filter((p) => p.id !== 'ai'))
const { open: openAssets } = useCustomAssets()
const { openSettings, status: myStatus, statusMeta: myStatusMeta, refreshIdentity: refreshMyIdentity } = useUserProfile()

// ── 数据看板 ──
import KpiCard from '@/components/canvas/KpiCard.vue'
import '@/styles/canvas.css' // 看板样式，命名空间在 .canvas/.panel 下，不与 LiveView 撞

// 数据看板 KPI：社媒区跟「接入数据源」配置走（见 socialSources）；下排 = 平台**真实**运营指标
//（会员/工作流/订单/知识库），来自后端 getPlatformStats。
import { getPlatformStats, type PlatformStats } from '@/matrix/client'
const stats = ref<PlatformStats | null>(null)
async function loadStats() { stats.value = await getPlatformStats() }
// 下排：平台运营真实数据；拿不到时为空（不渲染该组，避免空屏占位）
const opsKpis = computed(() => {
  const s = stats.value
  if (!s) return []
  return [
    { label: '付费会员', target: s.members_paid + s.members_creator, unit: '人',
      delta: `创作者 ${s.members_creator}` },
    { label: '工作流运行', target: s.workflow_runs, unit: '次', delta: '累计' },
    { label: '完成订单', target: s.orders_paid, unit: '单', delta: '会员订阅' },
    { label: '知识库文档', target: s.kb_docs, unit: '篇', delta: 'RAG 检索' },
  ]
})

// 看板"一句话下达目标"：真的交给中枢 AI（打开面板 + 复用 aiSend 发给 bot），不再 mock。
const boardAsk = ref('')
async function askFromBoard() {
  const t = boardAsk.value.trim()
  if (!t) return
  boardAsk.value = ''
  aiDraft.value = t
  aiOpen.value = true   // 打开右侧中枢 AI 面板，结果显示在那
  await aiSend()        // 真发给 bot 的 DM 房间
}

// 主区视图：board=数据看板 / tasks=任务看板 / 两者皆 false=频道（登录后默认数据看板）
const board = ref(true)
const tasks = ref(false)
const docs = ref(false)   // 文档视图(类云文档，按工作区一棵页面树)：与 board/tasks 同级
const org = ref(false)    // 组织/人事视图（员工花名册，数据智能演示）：与 board/tasks 同级
function openBoard() { board.value = true; tasks.value = false; docs.value = false; org.value = false; currentRoom.value = '' }
function openTasks() { tasks.value = true; board.value = false; docs.value = false; org.value = false; currentRoom.value = ''; loadTasks() }
function openDocs() {
  docs.value = true; board.value = false; tasks.value = false; org.value = false; currentRoom.value = ''
}
function openOrg() { org.value = true; board.value = false; tasks.value = false; docs.value = false; currentRoom.value = '' }

// 任务看板（AI 任务编排 P1）：主 AI 拆解的真实任务，三列 Kanban + 手动改状态。
import { getTasks, updateTask, currentUserId, type TaskItem } from '@/matrix/client'
const taskList = ref<TaskItem[]>([])
// AI 侧栏放大态右栏：进度=真实任务完成数，项目文件=真实个人知识库文档
const doneCount = computed(() => scopedTasks.value.filter((t) => t.status === 'done').length)
// 个人知识库文档：与「知识库管理」弹窗共用同一份单例（增删后两处同步刷新）
const { docs: kbDocsMine, load: loadKb, open: openKnowledge } = useKnowledge()
// 「我的协作人」弹窗（普通用户维护个人能力名册）
const { open: openMyPeople } = useMyPeople()
// 「我的额度」弹窗（用量配额展示）
const { open: openMyUsage } = useMyUsage()
const TASK_COLS = [
  { key: 'todo', label: '待办' },
  { key: 'doing', label: '进行中' },
  { key: 'done', label: '已完成' },
]
async function loadTasks() { taskList.value = await getTasks() }
// 按当前工作区过滤任务(QA:不同工作区任务看板全一样)。口径与左侧频道列表完全一致:
// 任务所在频道属于本工作区 → 显示;属于**别的**工作区 → 隐藏;不属于任何工作区(孤儿专班/
// 旧任务无 room_id) → 各工作区都显示,避免"任务凭空消失"。
const scopedTasks = computed(() => {
  // 任务按**工作区归属(space_id)**过滤——中枢AI 私聊里拆的任务 room_id 是私聊房、归不了工作区,
  // 光靠 room_id 只能"各处显示",导致每个工作区看板长一样(负责人报的 bug)。现在拆任务时会把
  // 发起人当时所在的工作区盖在任务上,于是:
  //   · 有归属(新任务) → 只在它自己的工作区显示,切工作区内容就真的变;
  //     若归属的工作区我进不去(不是该 Space 成员)但任务派给我 → 仍显示,免得我的任务彻底看不到。
  //   · 无归属(存量老任务) → 沿用旧兜底(按 room_id 判断 / 各处显示),保证一条都不丢。
  const aiIds = aiSessionRoomIds()
  const mySpaceIds = new Set(spaces.value.map((s) => s.id))
  return taskList.value.filter((t) => {
    const sid = t.space_id || ''
    if (sid) {
      if (sid === activeSpace.value) return true      // 就是本工作区的任务
      if (mySpaceIds.has(sid)) return false           // 属于我的另一个工作区 → 只在那边显示
      // 归属工作区我进不去,但**派给我 或 我下达的** → 别弄丢(L11:此前只保留"派给我的",
      // 把"我下达却派给别人、且归属工作区已退出/删除"的任务弄丢了,与后端可见性口径不一致)。
      // 平台管理员额外放行:后端本来就发全量给管理员,但未加入的工作区在左栏没有入口,
      // 这里再按成员身份过滤掉就**永远看不到**(负责人报的 bug)——与"全局管理员"权限定义不符。
      return assignedToMe(t) || dispatchedByMe(t) || isAdmin.value
    }
    // —— 以下为无归属的存量任务：旧口径兜底 ——
    const rid = t.room_id || ''
    if (!activeSpace.value || !rid) return true       // 没选工作区 / 无 room_id:各处显示
    if (spaceChildIds.value.has(rid)) return true     // 本工作区的频道任务
    if (allSpaceChildIds.value.has(rid)) return assignedToMe(t)  // 别的工作区频道:那边看;派给我才兜底
    if (aiIds.has(rid)) return true                   // 自己的 AI 会话房:全局任务
    return true                                        // 私聊/孤儿房:没有归宿 → 各处显示,不丢
  })
})

/** 这条任务是否派给当前登录用户本人(与后端 handle_tasks_list 可见性口径一致)。
 *  比对「localpart」(去掉 @、去掉 :服务器 后缀、小写)——兼容 executor_ref 存全 id / 纯 localpart /
 *  带不带 @ 的各种写法;旧任务无 executor_ref 时按 assignee 首词兜底。 */
function assignedToMe(t: TaskItem): boolean {
  const me = localPartOf(currentUserId())
  if (!me) return false
  const ref = (t.executor_ref || '').trim()
  if (t.executor_kind === 'human' && ref) {
    return localPartOf(ref) === me
  }
  if (!ref) {
    const first = (t.assignee || '').trim().split(/\s+/)[0] || ''
    if (first && localPartOf(first) === me) return true
  }
  return false
}
/** 这条任务是否由当前登录用户**下达**(sender==本人)——与后端可见性口径一致(L11)。 */
function dispatchedByMe(t: TaskItem): boolean {
  const me = localPartOf(currentUserId())
  return !!me && !!t.sender && localPartOf(t.sender) === me
}
/** 取 Matrix user_id 的 localpart：`@duxz01:cosmac.cc` / `duxz01` / `@duxz01` → `duxz01`(小写)。 */
function localPartOf(s: string): string {
  return (s || '').trim().replace(/^@/, '').split(':')[0].toLowerCase()
}
// 按"项目/剧集"(任务的 goal=拆解时的总目标)分组，算每个项目的完成进度
const activeGoal = ref('')   // '' = 全部项目
const projects = computed(() => {
  const m = new Map<string, TaskItem[]>()
  for (const t of scopedTasks.value) {
    const g = t.goal || '未归类'
    if (!m.has(g)) m.set(g, [])
    m.get(g)!.push(t)
  }
  return [...m.entries()].map(([goal, ts]) => {
    const done = ts.filter((t) => t.status === 'done').length
    // 项目完成度 = 已完成任务数占比,与旁边「n/m 完成」同一口径(负责人报:旧算法把
    // 进行中任务的 progress 也平均进来,6/7 显示成 87%,读起来像四舍五入算错了)
    const pct = ts.length ? Math.round((done / ts.length) * 100) : 0
    return { goal, total: ts.length, done, pct }
  })
})
// 已完成项目折叠(负责人建议):100% 完成的项目卡收进"已完成"折叠区,别占满首屏。
// 判定用 done===total(任务全部完成),不用 pct(进行中任务的 progress 平均也可能凑到 100)。
const doneProjectsOpen = ref(false)
const activeProjects = computed(() => projects.value.filter((p) => !(p.total > 0 && p.done === p.total)))
const doneProjects = computed(() => projects.value.filter((p) => p.total > 0 && p.done === p.total))
// 展开条件:手动展开,或当前选中的项目恰好是已完成的(否则选中卡被折叠藏起来,状态看不见)
const showDoneProjects = computed(() =>
  doneProjectsOpen.value || doneProjects.value.some((p) => p.goal === activeGoal.value))
const visibleTasks = computed(() =>
  activeGoal.value ? scopedTasks.value.filter((t) => (t.goal || '未归类') === activeGoal.value) : scopedTasks.value)
// 列内按截止时间升序(负责人建议:最紧急的排最前);无截止时间的沉底,同截止按 id 稳定
function tasksByStatus(s: string) {
  return visibleTasks.value
    .filter((t) => t.status === s)
    .sort((a, b) => ((a.due_ts || Infinity) - (b.due_ts || Infinity)) || (a.id - b.id))
}
// 档2 类型化执行者 → 看板小标签（人/AI/工作流）；none 或无 ref 返回空、不显示
function execLabel(t: TaskItem): string {
  const ref = (t.executor_ref || '').trim()
  if (!ref) return ''
  const k = t.executor_kind
  if (k === 'human') return '👤 ' + ref
  if (k === 'agent') return '🤖 ' + ref
  if (k === 'workflow') return '⚙ ' + ref
  return ''
}
// 截止时间徽章：据 due_ts 与当前时间算"已逾期/今天到期/还剩N天/日期截止"，配色区分紧急度。
// 已完成任务不显示（已经交付了、期限不再有意义）。
function dueMeta(t: TaskItem): { text: string; cls: string } | null {
  if (!t.due_ts || t.status === 'done') return null
  const d = new Date(t.due_ts * 1000)
  const when = `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  const diff = t.due_ts - Date.now() / 1000  // 距截止秒数（负=已逾期）
  if (diff < 0) return { text: `已逾期 · ${when}`, cls: 'overdue' }
  if (diff < 86400) return { text: `今天到期 · ${when}`, cls: 'soon' }
  const days = Math.floor(diff / 86400)
  if (days <= 2) return { text: `还剩 ${days} 天 · ${when}`, cls: 'soon' }
  return { text: `${when} 截止`, cls: '' }
}
function nextStatus(s: string) { return s === 'todo' ? 'doing' : 'done' }
function prevStatus(s: string) { return s === 'done' ? 'doing' : 'todo' }
async function moveTask(t: TaskItem, status: string) {
  const res = await updateTask(t.id, { status })
  if (res.ok) {
    t.status = status
    if (status === 'done') t.progress = 100
  } else {
    // 把后端真实原因告诉用户(如账号被停用后的「登录已失效，请重新登录」),别让按钮"点了没反应"
    toast('操作失败', res.error || '请稍后重试')
  }
}


const HS = 'https://hs.cosmac.cc'

// ── 登录态 ──────────────────────────────────────────────
const user = ref('')
const loggedIn = ref(false)
const me = ref('')
const loading = ref(false)

// ── 频道 / 消息 ─────────────────────────────────────────
const rooms = ref<LiveRoom[]>([])
const currentRoom = ref('')
const msgs = ref<LiveMsg[]>([])
const draft = ref('')
const taRef = ref<HTMLTextAreaElement>()
const filterText = ref('')
const filterInput = ref<HTMLInputElement>()

// ── 右侧"中枢 AI"面板（= 与主 AI 的私聊）────────────────
const aiRoom = ref('')
// ③ 流式体感：中枢 AI 是否"正在输入…"（bot 生成回复期间发 typing 信号，这里渲染气泡）
const botTyping = ref(false)
const aiMsgs = ref<LiveMsg[]>([])
const aiDraft = ref('')
const aiOpen = ref(true)
// ── 多会话（放大态左栏 Recents）：每个会话 = 一个与主 AI 的独立私聊房 ──
const aiSessions = ref<AiSession[]>([])
function refreshAiSessions() { aiSessions.value = listAiSessions() }

// ── 真人私信(DM):渲染在侧栏"私信"区,点开在主区聊天(头部/输入框走简化私聊样式) ──
const dms = ref<{ id: string; name: string; avatar: string; peerId?: string; fav?: boolean; pending?: boolean; fromPeer?: boolean; unread?: number }[]>([])
// 新私信通知(QA:对方发起私信毫无提示,接收方不知道):首轮加载只记不弹(老私信不轰炸),
// 之后 sync 里**新出现的、对方发起的**私信房弹一条通知;正打开着那间房的不弹。
let dmSeeded = false
const seenDmIds = new Set<string>()
function refreshDms() {
  const list = listDirectMessages()
  if (!dmSeeded) {
    for (const d of list) seenDmIds.add(d.id)
    dmSeeded = true
  } else {
    for (const d of list) {
      if (seenDmIds.has(d.id)) continue
      seenDmIds.add(d.id)
      if (d.fromPeer && currentRoom.value !== d.id) {
        toast('📩 收到新私信', `${d.name} 向你发起了私信，点左侧「私信」分组查看`)
      }
    }
  }
  // 正在看的会话:新到的消息即视为已读——本地清零徽章 + 补发已读回执(负责人报:
  // 会话开着时来消息,未读数一直挂着不消。此前只在打开会话那一刻标过一次已读。)
  const cur = list.find((d) => d.id === currentRoom.value)
  if (cur?.unread) {
    cur.unread = undefined
    void markRoomRead(cur.id)
  }
  dms.value = list
}
/** 私信管理:给当前联系人改备注名(存本人 account data,只影响自己看到的显示)。 */
async function renameDmContact() {
  const dm = dms.value.find((d) => d.id === currentRoom.value)
  if (!dm?.peerId) { toast('暂不可用', '没拿到对方账号信息，稍后再试'); return }
  const cur = contactAlias(dm.peerId)
  const alias = prompt(`给「${dm.name}」设置备注名（留空恢复原名）：`, cur)
  if (alias === null) return  // 用户取消
  try {
    await setContactAlias(dm.peerId, alias)
    refreshDms()  // 侧栏与会话头(currentName 取自 dms)立即用新备注
    toast('已更新备注', alias.trim() ? `显示为「${alias.trim()}」` : '已恢复对方原名')
  } catch (e: any) {
    toast('备注保存失败', e?.message || String(e))
  }
}

/** 私信管理:删除当前会话(离开并遗忘——只从自己列表移除,对方不受影响)。 */
async function deleteDmChat() {
  const room = currentRoom.value
  if (!room) return
  if (!confirm(`删除与「${currentName.value}」的私信会话？\n聊天记录将从你的列表中移除（对方不受影响）。对方之后再发消息会重新出现新会话。`)) return
  try {
    await leaveAndForget(room)
    currentRoom.value = ''
    board.value = true
    refreshDms()
    toast('已删除会话', '如需再联系，可从「发起私信」重新开始')
    setTimeout(refresh, 600)
  } catch (e: any) {
    toast('删除失败', e?.message || String(e))
  }
}

const dmDialogOpen = ref(false)     // "发起私信"弹窗
const dmUserInput = ref('')
const dmBusy = ref(false)
function openStartDm() { dmUserInput.value = ''; dmDialogOpen.value = true }
async function doStartDm() {
  const v = dmUserInput.value.trim()
  if (!v || dmBusy.value) return
  dmBusy.value = true
  try {
    // 先校验对方存在——不存在就别建出一个邀请不到人的死私信房,直接给清晰提示。
    if (!(await userExists(v))) {
      toast('该用户不存在', '请检查用户名是否正确（对方需已有账号）')
      return
    }
    const roomId = await createDirectMessage(v)   // 已有则复用,不重复建
    dmDialogOpen.value = false
    // 邀请刚发出,房可能还没 sync 完;稍等再刷新列表并打开
    setTimeout(() => { refresh(); openRoom(roomId) }, 500)
    toast('已发起私信', '对方接受后即可开始聊天')
  } catch (e: any) {
    toast('发起私信失败', e?.message || String(e))
  } finally {
    dmBusy.value = false
  }
}
// 新建会话：建房 → 切过去 → 清空当前对话区（AI 从零开始）
async function newAiSession() {
  try {
    const rid = await createAiSession()
    aiRoom.value = rid
    aiMsgs.value = []
    refreshAiSessions()
    refreshDms()
    refresh()               // 让频道列表把新会话房排除掉
    nextTick(scrollAiToBottom)
  } catch { /* 建会话失败静默，保持当前会话 */ }
}
// 切换到某历史会话：设为当前 aiRoom，重载它的消息
function switchAiSession(roomId: string) {
  if (!roomId || roomId === aiRoom.value) return
  aiRoom.value = roomId
  aiMsgs.value = listMessages(roomId)
  nextTick(scrollAiToBottom)
}
// 删除会话：离开房间；若删的是当前会话，切到下一个（没有则新建）
async function removeAiSession(roomId: string) {
  if (!confirm('删除这个会话？聊天记录将不再显示。')) return
  const wasCurrent = roomId === aiRoom.value
  // L4：先把当前指针移开被删的房，避免下面竞态里 aiSessions[0] 还是它(leave/forget 的 sync 回声
  // 尚未到达)、又被 switchAiSession 切回去（界面看起来"删除没生效"）。
  if (wasCurrent) aiRoom.value = ''
  await deleteAiSession(roomId)
  refreshAiSessions()
  if (wasCurrent) {
    // 从刷新后的列表里**排除刚删的房**再挑下一个（它可能因回声未到仍在列表里）
    const next = aiSessions.value.find((s) => s.roomId !== roomId)?.roomId
    if (next) switchAiSession(next)
    else await newAiSession()
  }
  refresh()
}
// 放大态：把中枢 AI 面板撑成 Cowork 式全屏弹窗（左导航 + 中对话 + 右进度/文件）
const aiMax = ref(false)
// 关闭面板时一并退出放大态，避免下次打开还停在放大
watch(aiOpen, (v) => { if (!v) aiMax.value = false })
// 进入放大态时拉真实数据填右栏（任务进度 + 个人知识库文档）
watch(aiMax, async (v) => {
  if (!v) return
  refreshAiSessions()   // 放大时刷新左栏 Recents 会话列表
  if (!taskList.value.length) loadTasks()
  loadKb()
})

// 中枢 AI 对话区：来新消息 / 打开面板时自动滚到底部（否则 bot 回复在视口下方看不到）
const aiBodyRef = ref<HTMLElement | null>(null)
// ── AI 面板作用域提示条:可关闭,localStorage 记住,不每次都弹 ──
const AI_SCOPE_TIP_KEY = 'cosmac_ai_scope_tip_dismissed'
const aiScopeTipDismissed = ref(localStorage.getItem(AI_SCOPE_TIP_KEY) === '1')
function dismissAiScopeTip() {
  aiScopeTipDismissed.value = true
  try { localStorage.setItem(AI_SCOPE_TIP_KEY, '1') } catch { /* 隐私模式写不进也无妨 */ }
}

// ── 主区消息流滚动:进频道停在底部最新消息(QA:此前打开频道停在顶部历史) ──
const streamRef = ref<HTMLElement | null>(null)
function scrollStreamToBottom(force = false) {
  const el = streamRef.value
  if (!el) return
  // 非强制时只在"本就贴近底部"才跟随——用户上翻看历史时,sync 刷新/新消息不把 TA 拽回底部
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  if (force || nearBottom) el.scrollTop = el.scrollHeight
}
// msgs 每次 sync 整体替换(引用变化即触发):贴底则跟随新消息
watch(msgs, () => nextTick(() => scrollStreamToBottom()))
// 切换频道:强制滚到底(等 DOM 渲染完这一帧)
watch(currentRoom, (id) => { if (id) nextTick(() => scrollStreamToBottom(true)) })

function scrollAiToBottom() {
  const el = aiBodyRef.value
  if (el) el.scrollTop = el.scrollHeight
}
watch(aiMsgs, () => nextTick(scrollAiToBottom), { deep: true })
watch(aiOpen, (v) => { if (v) nextTick(scrollAiToBottom) })

// ── 纯界面态（折叠分组 / 下拉菜单 / 专注模式 / 收藏星）────
const channelsOpen = ref(true)
const favOpen = ref(true)
const dmsOpen = ref(true)
const appMenuOpen = ref(false)
const userMenuOpen = ref(false)
// ── 多账号：切换 / 添加（缓存免密切换）──
const addingAccount = ref(false)
const cachedAccounts = ref<{ userId: string; name: string }[]>([])
function refreshCachedAccounts() {
  cachedAccounts.value = listCachedAccounts().filter((a) => a.userId !== me.value)
}
function toggleUserMenu() {
  userMenuOpen.value = !userMenuOpen.value
  if (userMenuOpen.value) refreshCachedAccounts()
}
function switchAccount(uid: string) {
  if (uid === me.value) return
  if (switchToAccount(uid)) {
    clearCustomAssetsStorage()   // 清本机用户专属缓存，避免带到另一个账号
    window.location.reload()      // 整页 reload：restoreSession 会用新账号会话登入
  }
}
function startAddAccount() {
  userMenuOpen.value = false
  // 跳独立登录页(添加账号模式);当前会话仍在 localStorage,可在登录页「返回当前账号」。
  router.push('/login?add=1')
}
function cancelAddAccount() {
  addingAccount.value = false
  loggedIn.value = true    // mx 仍是当前账号，直接返回
}
// 管理后台：isAdmin 决定菜单入口是否显示（仅服务器管理员可见）；adminOpen 控制覆盖层
const isAdmin = ref(false)
const adminOpen = ref(false)
const focused = ref(false)
const fav = ref(false)
const rootEl = ref<HTMLElement | null>(null)

const currentName = computed(() => {
  const inRooms = rooms.value.find((r) => r.id === currentRoom.value)?.name
  if (inRooms) return inRooms
  // 私信房不在频道列表(rooms)里,而在 dms 里——否则私信头部名字/头像取不到(QA:顶部空白)
  const dm = dms.value.find((d) => d.id === currentRoom.value)
  return dm?.name || ''
})
const currentTopic = computed(
  () => rooms.value.find((r) => r.id === currentRoom.value)?.topic || '',
)
// 当前频道类型角标:公开(任何人可自行加入)/私密(仅邀请可进)。直接读房间的 m.room.join_rules
// (spaceJoinRule 对任意房间通用)。来由:用户分不清"我在私聊还是群里/这群外人进得来吗",
// 曾把邀请发错地方——头部亮出类型,一眼可辨。
const currentVis = computed(() => {
  if (!currentRoom.value) return ''
  return spaceJoinRule(currentRoom.value) === 'public' ? '公开' : '私密'
})
// 当前频道即「当前群」：切频道时让「频道管理」面板跟着切到对应群的配置（每个群一份、互不影响）
// 传 currentRoom（真实 room id）→「人员」标签走真实 Matrix 成员
watch([currentName, currentRoom], ([n, id]) => { if (n) setAdminChannel(n, id) }, { immediate: true })

// 右侧面板互斥：关于此频道 / 中枢 AI / 数据源 同时只开一个（覆盖所有入口）
watch(rightPanelVisible, (v) => { if (v) { aiOpen.value = false; closeBoardSrcPanel() } })
watch(aiOpen, (v) => { if (v) { hideRightPanel(); closeBoardSrcPanel() } })
watch(boardPanelOpen, (v) => { if (v) { aiOpen.value = false; hideRightPanel() } })

// ── 工作区（Matrix Space）──────────────────────────────
const spaces = ref<LiveSpace[]>([])
const activeSpace = ref('')                       // 当前工作区 id
const spaceChildIds = ref<Set<string>>(new Set()) // 当前工作区下的频道 id
// 所有工作区子频道的**并集**:用来识别"不属于任何工作区的孤儿房"(AI 建的专班/被邀请加入的群)。
// 孤儿房在任何工作区下都显示——否则有工作区的成员被邀进 AI 群后,左侧永远没有入口(bug)。
const allSpaceChildIds = ref<Set<string>>(new Set())
const activeSpaceName = computed(
  // 没有工作区/尚未 sync 时用中性名，别拿具体租户名(安其影视)兜底、误当成用户自己的工作区
  () => spaces.value.find((s) => s.id === activeSpace.value)?.name || '我的工作区',
)
// 工作区切换 → 看板数据源跟着切到该工作区的配置（每个工作区一份）
watch(activeSpace, (id) => { setBoardSpace(id); setSocialSpace(id) }, { immediate: true })
function wsLabel(name: string) {
  return [...name.replace(/[·\s]/g, '')].slice(0, 2).join('')
}
function selectSpace(id: string) {
  activeSpace.value = id
  spaceChildIds.value = roomIdsInSpace(id)
  // 切了工作区，若当前正看的频道不属于新工作区：别停在"频道模式却没频道"的**空白页**
  // (顶部频道名空白、正文还是旧频道——用户实测到的 bug)，直接回到该工作区的「数据看板」。
  // currentRoom 有值 ⟺ 正处于频道视图(openRoom 会把 board/tasks/docs/org 全置 false)，
  // 故这里可安全地用 openBoard() 一步切回看板(它会把 board=true 且清空 currentRoom)。
  if (currentRoom.value && !spaceChildIds.value.has(currentRoom.value)) openBoard()
  // 任务看板选中的"项目"是上个工作区的,清掉回到「全部项目」
  activeGoal.value = ''
}

// ── 工作区设置（点工作区名打开，改名称 / 简称）──
const wsSetOpen = ref(false)
const wsSetName = ref('')
const wsSetLabel = ref('')
const wsSetBusy = ref(false)
const wsDeleteArm = ref(false) // 删除工作区的二次确认
// 工作区头像：avatarChange=undefined 不动 / '' 移除 / mxc 新图；preview 仅用于弹窗内显示
const wsSetAvatarChange = ref<string | undefined>(undefined)
const wsSetAvatarPreview = ref('')
const wsUploading = ref(false)
const wsFileInput = ref<HTMLInputElement>()
// 社区服务器：开放加入 + 邀请链接
const wsOpenJoin = ref(false)          // 当前工作区是否"开放加入"(join_rule=public)
const wsJoinBusy = ref(false)
const wsLinkCopied = ref(false)
const wsJoinLink = computed(() => activeSpace.value ? spaceJoinLink(activeSpace.value) : '')
function openWsSettings() {
  if (!activeSpace.value) return
  const s = spaces.value.find((x) => x.id === activeSpace.value)
  wsSetName.value = s?.name || ''
  wsSetLabel.value = s?.label || ''
  wsSetAvatarChange.value = undefined
  wsSetAvatarPreview.value = s?.avatarUrl || ''
  wsDeleteArm.value = false
  wsOpenJoin.value = spaceJoinRule(activeSpace.value) === 'public'
  wsOpenConfirm.value = false
  wsLinkCopied.value = false
  wsSetOpen.value = true
}
const wsOpenConfirm = ref(false)       // 开启公开前的确认态(公开=高风险动作,必须看清后果再点)
async function toggleWsOpenJoin() {
  if (!activeSpace.value || wsJoinBusy.value) return
  if (!wsOpenJoin.value) {
    // 关→开:公开意味着"谁拿到链接谁就能进全部频道、无审批"——先弹确认,看清后果再执行
    wsOpenConfirm.value = true
    return
  }
  // 开→关:收紧动作,低风险,直接执行
  await applyWsOpenJoin(false)
}
async function applyWsOpenJoin(next: boolean) {
  if (!activeSpace.value || wsJoinBusy.value) return
  wsJoinBusy.value = true
  try {
    await setSpaceOpenJoin(activeSpace.value, next)
    wsOpenJoin.value = next
    wsOpenConfirm.value = false
    toast(
      next ? '已公开工作区' : '已恢复私密',
      next ? '任何人凭邀请链接都能加入本工作区的全部频道' : '链接已失效;已加入的成员不会被自动移除',
    )
  } catch (e: any) {
    toast('操作失败', e?.message || '可能没有权限')
  } finally {
    wsJoinBusy.value = false
  }
}
async function copyWsJoinLink() {
  try {
    await navigator.clipboard.writeText(wsJoinLink.value)
    wsLinkCopied.value = true
    setTimeout(() => { wsLinkCopied.value = false }, 1500)
  } catch { toast('复制失败', '请手动复制链接') }
}

// ── 社区服务器：成员列表 + 角色管理 ──
const memberMgrOpen = ref(false)
const serverMembers = ref<ChannelMember[]>([])
const bannedMembers = ref<{ id: string; name: string; avatar: string }[]>([])
const myServerPower = ref(0)          // 我在这个服务器的 power（决定能做什么）
const memberMgrBusy = ref('')          // 正在操作的 user id（禁用该行按钮）
function reloadServerMembers() {
  if (!activeSpace.value) return
  myServerPower.value = myPowerIn(activeSpace.value)
  serverMembers.value = listChannelMembers(activeSpace.value).filter((m) => !m.pending || myServerPower.value >= 50)
  bannedMembers.value = myServerPower.value >= 50 ? listBannedMembers(activeSpace.value) : []
}
function openServerMembers() {
  if (!activeSpace.value) return
  myServerPower.value = myPowerIn(activeSpace.value)
  reloadServerMembers()
  wsSetOpen.value = false
  memberMgrOpen.value = true
}
// 「刷新」原来直接调 reloadServerMembers:它是同步读本地 sync 状态、瞬间返回,按钮毫无反馈,
// 用户不知道点没点到。这里给一个明确的忙态 + 结果 toast(读的是最新成员数,不是假动画)。
const mmgRefreshing = ref(false)
async function refreshServerMembers() {
  if (mmgRefreshing.value) return
  mmgRefreshing.value = true
  try {
    reloadServerMembers()
    await nextTick()   // 让「刷新中…」渲染出来一帧,按钮有可见反馈
    toast('已刷新', `当前 ${serverMembers.value.length} 位工作区成员`)
  } finally {
    mmgRefreshing.value = false
  }
}
// 二级弹窗回到上一级:关成员管理、重开「工作区设置」(此前进来就回不去了)
function backToWsSettings() {
  memberMgrOpen.value = false
  wsSetOpen.value = true
}
// 我能不能管理某成员：我≥50、且对方 power 比我低、且不是我自己/bot
function canManage(m: ChannelMember): boolean {
  return myServerPower.value >= 50 && m.power < myServerPower.value && m.id !== me.value && !m.isBot
}
async function setMemberRole(m: ChannelMember, power: number) {
  if (!activeSpace.value || memberMgrBusy.value) return
  memberMgrBusy.value = m.id
  try {
    await setMemberPower(activeSpace.value, m.id, power)
    toast('已更新', `${m.name} → ${power >= 50 ? '管理员' : '成员'}`)
    setTimeout(reloadServerMembers, 500)
  } catch (e: any) {
    toast('操作失败', e?.message || '可能权限不足')
  } finally {
    memberMgrBusy.value = ''
  }
}
async function removeServerMember(m: ChannelMember) {
  if (!activeSpace.value || memberMgrBusy.value) return
  if (!confirm(`把「${m.name}」移出这个服务器（含其下频道）？他之后仍可再加入。`)) return
  memberMgrBusy.value = m.id
  try {
    await kickFromSpace(activeSpace.value, m.id)
    toast('已移出', m.name)
    setTimeout(reloadServerMembers, 500)
  } catch (e: any) {
    toast('移出失败', e?.message || '可能权限不足')
  } finally {
    memberMgrBusy.value = ''
  }
}
async function banServerMember(m: ChannelMember) {
  if (!activeSpace.value || memberMgrBusy.value) return
  if (!confirm(`封禁「${m.name}」？他将被移出、且**无法再加入**这个服务器，直到你解封。`)) return
  memberMgrBusy.value = m.id
  try {
    await banFromSpace(activeSpace.value, m.id)
    toast('已封禁', m.name)
    setTimeout(reloadServerMembers, 500)
  } catch (e: any) {
    toast('封禁失败', e?.message || '可能权限不足')
  } finally {
    memberMgrBusy.value = ''
  }
}
async function unbanServerMember(u: { id: string; name: string }) {
  if (!activeSpace.value || memberMgrBusy.value) return
  memberMgrBusy.value = u.id
  try {
    await unbanFromSpace(activeSpace.value, u.id)
    toast('已解封', `${u.name} 现在可以重新加入`)
    setTimeout(reloadServerMembers, 500)
  } catch (e: any) {
    toast('解封失败', e?.message || '可能权限不足')
  } finally {
    memberMgrBusy.value = ''
  }
}
async function onPickWsImage(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  wsUploading.value = true
  try {
    const mxc = await uploadMedia(file)
    wsSetAvatarChange.value = mxc
    // 预览用**本地文件**的 object URL,而不是 mxcToHttp(mxc)——新版 Synapse 强制"已认证媒体",
    // <img> 带不了 Authorization 头,直接引用媒体 URL 会加载失败(显示裂图)。本地文件必渲染、且即时。
    if (wsPreviewObjUrl) URL.revokeObjectURL(wsPreviewObjUrl)
    wsPreviewObjUrl = URL.createObjectURL(file)
    wsSetAvatarPreview.value = wsPreviewObjUrl
  } catch (err: any) {
    toast('上传失败', err?.message || String(err))
  } finally {
    wsUploading.value = false
    if (wsFileInput.value) wsFileInput.value.value = '' // 允许重选同一文件
  }
}
// 预览用的本地 object URL（换图/移除/关闭时回收，避免内存泄漏）
let wsPreviewObjUrl = ''
function removeWsImage() {
  wsSetAvatarChange.value = ''
  wsSetAvatarPreview.value = ''
  if (wsPreviewObjUrl) { URL.revokeObjectURL(wsPreviewObjUrl); wsPreviewObjUrl = '' }
}

// 简称统一限制为「2 个字符」——按码点(visual char)算，中/英/日/韩/emoji 都是 2 个为上限。
function clamp2(s: string): string {
  return [...s].slice(0, 2).join('')
}
watch(wsSetLabel, (v) => { const c = clamp2(v); if (c !== v) wsSetLabel.value = c })
// 当前工作区下的频道数（删除确认提示用）
const wsChildCount = computed(() => (activeSpace.value ? roomIdsInSpace(activeSpace.value).size : 0))
async function deleteWorkspace() {
  const id = activeSpace.value
  if (!id || wsSetBusy.value) return
  wsSetBusy.value = true
  try {
    // 先退出该工作区下的所有频道，再退出工作区本身
    for (const cid of roomIdsInSpace(id)) {
      try { await leaveAndForget(cid) } catch { /* 单个失败不阻断 */ }
    }
    await leaveAndForget(id)
    toast('已删除工作区', wsSetName.value)
    wsSetOpen.value = false
    activeSpace.value = ''
    setTimeout(() => {
      refresh()
      board.value = true; tasks.value = false; currentRoom.value = ''
    }, 900)
  } catch (e: any) {
    toast('删除失败', e?.message || String(e))
  } finally {
    wsSetBusy.value = false
  }
}
async function saveWsSettings() {
  const id = activeSpace.value
  const name = wsSetName.value.trim()
  if (!id || !name || wsSetBusy.value) return
  wsSetBusy.value = true
  try {
    await updateSpace(id, { name, label: wsSetLabel.value.trim(), avatar: wsSetAvatarChange.value })
    toast('已保存', `工作区改为「${name}」`)
    wsSetOpen.value = false
    setTimeout(refresh, 700)
  } catch (e: any) {
    toast('保存失败', e?.message || String(e))
  } finally {
    wsSetBusy.value = false
  }
}

// ── 频道设置（点频道头标题打开，改名称 / 简介）──
const chSetOpen = ref(false)
const chSetName = ref('')
const chSetTopic = ref('')
const chSetBusy = ref(false)
const chDeleteArm = ref(false)
// 「移动到工作区」：弹窗里的目标工作区选择，初始=当前工作区；保存时若变了就真移动。
// （负责人需求：粉丝运营等要独立工作区,频道得能从原工作区挪过去。）
const chSetSpace = ref('')
function openChannelSettings() {
  if (!currentRoom.value) return
  chSetName.value = currentName.value
  chSetTopic.value = currentTopic.value
  chSetSpace.value = activeSpace.value
  chDeleteArm.value = false
  chDeleteTaskWarn.value = 0
  chSetOpen.value = true
}
const chDeleteTaskWarn = ref(0)   // 本频道未完成任务数(>0 时删除前多一道确认)
async function deleteChannel() {
  const id = currentRoom.value
  if (!id || chSetBusy.value) return
  // 软提醒(方案1):删除前查本频道未完成任务(非 done)。有则先弹一次"知情确认",不硬拦——
  // 给知情权,又不因一条遗留任务把想删废弃频道的人锁死。已经确认过(warn>0)则放行。
  if (chDeleteTaskWarn.value === 0) {
    try {
      const tasks = await getTasks()
      const pending = tasks.filter((t) => t.room_id === id && t.status !== 'done').length
      if (pending > 0) {
        chDeleteTaskWarn.value = pending
        return   // 停在设置面板,模板会显示黄色提醒 + "仍要删除"按钮
      }
    } catch { /* 查任务失败不阻断删除,退化为无提醒 */ }
  }
  chSetBusy.value = true
  try {
    await leaveAndForget(id)
    toast('已退出频道', `${chSetName.value}（频道本身仍在，其他成员不受影响）`)
    chSetOpen.value = false
    currentRoom.value = ''
    chDeleteTaskWarn.value = 0
    setTimeout(refresh, 800)
  } catch (e: any) {
    toast('操作失败', e?.message || String(e))
  } finally {
    chSetBusy.value = false
  }
}
async function saveChannelSettings() {
  const id = currentRoom.value
  const name = chSetName.value.trim()
  if (!id || !name || chSetBusy.value) return
  // 改名也查重(排除自己):别把频道改成本工作区已有的名字,造成重名分不清。
  if (channelNameExists(name, id)) {
    toast('频道名已存在', `本工作区已有「${name}」频道，换个名字吧`)
    return
  }
  chSetBusy.value = true
  try {
    try {
      await updateRoom(id, { name, topic: chSetTopic.value.trim() })
    } catch (e: any) {
      // 改名/改简介需要 50 级权限。旧频道里主人只有 0 级(bot 建房时没提权)→ 403。
      // 让后端认领本频道管理员(仅平台管理员或无主频道的成员放行)，成功后重试一次。
      if (await claimChannelAdmin(id)) {
        await updateRoom(id, { name, topic: chSetTopic.value.trim() })
      } else {
        throw e
      }
    }
    // 目标工作区变了 → 真移动（先挂进新工作区、再从旧的摘除,详见 moveRoomToSpace）。
    // 放在改名之后:名字/简介保存失败会先抛出去,不会出现"名没改成却已被挪走"的半截态。
    if (chSetSpace.value && chSetSpace.value !== activeSpace.value) {
      const target = chSetSpace.value
      const res = await moveRoomToSpace(activeSpace.value, target, id)
      if (res === 'fail') {
        toast('移动失败', '你可能没有目标工作区的管理权限')
        return
      }
      const tname = spaces.value.find((s) => s.id === target)?.name || '目标工作区'
      // 本地状态跟着走,别等 sync:切到目标工作区并保持频道打开(频道跟人走)
      activeSpace.value = target
      spaceChildIds.value = new Set([...roomIdsInSpace(target), id])
      allSpaceChildIds.value = new Set([...allSpaceChildIds.value, id])
      toast(
        res === 'ok' ? '已移动频道' : '已挂进新工作区',
        res === 'ok' ? `「${name}」现在属于「${tname}」` : `「${name}」已进「${tname}」;原工作区无权摘除,它暂时两边可见`,
      )
    } else {
      toast('已保存', `频道改为「${name}」`)
    }
    chSetOpen.value = false
    setTimeout(refresh, 700)
  } catch (e: any) {
    toast('保存失败', e?.message || String(e))
  } finally {
    chSetBusy.value = false
  }
}

// ── 新建工作区（完整表单：类型 / 名称 / 简称 / 可见性 / 按类型建默认频道）──
interface WsType { key: string; title: string; nameLabel: string; namePh: string; spaceName: (n: string) => string; chans: (n: string) => string[] }
const WS_TYPES: WsType[] = [
  { key: '制作', title: '制作', nameLabel: '项目/部门名', namePh: '如：新剧《潮汐》', spaceName: (n) => `制作·${n}`, chans: (n) => [`${n} 制作专班`] },
  { key: '运营', title: '运营营销', nameLabel: '工作区名称', namePh: '如：海外发行', spaceName: (n) => n, chans: (n) => [`${n} · 运营`] },
  { key: '明星', title: '明星·粉丝', nameLabel: '虚拟明星名', namePh: '如：墨白', spaceName: (n) => `明星·${n}`, chans: (n) => [`虚拟明星·${n}`, `${n}后援会`] },
  { key: '外部', title: '外部', nameLabel: '工作区名称', namePh: '如：某品牌合作', spaceName: (n) => n, chans: (n) => [`${n} · 对外洽谈`] },
]
const newWsOpen = ref(false)
const newWsType = ref('制作')
const newWsName = ref('')
const newWsLabel = ref('')
watch(newWsLabel, (v) => { const c = clamp2(v); if (c !== v) newWsLabel.value = c })
const newWsPublic = ref(false)
const newWsCreating = ref(false)
const curWsType = computed(() => WS_TYPES.find((t) => t.key === newWsType.value) || WS_TYPES[0])
const newWsSpaceName = computed(() => (newWsName.value.trim() ? curWsType.value.spaceName(newWsName.value.trim()) : ''))
const newWsChannels = computed(() => (newWsName.value.trim() ? curWsType.value.chans(newWsName.value.trim()) : []))
function openNewWorkspace() {
  newWsType.value = '制作'; newWsName.value = ''; newWsLabel.value = ''; newWsPublic.value = false; newWsOpen.value = true
}
async function createWorkspace() {
  const n = newWsName.value.trim()
  if (!n || newWsCreating.value) return
  const t = curWsType.value
  const spaceName = t.spaceName(n)
  const label = newWsLabel.value.trim() || wsLabel(spaceName)
  const pub = newWsPublic.value
  newWsCreating.value = true
  try {
    const sid = await createSpace(spaceName, { public: pub, label })
    for (const cn of t.chans(n)) await createChannelInSpace(sid, cn, { public: pub })
    toast('已创建工作区', `${spaceName}（${t.chans(n).length} 个频道）`)
    newWsOpen.value = false
    setTimeout(() => {
      refresh()
      activeSpace.value = sid
      spaceChildIds.value = roomIdsInSpace(sid)
      board.value = false; tasks.value = false; currentRoom.value = ''
    }, 900)
  } catch (e: any) {
    toast('创建失败', e?.message || String(e))
  } finally {
    newWsCreating.value = false
  }
}

// ── 新建频道（在当前工作区下真建）──
const newChOpen = ref(false)
const newChName = ref('')
const newChTopic = ref('')
const newChPublic = ref(false)
const newChCreating = ref(false)
function openNewChannel() {
  if (!activeSpace.value) { toast('请先选一个工作区', '频道需要归属到某个工作区'); return }
  newChName.value = ''; newChTopic.value = ''
  // L6：公开工作区里新建频道**默认公开**——与"任何人凭链接可加入全部频道"的承诺一致，避免凭链接
  // 进来的人进不去后建的私密频道。用户仍可在弹窗里改回私密。
  newChPublic.value = spaceJoinRule(activeSpace.value) === 'public'
  newChOpen.value = true
}
/** 频道名归一化(去首尾空格、内部空白折叠成一个、转小写)——用于重名比对。 */
function normChanName(s: string): string {
  return (s || '').trim().replace(/\s+/g, ' ').toLowerCase()
}
/** 当前工作区内是否已存在同名频道(可排除某个 id,给"改名不算和自己撞名"用)。
 *  只在**本工作区**范围查重——不同工作区允许重名;重名会让主AI/用户都分不清哪个是哪个。 */
function channelNameExists(name: string, excludeId = ''): boolean {
  const target = normChanName(name)
  if (!target) return false
  return rooms.value.some(
    (r) => r.id !== excludeId
      && (!activeSpace.value || spaceChildIds.value.has(r.id))
      && normChanName(r.name) === target,
  )
}

async function createChannel() {
  const n = newChName.value.trim()
  if (!n || newChCreating.value || !activeSpace.value) return
  // 建之前先查重:本工作区已有同名频道就拦下,免得建出两个「员工招聘」谁也分不清(含主AI)。
  if (channelNameExists(n)) {
    toast('频道名已存在', `本工作区已有「${n}」频道，换个名字吧`)
    return
  }
  newChCreating.value = true
  try {
    const cid = await createChannelInSpace(activeSpace.value, n, { public: newChPublic.value, topic: newChTopic.value.trim() })
    toast('已创建频道', `# ${n} → ${activeSpaceName.value}`)
    newChOpen.value = false
    setTimeout(() => {
      refresh()
      openRoom(cid)
    }, 900)
  } catch (e: any) {
    toast('创建失败', e?.message || String(e))
  } finally {
    newChCreating.value = false
  }
}

// ── 成员管理（邀请已有用户进当前频道/工作区）──
// 注：「新建账号」需走 Synapse Admin API，而 admin API 不对外代理、也不该把 admin token 暴露到浏览器，
// 所以建账号留给后端（业务后台）做；这里先做能从客户端真跑通的「邀请已有用户」。
const memberOpen = ref(false)
const inviteUserInput = ref('')
const memberBusy = ref(false)
const memberList = ref<{ id: string; name: string; isBot: boolean; pending?: boolean }[]>([])
// 邀请目标：优先当前打开的频道，否则当前工作区(Space)
const memberTarget = computed(() => {
  if (currentRoom.value) return { id: currentRoom.value, name: `#${currentName.value}` }
  if (activeSpace.value) return { id: activeSpace.value, name: `${activeSpaceName.value} 工作区` }
  return null
})
function openMembers() {
  inviteUserInput.value = ''
  memberList.value = memberTarget.value ? listRoomMembers(memberTarget.value.id) : []
  memberOpen.value = true
}
async function doInvite() {
  const t = memberTarget.value
  const uid = normalizeUserId(inviteUserInput.value)
  if (!t || !uid || memberBusy.value) return
  memberBusy.value = true
  try {
    await inviteToRoom(t.id, uid)
    toast('已邀请', `${uid} → ${t.name}`)
    inviteUserInput.value = ''
    setTimeout(() => { memberList.value = listRoomMembers(t.id) }, 600)
  } catch (e: any) {
    toast('邀请失败', e?.message || String(e))
  } finally { memberBusy.value = false }
}

// 频道列表：按当前工作区过滤 + 关键词筛选。
// 孤儿房(不属于任何工作区)**不再混进这里**——此前混着放行导致"不同工作区群都一样"(QA):
// AI 建的专班/别人拉我进的群一多,每个工作区的频道列表就长一个样。现在它们单独进「未归类」组。
const filteredRooms = computed(() =>
  rooms.value.filter(
    (r) =>
      (!activeSpace.value || spaceChildIds.value.has(r.id)) &&
      (!filterText.value || r.name.includes(filterText.value)),
  ),
)
// 未归类 = 孤儿房。必须有入口(否则被邀成员进不了群——历史 bug),但集中一组、明确标注,
// 且可一键「归入」当前工作区(写 m.space.child),归入后就只在那个工作区显示。
const orphanRooms = computed(() =>
  !activeSpace.value ? [] : rooms.value.filter(
    (r) =>
      !allSpaceChildIds.value.has(r.id) &&
      (!filterText.value || r.name.includes(filterText.value)),
  ),
)
const orphanOpen = ref(true)
const adoptBusy = ref('')
async function adoptOrphan(r: { id: string; name: string }) {
  if (!activeSpace.value || adoptBusy.value) return
  adoptBusy.value = r.id
  try {
    if (await linkRoomToSpace(activeSpace.value, r.id)) {
      // 本地立即把它算进本工作区(sync 稍后也会带来),频道从「未归类」挪进「频道」组
      spaceChildIds.value = new Set([...spaceChildIds.value, r.id])
      allSpaceChildIds.value = new Set([...allSpaceChildIds.value, r.id])
      toast('已归入本工作区', r.name)
    } else {
      toast('归入失败', '你可能没有本工作区的管理权限')
    }
  } finally { adoptBusy.value = '' }
}

// 某频道是否「已归档专班」（bot 收尾写 cosmac.project.archived）：灰显 + 排到最后。
function isArchived(id: string): boolean { return isProjectArchived(id) }
// 收藏的频道（m.favourite 标签）——单独置顶成「收藏」组;已收藏的不再在下面的普通组重复出现。
const favRooms = computed(() =>
  filteredRooms.value
    .filter((r) => r.fav)
    .sort((a, b) => a.name.localeCompare(b.name, 'zh')),
)
// 普通频道（剔除已收藏的）；已归档的排到最后（在用频道在前，留档不打扰）。
// （曾按名称启发式单列过「粉丝社区」分组，负责人拍板撤销：粉丝运营应是独立工作区,不是频道分组。）
const channelRooms = computed(() =>
  filteredRooms.value
    .filter((r) => !r.fav)
    .sort((a, b) => Number(isArchived(a.id)) - Number(isArchived(b.id))),
)

// ── 频道彩色图标：按名字确定性取色 + 取代表字（无需后端，所有频道立即生效）──
const CHAN_PALETTE = ['#c96442', '#6b8e4e', '#4a7a8c', '#b58932', '#8a6a8a', '#5a7a8a', '#b94a4a', '#7a8a5a']
function colorOf(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return CHAN_PALETTE[h % CHAN_PALETTE.length]
}
/** 取频道代表字：优先「·」后一段 / 《》内首字，否则去掉前缀符号取首字 */
function iconChar(name: string): string {
  const s = name.trim()
  const dot = s.lastIndexOf('·')
  if (dot >= 0 && dot < s.length - 1) return [...s.slice(dot + 1)][0]
  const m = s.match(/《(.)/)
  if (m) return m[1]
  return [...s.replace(/^[#\s]+/, '')][0] || '#'
}

function isBot(s: string) {
  return s === botId()
}

// ── 安全的极简 Markdown 渲染（消息显示用）──
// 先 HTML 转义（防 XSS：任何 <script> 都变成纯文本），再做有限的 markdown 替换。
// 代码块/行内代码先抠出占位、避免里面的符号被二次处理。
function escapeHtml(s: string): string {
  // 必须连引号一起转义：链接渲染时 url 会进 href="...", 不转 " 会被击穿属性边界注入属性。
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}
function renderMd(raw: string): string {
  // 先剥掉占位哨兵字符 \x00：下面用它做代码块占位，若用户原文里带 \x00 会污染还原逻辑。
  let s = escapeHtml((raw || '').replace(/\x00/g, ''))
  const stash: string[] = []
  const keep = (html: string) => `\x00${stash.push(html) - 1}\x00`
  // 代码块 ```...```
  s = s.replace(/```([\s\S]*?)```/g, (_m, c) => keep(`<pre class="md-pre">${c.replace(/^\n|\n$/g, '')}</pre>`))
  // 行内代码 `...`
  s = s.replace(/`([^`\n]+)`/g, (_m, c) => keep(`<code class="md-code">${c}</code>`))
  // 加粗 / 斜体 / 删除线
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  s = s.replace(/~~([^~\n]+)~~/g, '<del>$1</del>')
  // 链接 [文字](url)，仅允许 http/https/mailto。生成的 <a> 也 stash——否则下面的"裸 URL 成链"
  // 会把 href 里的 url 二次匹配。
  s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/g,
    (_m, text, url) => keep(`<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`))
  // 裸露 URL 自动成链（QA:工作区/邀请链接直接粘贴时显示成纯文本、点不了）。
  // 放在 markdown 链接之后(那些已被 stash 抠走)、@提及之前;剥掉末尾句读避免把中文句号/右括号吃进链接。
  s = s.replace(/(https?:\/\/[^\s<]+)/g, (m) => {
    const tail = m.match(/[.,;:!?)\]}）】。，、！？]+$/)
    const url = tail ? m.slice(0, -tail[0].length) : m
    const suffix = tail ? tail[0] : ''
    return keep(`<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`) + suffix
  })
  // @提及高亮（@用户 或 @用户:服务器）
  s = s.replace(/(^|[\s(])@([a-zA-Z0-9_.\-]+(?::[a-zA-Z0-9_.\-]+)?)/g, '$1<span class="mention">@$2</span>')
  // 块级：标题 / 引用 / 无序列表（L8：composer 工具条有这三个按钮，渲染端此前不支持、对方看到
  // 字面 "## 标题"）。逐行判断，放在换行→<br> 之前；块级行渲染成独立块元素、其间不加 <br>，
  // 只有相邻的普通行之间才用 <br> 连接。注意此时文本已被 escapeHtml，故 ">" 已是 "&gt;"。
  const parts = s.split('\n').map((ln) => {
    let mm = ln.match(/^(#{1,3})\s+(.+)$/)
    if (mm) return { block: true, html: `<div class="md-h md-h${mm[1].length}">${mm[2]}</div>` }
    mm = ln.match(/^&gt;\s?(.*)$/)
    if (mm) return { block: true, html: `<blockquote class="md-quote">${mm[1]}</blockquote>` }
    mm = ln.match(/^[-*]\s+(.+)$/)
    if (mm) return { block: true, html: `<div class="md-li">•&nbsp;${mm[1]}</div>` }
    return { block: false, html: ln }
  })
  s = ''
  parts.forEach((p, i) => {
    if (i > 0 && !p.block && !parts[i - 1].block) s += '<br>'
    s += p.html
  })
  // 还原代码占位
  s = s.replace(/\x00(\d+)\x00/g, (_m, i) => stash[+i])
  return s
}
function fmtTime(ts: number) {
  const d = new Date(ts)
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}
// 日期分隔线标签：今天 / 昨天 / X月X日
function dayKey(ts: number) {
  const d = new Date(ts)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}
function dayLabel(ts: number) {
  const d = new Date(ts)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const that = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const diff = Math.round((today - that) / 86400000)
  if (diff === 0) return '今天'
  if (diff === 1) return '昨天'
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日`
}
// 发送者名字配色（沿用频道调色板做确定性取色）
function nameColor(name: string) {
  return colorOf(name)
}

// ── 轻量 toast ──────────────────────────────────────────
interface Toast { id: number; title: string; msg?: string }
const toasts = ref<Toast[]>([])
let toastSeq = 0
function toast(title: string, msg?: string) {
  const id = ++toastSeq
  toasts.value.push({ id, title, msg })
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }, 2600)
}
// 全局 useToast(协作人/知识库/后台等 composable 在用)此前从没被渲染过——它假想的
// <ToastHost /> 挂在 App.vue,但真实根组件是 LiveView。在这里把它的队列一并渲染,
// 否则那些页面的成功/报错反馈(含"需要会员"403)全部静默丢失。
const { items: globalToasts } = useToast()

// ── 真实数据刷新 ────────────────────────────────────────
function refresh() {
  // 工作区（Space）：加载（listSpaces 已按 order 稳定排序，改名不影响顺序）
  spaces.value = listSpaces()
  // 校正激活项（默认第一个 = order 最小 = 制作中心）
  if (!activeSpace.value || !spaces.value.some((s) => s.id === activeSpace.value)) {
    activeSpace.value = spaces.value[0]?.id || ''
  }
  spaceChildIds.value = activeSpace.value ? roomIdsInSpace(activeSpace.value) : new Set()
  // 重算"所有工作区子频道并集"(识别孤儿房用;每次刷新重算,新挂接的频道自动归位)
  {
    const all = new Set<string>()
    for (const sp of spaces.value) for (const id of roomIdsInSpace(sp.id)) all.add(id)
    allSpaceChildIds.value = all
  }
  rooms.value = listRooms().filter((r) => r.id !== aiRoom.value)
  maybeAcceptInvites()   // 在线期间收到的邀请也实时接受(不用重新登录)
  if (currentRoom.value) {
    msgs.value = listMessages(currentRoom.value)
    channelMembers.value = listRoomMembers(currentRoom.value)
    reactions.value = listReactions(currentRoom.value)
  }
  if (aiRoom.value) aiMsgs.value = listMessages(aiRoom.value)
  refreshAiSessions() // 会话列表（标题随首条消息、排序随最近活跃）跟着每次刷新更新
  refreshDms() // 私信列表也随 sync 刷新——否则别人发起的私信,接收方侧栏永远不出现(QA)
  // bot 建专班后发来的 team_created 信号卡：把新专班挂进当前工作区（bot 没权限、客户端来补）
  processTeamCards()

  // 首屏按浏览器地址还原导航状态（支持刷新留在原页 / 深链直达某频道）。
  // 深链到频道时需等房间列表加载好再解析；其余地址不必等。只做一次。
  if (!urlRestored) {
    const needRoom = /^\/s\/[^/]+\/c\//.test(route.path)
    // L7：深链到频道要等房间列表加载好再解析；但**零房间账号**永远等不到 rooms.value.length，
    // 会导致 urlRestored/syncReady 永不置位、之后所有导航都不再写地址(后退/前进/刷新全失效)。
    // 故加一个兜底期限：超过它即便房间没到也强制还原(applyFromRoute 对找不到的房会优雅回退看板)。
    if (!restoreDeadline) restoreDeadline = Date.now() + 3000
    if (!needRoom || rooms.value.length || Date.now() > restoreDeadline) {
      applyFromRoute()
      urlRestored = true
      syncReady = true // 还原完成后才允许"状态→地址"回写，避免覆盖初始深链
      // 规范化地址（如登录默认页 → /s/<空间>/board）
      const path = computePath()
      if (route.path !== path) router.replace(path).catch(() => {})
      // 首屏同步就绪后检测一次：**全新账号**（没引导过 且 还没有任何工作区）弹首次引导。
      // 放这里是因为此刻 account data 已同步，isOnboarded() 读得准；额外用"无工作区"双保险，
      // 避免给已有频道的老用户弹引导（maybeAutoStart 内部再判 isOnboarded）。
      if (!onbChecked) { onbChecked = true; if (!spaces.value.length) maybeStartOnboarding() }
    }
  }
}

/** 引导完成：刷新工作区列表 + 切到新建的工作区 + 回到数据看板。 */
async function onOnboardingDone(spaceId: string) {
  // 新建的 Space 可能还没 sync 进本地房间列表；轮询刷新几次直到它出现，否则
  // activeSpaceName 会回退到租户默认名（"安其影视"），界面看着像没改成自己的工作区。
  for (let i = 0; i < 12; i++) {
    refresh()
    if (!spaceId || spaces.value.some((s) => s.id === spaceId)) break
    await new Promise((r) => setTimeout(r, 300))
  }
  if (spaceId) { activeSpace.value = spaceId; spaceChildIds.value = roomIdsInSpace(spaceId) }
  openBoard()
  toast('工作台已就绪', '欢迎使用 CosMac Star')
}
function onOnboardingSkip() { /* 跳过即可，已标记 onboarded */ }

// 持有 onUpdate 的解绑函数：登出/卸载时调用，避免重复登录累积监听器、同一更新触发多次。
let stopUpdates: (() => void) | null = null
// 同上：typing 监听的解绑函数。
let stopTyping: (() => void) | null = null
// typing 信号变化 → 重算中枢 AI 是否在输入；刚开始输入时滚到底，让"正在输入…"可见。
function refreshTyping() {
  const t = aiRoom.value ? roomTyping(aiRoom.value) : false
  if (t && !botTyping.value) nextTick(scrollAiToBottom)
  botTyping.value = t
}

// 实时自动接受频道邀请:邀请可能在**在线期间**到达(AI 拉人),不能只在登录那一刻查一次——
// 否则被邀成员必须重新登录才能进群。refresh 由 sync 驱动,邀请一到就会走到这里。
// 防重入:join 是网络调用,sync 密集触发时别叠加并发。
let acceptingInvites = false
function maybeAcceptInvites() {
  if (acceptingInvites) return
  acceptingInvites = true
  acceptPendingInvites()
    .then((n) => { if (n > 0) refresh() })   // 有新入群 → 刷新列表让频道立即出现
    .catch(() => {})
    .finally(() => { acceptingInvites = false })
}

async function afterLogin(uid: string) {
  me.value = uid
  loggedIn.value = true
  // M12：会话已就绪，按当前账号回填在线状态（从 account data）——setup 时 session 还没好、
  // 回填不了，不在这里补一次的话刷新后状态点会错显示成"在线"。
  refreshMyIdentity()
  addingAccount.value = false   // 加账号流程结束（若是）
  board.value = true // 登录后第一屏 = 数据看板
  tasks.value = false
  // 新私信通知的种子重置:换账号重新登录时,别把新账号的存量私信当"新私信"轰炸一遍
  dmSeeded = false
  seenDmIds.clear()
  if (stopUpdates) stopUpdates()   // 若是重新登录，先解绑上一次的
  stopUpdates = onUpdate(refresh)
  // L7 兜底：若 3.2s 内 sync 事件没再触发 refresh（如零房间账号、深链到不存在的频道），
  // 主动补一次，确保首屏还原一定发生、URL 同步不会永久锁死。
  setTimeout(() => { if (!urlRestored) refresh() }, 3200)
  if (stopTyping) stopTyping()
  stopTyping = onTyping(refreshTyping)
  try {
    aiRoom.value = await ensureBotDm()
  } catch (e) {
    /* 没建成私聊也不影响频道功能 */
  }
  // 探测当前账号是不是服务器管理员：是才显示「管理后台」入口（非管理员连按钮都看不到）。
  // CORS 已通，探测能正常返回；失败/非管理员一律按"不显示"处理。
  isServerAdmin().then((ok) => {
    isAdmin.value = ok
    // 管理员：登录时接受控制室邀请并加入，才拿到"亲自写 AI 配置/门控"的资格
    // （否则光被邀请发不了 state event，权限会比所有者差一点）。幂等、失败静默。
    if (ok) ensureControlRoomMembership()
  }).catch(() => { isAdmin.value = false })
  // 自动接受待接受的频道邀请(登录时清一次存量;在线期间的实时邀请由 refresh 里的
  // maybeAcceptInvites 处理,修 bug 9/10/11)。
  maybeAcceptInvites()
  loadStats() // 数据看板真实指标（best-effort）
  // 插件商城:恢复本人装过的插件到右侧栏(存 account data)。sync 首包可能还没带回
  // account data,3.5s 后再补一次(restore 幂等,多调无害)。
  restorePlugins()
  setTimeout(restorePlugins, 3500)
  refresh()
  // 若是从"社区服务器邀请链接"进来的，登录后执行加入
  if (pendingJoinSpace) { const sid = pendingJoinSpace; pendingJoinSpace = ''; doJoinSpace(sid) }
}

// ── 社区服务器：凭邀请链接加入 ──
let pendingJoinSpace = ''            // 未登录时先记下要加入的 Space，登录后再执行
const joinAttempted = new Set<string>()  // 防同一链接重复加入
async function doJoinSpace(spaceId: string) {
  if (!spaceId || joinAttempted.has(spaceId)) return
  joinAttempted.add(spaceId)
  toast('加入中…', '正在加入社区服务器')
  const ok = await joinSpaceByLink(spaceId)
  if (!ok) {
    toast('加入失败', '这个服务器可能未开放加入或链接失效')
    router.replace('/').catch(() => {})
    return
  }
  setTimeout(() => {
    refresh()
    selectSpace(spaceId)   // 切到刚加入的服务器
    toast('已加入 🎉', '欢迎加入')
  }, 800)
}

// (旧内嵌登录/注册/找回代码已删除:认证已迁移到独立的 AuthView 页面。
//  旧代码保活着「直连 Synapse 登录」「不带人机验证的发码」两条已被收口的路径,留着有被误接回的风险。)

// ── Discord 化：反应 / 回复 / 消息分组 ──
import type { ReactionAgg } from '@/matrix/client'
const reactions = ref<Record<string, ReactionAgg[]>>({})
const replyTo = ref<{ id: string; name: string; body: string } | null>(null)
function loadReactions() {
  if (currentRoom.value) reactions.value = listReactions(currentRoom.value)
}
// 消息分组：同一发送者、5 分钟内、非回复 → 折叠头像/名字
const groupedMsgs = computed(() =>
  msgs.value.map((m, i) => {
    const prev = msgs.value[i - 1]
    const showDay = !prev || dayKey(prev.ts) !== dayKey(m.ts)
    // 跨天必定显头像；否则同人+5分钟内+非回复才折叠
    const showHeader = showDay || !prev || prev.sender !== m.sender || m.ts - prev.ts > 5 * 60 * 1000 || !!m.replyToId
    return { ...m, showHeader, showDay }
  }),
)
// emoji 选择器（点工具条表情/反应＋时弹出）
const EMOJIS = ['👍', '❤️', '😂', '😮', '😢', '😡', '🎉', '🔥', '👏', '🙏', '💯', '✅', '😄', '😍', '🤔', '😎', '😅', '🥳', '😭', '👀', '💪', '🚀', '⭐', '💡', '🎬', '🎵', '📌', '🤝', '😬', '🫡', '🤩', '😇']
const emojiPicker = ref<{ msgId: string; x: number; y: number } | null>(null)
function openEmojiPicker(msgId: string, e: MouseEvent) {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  emojiPicker.value = { msgId, x: Math.min(r.left, window.innerWidth - 250), y: r.bottom + 4 }
}
function pickEmoji(key: string) {
  if (emojiPicker.value) quickReact(emojiPicker.value.msgId, key)
  emojiPicker.value = null
}
// 编辑自己的消息
const editingId = ref<string | null>(null)
function startEdit(m: { id: string; body: string }) {
  editingId.value = m.id
  replyTo.value = null
  draft.value = m.body
  nextTick(() => taRef.value?.focus())
}
function cancelEdit() { editingId.value = null; draft.value = '' }
async function copyMsg(body: string) {
  try { await navigator.clipboard.writeText(body); toast('已复制') } catch { toast('复制失败') }
}
async function toggleReaction(msgId: string, key: string) {
  if (!currentRoom.value) return
  const mine = reactions.value[msgId]?.find((r) => r.key === key && r.mine)
  try {
    if (mine?.myId) await unreact(currentRoom.value, mine.myId)
    else await react(currentRoom.value, msgId, key)
    setTimeout(loadReactions, 500)
  } catch (e: any) { toast('操作失败', e?.message || String(e)) }
}
async function quickReact(msgId: string, key: string) {
  if (!currentRoom.value) return
  // 已经有我的同款反应 → 取消，否则添加
  const mine = reactions.value[msgId]?.find((r) => r.key === key && r.mine)
  try {
    if (mine?.myId) await unreact(currentRoom.value, mine.myId)
    else await react(currentRoom.value, msgId, key)
    setTimeout(loadReactions, 500)
  } catch (e: any) { toast('操作失败', e?.message || String(e)) }
}
function startReply(m: { id: string; senderName: string; body: string }) {
  replyTo.value = { id: m.id, name: m.senderName, body: m.body }
  nextTick(() => taRef.value?.focus())
}
function cancelReply() { replyTo.value = null }

// 当前频道的真实成员（频道头显示数量+头像）
const channelMembers = ref<{ id: string; name: string; isBot: boolean; pending?: boolean }[]>([])
function openRoom(id: string) {
  board.value = false
  tasks.value = false
  docs.value = false
  org.value = false
  currentRoom.value = id
  msgs.value = listMessages(id)
  channelMembers.value = listRoomMembers(id)
  fav.value = isFavourite(id)
  checkDmDeliverability(id)
  reactions.value = listReactions(id)
  replyTo.value = null
  editingId.value = null
  // 被邀请的房(别人发起的私信/群邀请)点开即自动接受——否则读不到历史也发不了消息。
  // join 完成后 sync 会补历史,稍等再刷一次消息区。
  acceptRoomInvite(id).then(() => {
    if (currentRoom.value !== id) return
    setTimeout(() => {
      if (currentRoom.value !== id) return
      msgs.value = listMessages(id)
      channelMembers.value = listRoomMembers(id)
      markRoomRead(id).then(refreshDms)  // 补历史后再标已读+刷未读徽章
    }, 600)
  })
  // 打开即标记已读(发已读回执 → 清未读徽章),并刷新私信列表
  markRoomRead(id).then(refreshDms)
}
// 当前打开的房是不是"真人私信":私信头部不显示 频道设置/私密角标/成员管理(那是频道的东西)
const currentIsDm = computed(() => (currentRoom.value ? isDirectRoom(currentRoom.value) : false))

// ── 私信"送不达"提醒：对方被停用/退出后 Synapse 把他移出房,消息发出去没人收 ──
const dmUndeliverable = ref<{ show: boolean; deactivated: boolean }>({ show: false, deactivated: false })
async function checkDmDeliverability(id: string) {
  dmUndeliverable.value = { show: false, deactivated: false }
  try {
    if (!isDirectRoom(id)) return
    const { peerId, joined, pending } = dmPeerStatus(id)
    // 在场(joined) 或 刚发起待对方接受(pending=invite) → 都正常，不提醒（M10：invite 不是送不达）
    if (!peerId || joined || pending) return
    // 对方不在场:先标记提醒,再异步确认是不是"已停用"(决定措辞),避免误报
    dmUndeliverable.value = { show: true, deactivated: false }
    const deactivated = await checkUserDeactivated(peerId)
    if (currentRoom.value === id) dmUndeliverable.value = { show: true, deactivated }
  } catch { /* 探测失败就不提醒,不打扰 */ }
}
// 收藏当前频道（真实 Matrix m.favourite 标签，按频道独立、跨设备同步）
async function toggleFav() {
  const id = currentRoom.value
  if (!id) return
  const next = !fav.value
  fav.value = next
  // 乐观更新左栏分组:直接改 rooms 里该频道的 fav,让它即时进/出「收藏」组——别等 setRoomTag 的
  // sync 回声(回声到达前 room.tags 还是旧的,refresh() 会读到旧值、频道不动)。
  const r = rooms.value.find((x) => x.id === id)
  const prevFav = r?.fav
  if (r) r.fav = next
  // 私信同理(负责人报"私信收藏无效"):乐观改 dms 条目并按 收藏优先 重排,联系人即时置顶
  const d = dms.value.find((x) => x.id === id)
  const prevDmFav = d?.fav
  if (d) {
    d.fav = next || undefined
    dms.value = [...dms.value].sort((a, b) => Number(!!b.fav) - Number(!!a.fav))
  }
  try {
    await setFavourite(id, next)
  } catch (e: any) {
    fav.value = !next
    if (r) r.fav = prevFav   // 失败回滚
    if (d) { d.fav = prevDmFav; refreshDms() }
    toast('收藏失败', e?.message || String(e))
  }
}

async function send() {
  const t = draft.value.trim()
  if (!t || !currentRoom.value) return
  const room = currentRoom.value
  const rep = replyTo.value
  const ed = editingId.value
  // 乐观清空输入/回复/编辑态；M13：发送失败要回填草稿+恢复状态，绝不让用户打的内容凭空消失。
  draft.value = ''
  replyTo.value = null
  editingId.value = null
  try {
    if (ed) await editMessage(room, ed, t)
    else if (rep) await sendReply(room, t, rep.id)
    else await sendText(room, t)
    setTimeout(refresh, 400)
  } catch (err: any) {
    draft.value = t                      // 回填草稿
    if (rep) replyTo.value = rep         // 恢复回复目标，方便直接重试
    if (ed) editingId.value = ed         // 恢复编辑态
    toast('发送失败', err?.message || '消息没能发出去，请重试')
  }
}

// 「我的AI工坊」(自建智能体/技能)弹窗
const myStudioOpen = ref(false)

// ── 附件/图片上传 ──
const fileInputRef = ref<HTMLInputElement>()   // 隐藏的文件选择框
const uploading = ref(false)
// 上限：图片/文件都限到 50MB，超了本地先拦（Synapse 默认也有上限，本地拦提示更友好）
const MAX_UPLOAD = 50 * 1024 * 1024
function pickAttachment() { if (!uploading.value) fileInputRef.value?.click() }
async function onAttachmentPicked(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''   // 清空，允许连续选同一个文件再次触发 change
  if (!files.length || !currentRoom.value) return
  uploading.value = true
  try {
    for (const f of files) {
      if (f.size > MAX_UPLOAD) { toast('文件过大', `${f.name} 超过 50MB，未发送`); continue }
      // 存储空间配额(账号权益):超限就别传了,给明确的升级/清理提示
      const st = await storageCheck(f.size)
      if (!st.ok) { toast('存储空间不足', st.error || `${f.name} 未发送,请清理或升级会员`); continue }
      // 按 MIME 判断走图片还是文件：图片进画廊式缩略图，其余当附件下载卡片
      if (f.type.startsWith('image/')) await sendImageFile(currentRoom.value, f)
      else await sendFileAttachment(currentRoom.value, f)
    }
    setTimeout(refresh, 400)
  } catch (err: any) {
    toast('上传失败', err?.message || String(err))
  } finally {
    uploading.value = false
  }
}

async function aiSend() {
  const t = aiDraft.value.trim()
  if (!t || !aiRoom.value) return
  const room = aiRoom.value
  aiDraft.value = ''
  // 捎上当前工作区：中枢 AI 是全局 DM，带上它才能基于「当前工作区的文档」做 RAG 答疑。
  // 再捎「当前所在频道」(频道感知):全局会话横跨多频道话题,bot 据此在历史里分段标注
  // + 告诫模型别把上一频道的规则/约束带进当前频道(负责人报的串扰问题)。看板态不带。
  const extra: Record<string, any> = {}
  if (activeSpace.value) extra['cosmac.doc_space'] = activeSpace.value
  if (currentRoom.value && currentName.value) {
    extra['cosmac.active_room'] = currentRoom.value
    extra['cosmac.active_room_name'] = currentName.value
  }
  try {
    await sendText(room, t, Object.keys(extra).length ? extra : undefined)
    setTimeout(refresh, 400)
  } catch (err: any) {
    aiDraft.value = t   // M13：发送失败回填草稿，别丢用户输入
    toast('发送失败', err?.message || '消息没能发出去，请重试')
    return
  }
}

// 选择卡点选：把用户选的内容作为普通消息发回该房间，主 AI 据此继续（同打字效果）
async function pickChoice(text: string, room: string) {
  const t = (text || '').trim()
  if (!t || !room) return
  await sendText(room, t)
  setTimeout(refresh, 400)
}

// bot 建专班 → 发 team_created 信号卡 → 客户端把新专班挂进当前工作区（bot 无权限写 m.space.child）。
// linkedTeams 去重，避免每次 refresh 重复挂接。
const linkedTeams = new Set<string>()
async function processTeamCards() {
  if (!activeSpace.value) return
  for (const m of aiMsgs.value) {
    const c = (m as any).card
    if (c?.kind !== 'team_created' || !c.team_room) continue
    if (linkedTeams.has(c.team_room)) continue
    linkedTeams.add(c.team_room)
    // 已在工作区里就别重复挂
    if (spaceChildIds.value.has(c.team_room)) continue
    const ok = await linkRoomToSpace(activeSpace.value, c.team_room)
    if (ok) setTimeout(refresh, 300)  // 挂上后刷新，频道树立刻出现新专班
  }
}
// 点「进入专班」按钮：确保挂好并打开
async function enterTeam(roomId: string) {
  if (activeSpace.value && !spaceChildIds.value.has(roomId)) {
    await linkRoomToSpace(activeSpace.value, roomId)
    refresh()
  }
  openRoom(roomId)
}

async function doLogout() {
  await logout()
  // 清掉用户专属的本机数据（自定义 Agent/技能），再整页 reload。
  // reload 是关键：很多 composable 用模块级单例状态(CLI 历史/频道配置/插件…)，不 reload
  // 的话共享浏览器上「登出→换人登录」会让下一个人看到上一个人的数据。reload 一次全清干净。
  clearCustomAssetsStorage()
  userMenuOpen.value = false
  window.location.reload()
}

function openAiPanel() {
  aiOpen.value = true
}

/** 私信分组里的「中枢 AI」:直接打开**放大版**主 AI 界面(负责人要求)——
 *  Cowork 式全屏弹窗(左会话列表+中对话+右进度/文件),而不是右侧小面板。 */
function openAiMax() {
  aiOpen.value = true
  aiMax.value = true
}

function initials(name: string) {
  return name.replace(/^@/, '').slice(0, 1).toUpperCase()
}
function isMe(s: string) {
  return s === me.value
}

// ── Composer Markdown 工具条（在 draft 文本上真实生效）────
function wrap(before: string, after: string, placeholder: string) {
  const ta = taRef.value
  if (!ta) return
  const start = ta.selectionStart
  const end = ta.selectionEnd
  const value = draft.value
  const inner = value.slice(start, end) || placeholder
  draft.value = value.slice(0, start) + before + inner + after + value.slice(end)
  const innerStart = start + before.length
  const innerEnd = innerStart + inner.length
  nextTick(() => {
    ta.focus()
    ta.setSelectionRange(innerStart, innerEnd)
  })
}
function prefixLine(prefix: string) {
  const ta = taRef.value
  if (!ta) return
  const start = ta.selectionStart
  const value = draft.value
  const lineStart = value.lastIndexOf('\n', start - 1) + 1
  draft.value = value.slice(0, lineStart) + prefix + value.slice(lineStart)
  const caret = start + prefix.length
  nextTick(() => {
    ta.focus()
    ta.setSelectionRange(caret, caret)
  })
}
function insertText(s: string) {
  const ta = taRef.value
  if (!ta) return
  const start = ta.selectionStart
  const value = draft.value
  draft.value = value.slice(0, start) + s + value.slice(ta.selectionEnd)
  const caret = start + s.length
  nextTick(() => {
    ta.focus()
    ta.setSelectionRange(caret, caret)
  })
}
const tb = reactive({
  bold: () => wrap('**', '**', '加粗文字'),
  italic: () => wrap('*', '*', '斜体文字'),
  strike: () => wrap('~~', '~~', '删除线文字'),
  heading: () => prefixLine('## '),
  link: () => wrap('[', '](url)', '链接文字'),
  code: () => wrap('`', '`', '代码'),
  quote: () => prefixLine('> '),
  ul: () => prefixLine('- '),
  // 插入 @ 并立刻弹出候选(成员+本频道 AI Agent),与手打 @ 同一套补全
  at: () => { insertText('@'); nextTick(detectMention) },
})

/* ── @ 补全：输入框打 @ 弹出「频道成员 + AI Agent」候选 ──────────────
 * 候选四类:频道成员(真人/主AI) / 本频道绑定的协作 Agent(专班 worker) /
 * 我自建的智能体 / 我商城已获取的智能体。后三类 bot 侧已支持 @名字 路由应答
 * (档3b + _agent_mention_hit),这里补前端入口——负责人需求:拆完任务 Agent
 * 进了频道,用户在输入框 @ 时要能看到并选中它们。
 * 选中插入「@名字 」纯文本(worker/自建/已获取按名字路由;真人靠渲染层染色)。 */
interface MentionCand { key: string; label: string; sub: string; isAgent: boolean }
const mentionOpen = ref(false)
const mentionQuery = ref('')
const mentionIdx = ref(0)
const mentionStart = ref(-1)              // draft 里触发这次补全的 @ 位置
const mentionPool = ref<MentionCand[]>([])   // 本频道的完整候选池(懒构建,切频道失效)
const mentionPoolRoom = ref('')              // 候选池对应的频道(失效判定)
let marketAgentNames: Map<string, string> | null = null // slug→名字(商城目录,会话级缓存)

/** 构建本频道候选池(首次触发 @ 时拉一次;失败只影响该类候选,绝不阻断输入)。 */
async function buildMentionPool() {
  const room = currentRoom.value
  const pool: MentionCand[] = []
  const seenAgent = new Set<string>()
  // ① 频道成员(真人 + 主 AI + AI 同事傀儡账号)。傀儡按 slug 记入 seenAgent——
  // 它们同时还会出现在下面 ② 的 agentSlugs 里,不去重会在候选里出现两次。
  for (const m of channelMembers.value) {
    if (m.pending) continue
    const slug = aiWorkerSlug(m.id)
    if (slug) {
      if (seenAgent.has(slug)) continue
      seenAgent.add(slug)
      pool.push({ key: 'a:' + slug, label: m.name, sub: '本频道 AI', isAgent: true })
      continue
    }
    pool.push({ key: 'u:' + m.id, label: m.name, sub: m.isBot ? '主 AI' : '成员', isAgent: !!m.isBot })
  }
  // slug→名字 映射(本频道 worker 与已获取都要用;目录仅拉一次)
  if (!marketAgentNames) {
    try {
      const cat = await fetchMarketCatalog()
      marketAgentNames = new Map(
        (cat?.items || []).filter((i) => i.kind === 'agent').map((i) => [i.slug, i.name]),
      )
    } catch { marketAgentNames = null }
  }
  // ② 本频道绑定的协作 Agent(专班 worker,建专班时写进 channel_config.agentSlugs)
  try {
    for (const s of (getChannelConfig(room)?.agentSlugs || []) as string[]) {
      if (!s || seenAgent.has(s)) continue
      seenAgent.add(s)
      pool.push({ key: 'a:' + s, label: marketAgentNames?.get(s) || s, sub: '本频道 AI', isAgent: true })
    }
  } catch { /* 读不到配置就没有这一类 */ }
  // ③ 我自建的智能体(任意频道点名即应答)
  try {
    for (const a of await myAgentsList()) {
      if (seenAgent.has(a.slug)) continue
      seenAgent.add(a.slug)
      pool.push({ key: 'my:' + a.slug, label: a.name || a.slug, sub: '我的 AI', isAgent: true })
    }
  } catch { /* 未登录/接口失败,略过 */ }
  // ④ 我商城已获取的智能体(任意频道 @点名即应答)
  try {
    for (const g of (await fetchMarketAcquired()) || []) {
      if (g.kind !== 'agent' || g.stale || seenAgent.has(g.slug)) continue
      seenAgent.add(g.slug)
      pool.push({ key: 'got:' + g.slug, label: g.name || g.slug, sub: '已获取', isAgent: true })
    }
  } catch { /* 同上 */ }
  mentionPool.value = pool
  mentionPoolRoom.value = room
}

/** 过滤后的候选(名字/来源包含关键字,最多 8 条;查询为空列全部)。 */
const mentionList = computed(() => {
  const q = mentionQuery.value.trim().toLowerCase()
  const hit = q
    ? mentionPool.value.filter((c) => c.label.toLowerCase().includes(q) || c.key.slice(c.key.indexOf(':') + 1).toLowerCase().includes(q))
    : mentionPool.value
  // 上限 30(面板自身可滚动):此前 8 条把成员多的频道里后面的 AI 同事整个截掉了
  // (负责人实测:@ 列表里少了社媒运营/数据分析,滑到底也没有)
  return hit.slice(0, 30)
})

/** 检测光标前是否正在打「@关键字」,是则打开/刷新补全面板。 */
async function detectMention() {
  const ta = taRef.value
  if (!ta || !currentRoom.value) { mentionOpen.value = false; return }
  const upto = draft.value.slice(0, ta.selectionStart)
  const at = upto.lastIndexOf('@')
  // @ 必须存在,且其前面是行首/空白/常见标点(避免邮箱等误触发)
  if (at < 0 || (at > 0 && !/[\s(（,，:：、]/.test(upto[at - 1]))) { mentionOpen.value = false; return }
  const q = upto.slice(at + 1)
  // @ 后已出现空白(点名已完成)或太长 → 不再补全
  if (/\s/.test(q) || q.length > 24) { mentionOpen.value = false; return }
  if (mentionPoolRoom.value !== currentRoom.value) await buildMentionPool()
  mentionStart.value = at
  mentionQuery.value = q
  mentionIdx.value = 0
  mentionOpen.value = mentionList.value.length > 0
}

/** 选中一条候选:把「@关键字」替换成「@名字 」,光标停在其后。 */
function pickMention(c: MentionCand) {
  const ta = taRef.value
  if (!ta) return
  const insert = '@' + c.label + ' '
  const tail = draft.value.slice(ta.selectionStart)
  draft.value = draft.value.slice(0, mentionStart.value) + insert + tail
  mentionOpen.value = false
  const caret = mentionStart.value + insert.length
  nextTick(() => { ta.focus(); ta.setSelectionRange(caret, caret) })
}

/** 输入框统一按键处理:补全面板打开时接管 ↑↓/Enter/Tab/Esc,否则维持原行为。 */
function onComposerKeydown(e: KeyboardEvent) {
  // 输入法组字中(isComposing)的按键一律不拦(评审#6):中文用户按 Enter 确认拼音候选时,
  // 若被下面的 mention 选中分支劫持,未上屏的组字会被吞掉换成 @候选。
  if (mentionOpen.value && !e.isComposing) {
    if (e.key === 'ArrowDown') { e.preventDefault(); mentionIdx.value = (mentionIdx.value + 1) % mentionList.value.length; return }
    if (e.key === 'ArrowUp') { e.preventDefault(); mentionIdx.value = (mentionIdx.value - 1 + mentionList.value.length) % mentionList.value.length; return }
    if (e.key === 'Enter' || e.key === 'Tab') {
      const c = mentionList.value[mentionIdx.value]
      if (c) { e.preventDefault(); pickMention(c); return }
    }
    if (e.key === 'Escape') { e.preventDefault(); mentionOpen.value = false; return }
  }
  if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && !e.isComposing) {
    e.preventDefault(); send(); return
  }
  if (e.key === 'Escape') { editingId.value ? cancelEdit() : cancelReply() }
}

// ── 顶栏按钮 / 应用切换 / 工作区工具 ──────────────────
// 升级会员弹窗（模块4 交易系统 · 用户侧）
const showMembership = ref(false)
function onUpgrade() { showMembership.value = true }
// 打开对应弹窗/面板（真实功能）
function onSettings(tab?: UserSettingsTab) { openSettings(tab); userMenuOpen.value = false }
function onMarket() { openMarket(); appMenuOpen.value = false }
function onCli() { openCli(); appMenuOpen.value = false }
function onProfile() { openProfileHome(); appMenuOpen.value = false; userMenuOpen.value = false }
function onPluginStore() { openPluginStore() }
function onCustomAssets() { openAssets() }
function onFilter() { filterInput.value?.focus() }

function onDocClick(e: MouseEvent) {
  if (!rootEl.value) return
  if (!(e.target as HTMLElement)?.closest?.('.tas-wrap')) appMenuOpen.value = false
  if (!(e.target as HTMLElement)?.closest?.('.um-wrap')) userMenuOpen.value = false
  if (!(e.target as HTMLElement)?.closest?.('.emoji-pop, .msg-tools, .rxn.add')) emojiPicker.value = null
}

/* ===== URL 路由同步 =====================================================
 * LiveView 是根组件、整页由它渲染，不走 <router-view>。这里把"内部导航状态"
 * 与浏览器地址(hash)做双向同步，让每个视图有独立地址、支持后退/前进/刷新/深链：
 *   · 状态变 → 写地址(push，浏览器后退可用)
 *   · 地址变(后退/前进/手改/深链) → 还原状态
 * 地址方案：/admin、/s/:space/board、/s/:space/tasks、/s/:space/c/:roomId
 * 不改任何点击 handler——所有导航本就收敛在 selectSpace/openBoard/openTasks/
 * openRoom + adminOpen 上，这里统一监听它们。
 */
const route = useRoute()
const router = useRouter()
let applyingFromRoute = false // 正在"按地址还原状态"，期间不回写地址（防死循环）
let syncReady = false         // 首屏还原完成后才开始"状态→地址"
let urlRestored = false       // 首屏只按地址还原一次（见 refresh）
let restoreDeadline = 0       // L7：首屏还原兜底期限——零房间账号也不至于永久等房间列表而锁死 URL 同步

/** 由当前导航状态算出对应地址 */
function computePath(): string {
  if (adminOpen.value) return '/admin'
  if (profileVisible.value) return '/me'
  const s = activeSpace.value
  if (!s) return '/'
  if (currentRoom.value) return `/s/${encodeURIComponent(s)}/c/${encodeURIComponent(currentRoom.value)}`
  if (tasks.value) return `/s/${encodeURIComponent(s)}/tasks`
  if (docs.value) return `/s/${encodeURIComponent(s)}/docs`
  if (org.value) return `/s/${encodeURIComponent(s)}/org`
  return `/s/${encodeURIComponent(s)}/board`
}

/** 按当前地址还原内部导航状态（后退/前进/深链/刷新时调用） */
function applyFromRoute() {
  // 社区服务器邀请链接 /join/:space（会话内点开/粘贴）：已登录直接加入，未登录先记下。
  const jm = route.path.match(/^\/join\/(.+)$/)
  if (jm) {
    const sid = decodeURIComponent(jm[1])
    if (loggedIn.value) doJoinSpace(sid)
    else pendingJoinSpace = sid
    return
  }
  applyingFromRoute = true
  try {
    const p = route.path
    // 两个全屏覆盖层先按地址决定开关（互斥）
    adminOpen.value = p.startsWith('/admin')
    profileVisible.value = p.startsWith('/me')
    if (adminOpen.value || profileVisible.value) return
    // 匹配 /s/:space、/s/:space/board、/s/:space/tasks、/s/:space/docs、/s/:space/c/:roomId
    const m = p.match(/^\/s\/([^/]+)(?:\/(board|tasks|docs|org)|\/c\/(.+))?$/)
    if (!m) return // 根路径或无法识别 → 保持现状
    const space = decodeURIComponent(m[1])
    if (space && spaces.value.some((s) => s.id === space)) {
      activeSpace.value = space
      spaceChildIds.value = roomIdsInSpace(space)
    }
    const roomId = m[3] ? decodeURIComponent(m[3]) : ''
    if (roomId) {
      // 房间还没加载到 / 不存在 → 退回数据看板，避免空白。
      // M11：私信(DM)不在 rooms.value 里(listRooms 排除了 DM)，必须同时查 dms.value，否则
      // 刷新/深链打开私信会因"找不到"落回看板。openRoom 对 DM 同样适用(会自动接受邀请+读历史)。
      if (rooms.value.some((r) => r.id === roomId) || dms.value.some((d) => d.id === roomId)) {
        openRoom(roomId)
      }
      else { board.value = true; tasks.value = false; docs.value = false; org.value = false; currentRoom.value = '' }
    } else if (m[2] === 'tasks') {
      tasks.value = true; board.value = false; docs.value = false; org.value = false; currentRoom.value = ''
    } else if (m[2] === 'docs') {
      openDocs()
    } else if (m[2] === 'org') {
      openOrg()
    } else {
      board.value = true; tasks.value = false; docs.value = false; org.value = false; currentRoom.value = ''
    }
  } finally {
    applyingFromRoute = false
  }
}

// 状态 → 地址：用 push 让浏览器后退可用
watch([activeSpace, board, tasks, docs, org, currentRoom, adminOpen, profileVisible], () => {
  if (!syncReady || applyingFromRoute) return
  const path = computePath()
  if (route.path !== path) router.push(path).catch(() => {})
})

// 地址 → 状态：仅当地址与当前状态不一致（真正的后退/前进/手改地址）才还原
watch(() => route.path, (p) => {
  if (!syncReady) return
  if (p === computePath()) return
  applyFromRoute()
})

onMounted(async () => {
  document.addEventListener('click', onDocClick)
  hideRightPanel()  // 「关于此频道」面板在真实客户端默认收起，由频道头 ℹ 按钮开关
  // 全局会话失效监听:账号被停用/token 被吊销时(运行中),弹明确提示并送回登录页——
  // 否则所有功能静默 401,用户只觉得"按钮都点不动了"(线上实测:停用后点任务「开始」无反应)。
  onSessionExpired((reason) => {
    toast('登录已失效', reason === 'M_USER_DEACTIVATED'
      ? '你的账号已被停用，请联系管理员。即将返回登录页…'
      : '请重新登录（账号可能已被停用或在别处退出）。即将返回登录页…')
    setTimeout(() => window.location.reload(), 2200)  // reload 后无会话 → 自动落到登录页
  })
  loading.value = true
  // 冷启动若是 /join/:space 邀请链接：先记下目标，登录/恢复会话后 afterLogin 里执行加入。
  const jm = route.path.match(/^\/join\/(.+)$/)
  if (jm) pendingJoinSpace = decodeURIComponent(jm[1])
  try {
    const uid = await restoreSession()
    if (uid) await afterLogin(uid)
    // 无有效会话 → 回登录页,带上当前地址;登录成功后 proceed() 送回原深链(审查 bug#12)
    else router.push({ path: '/login', query: { redirect: route.fullPath } })
  } finally {
    loading.value = false
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  if (stopUpdates) { stopUpdates(); stopUpdates = null }
  if (stopTyping) { stopTyping(); stopTyping = null }
})
</script>

<template>
  <!-- 认证已抽到独立 /login 页(AuthView)。这里只渲染已登录的主应用;
       restoreSession 未完成时先占位,避免空白/闪登录框(无会话时 onMounted 会跳 /login)。 -->
  <div v-if="!loggedIn" class="live-splash">载入中…</div>

  <!-- ════════════════ 驾驶舱 ════════════════ -->
  <div v-else ref="rootEl" class="shell">
    <!-- ───────── 顶栏 ───────── -->
    <header class="topbar">
      <!-- 左：品牌 / 九宫格应用切换器 -->
      <div class="tas-wrap">
        <button class="top-brand-btn" :class="{ open: appMenuOpen }" @click.stop="appMenuOpen = !appMenuOpen">
          <svg class="apps-ic" width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
            <circle cx="3" cy="3" r="1.6" /><circle cx="9" cy="3" r="1.6" /><circle cx="15" cy="3" r="1.6" />
            <circle cx="3" cy="9" r="1.6" /><circle cx="9" cy="9" r="1.6" /><circle cx="15" cy="9" r="1.6" />
            <circle cx="3" cy="15" r="1.6" /><circle cx="9" cy="15" r="1.6" /><circle cx="15" cy="15" r="1.6" />
          </svg>
          <img :src="logoUrl" alt="" class="logo" />
          <span class="product-name">CosMac Star<span class="product-x">X</span>{{ activeSpaceName }}</span>
        </button>
        <div v-if="appMenuOpen" class="tas-pop" @click.stop>
          <button class="tas-item active"><span class="tas-ic">💬</span><span class="tas-label">频道</span><span class="tas-check">✓</span></button>
          <div class="tas-sep" />
          <button class="tas-item" @click="onMarket"><span class="tas-ic">🛒</span><span class="tas-label">AI Agent 商城</span></button>
          <button class="tas-item" @click="onCli"><span class="tas-ic">▸</span><span class="tas-label">CLI</span></button>
          <button class="tas-item" @click="appMenuOpen = false"><span class="tas-ic">▭</span><span class="tas-label">系统控制台</span></button>
          <button class="tas-item" @click="appMenuOpen = false"><span class="tas-ic">🧩</span><span class="tas-label">集成</span></button>
          <div class="tas-sep" />
          <button class="tas-item" @click="onProfile"><span class="tas-ic">🏠</span><span class="tas-label">个人主页</span></button>
        </div>
      </div>

      <!-- 中：留空（原演示版"全局搜索"未接后端，已移除；频道检索走左侧栏「查找频道」）-->
      <div class="top-mid"></div>

      <!-- 右：升级 / 设置 / 中枢AI开关 / 用户菜单 -->
      <div class="top-right">
        <button class="top-upgrade" @click="onUpgrade">✦ 升级会员 ✦</button>
        <button class="ic-btn" title="设置" @click="onSettings()">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
        </button>
        <button class="ic-btn ai-toggle" :class="{ active: aiOpen }" :title="aiOpen ? '收起中枢 AI' : '展开中枢 AI'" @click="aiOpen = !aiOpen">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.9 5.6L19.5 9.5 13.9 11.4 12 17l-1.9-5.6L4.5 9.5l5.6-1.9L12 2z" /></svg>
        </button>
        <div class="um-wrap">
          <button class="user-chip" :class="{ open: userMenuOpen }" @click.stop="toggleUserMenu">
            <span class="avatar">{{ initials(me) }}</span>
            <span class="online-dot" :style="{ background: myStatusMeta.color }" :title="myStatus" />
          </button>
          <div v-if="userMenuOpen" class="um-pop" @click.stop>
            <div class="um-head">
              <span class="um-ava">{{ initials(me) }}</span>
              <div class="um-id">
                <div class="um-name">{{ me }}</div>
                <div class="um-handle">已连接 {{ HS }} · <span class="um-online" :style="{ color: myStatusMeta.color }">{{ myStatus }}</span></div>
              </div>
            </div>
            <div class="um-sep" />
            <button class="um-item" @click="onSettings('profile')"><span class="um-ic">👤</span>个人资料</button>
            <button class="um-item" @click="openMyPeople(); userMenuOpen = false"><span class="um-ic">🧑‍🤝‍🧑</span>我的协作人</button>
            <button class="um-item" @click="myStudioOpen = true; userMenuOpen = false"><span class="um-ic">🎭</span>我的AI工坊</button>
            <button class="um-item" @click="openMyUsage(); userMenuOpen = false"><span class="um-ic">📈</span>我的额度</button>
            <button class="um-item" @click="onSettings('perms')"><span class="um-ic">🔒</span>我的权限</button>
            <button class="um-item" @click="onSettings('share')"><span class="um-ic">🔔</span>数据调用授权</button>
            <!-- 管理后台入口：仅服务器管理员可见（isAdmin 探测为真）-->
            <template v-if="isAdmin">
              <div class="um-sep" />
              <button class="um-item" @click="adminOpen = true; userMenuOpen = false"><span class="um-ic">⚙</span>管理后台</button>
            </template>
            <!-- 切换账号（缓存的其它账号，免密切换）+ 添加账号 -->
            <div class="um-sep" />
            <div class="um-label">切换账号</div>
            <button v-for="a in cachedAccounts" :key="a.userId" class="um-item um-acct" @click="switchAccount(a.userId)">
              <span class="um-acct-ava">{{ initials(a.name) }}</span>
              <span class="um-acct-name">{{ a.name }}</span>
            </button>
            <button class="um-item" @click="startAddAccount"><span class="um-ic">＋</span>添加账号</button>
            <div class="um-sep" />
            <button class="um-item danger" @click="doLogout"><span class="um-ic">⎋</span>退出登录</button>
          </div>
        </div>
      </div>
    </header>

    <!-- ───────── 主体（浮卡式三栏 + 两侧竖栏）───────── -->
    <div class="body" :class="{ focused }">
      <!-- 最左：工作区竖栏 -->
      <nav v-if="!focused" class="ws-rail">
        <div
          v-for="s in spaces"
          :key="s.id"
          class="ws-icon"
          :class="{ active: s.id === activeSpace, 'has-img': !!s.avatarUrl }"
          :title="s.name"
          @click="selectSpace(s.id)"
        >
          <img v-if="s.avatarUrl" :src="s.avatarUrl" alt="" class="ws-img" />
          <template v-else>{{ s.label || wsLabel(s.name) }}</template>
        </div>
        <div class="ws-icon plus" title="新建工作区" @click="openNewWorkspace">+</div>
        <div class="ws-sep" />
        <div class="ws-icon ws-tool" title="AI Agent 商城" @click="onMarket">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z" /><path d="M3 6h18" /><path d="M16 10a4 4 0 0 1-8 0" /></svg>
        </div>
        <div class="ws-icon ws-tool" title="CLI" @click="onCli">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5" /><line x1="12" x2="20" y1="19" y2="19" /></svg>
        </div>
        <div class="ws-icon ws-tool" title="个人主页" @click="onProfile">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg>
        </div>
      </nav>

      <!-- 左：频道侧栏（浮卡）-->
      <aside v-if="!focused" class="channels">
        <div class="cs-ws-head">
          <button class="cs-ws-name" :title="`${activeSpaceName} · 点击设置`" @click="openWsSettings">
            <span class="name">{{ activeSpaceName }}</span>
            <svg class="chev" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
          </button>
          <button class="cs-add" title="添加" @click="openNewChannel">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5v14" /></svg>
          </button>
        </div>

        <div class="cs-filter">
          <button class="cs-filter-funnel" title="筛选" @click="onFilter">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18l-7 9v6l-4-2v-4z" /></svg>
          </button>
          <input ref="filterInput" class="cs-filter-input" v-model="filterText" placeholder="查找频道" />
        </div>

        <div class="cs-list">
          <!-- 置顶：数据看板（影视公司制作驾驶舱）-->
          <div class="cs-item pinned-item" :class="{ active: board }" @click="openBoard">
            <span class="cs-ic">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></svg>
            </span>
            <span class="cs-label">数据看板</span>
          </div>
          <div class="cs-item pinned-item" :class="{ active: tasks }" @click="openTasks">
            <span class="cs-ic">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>
            </span>
            <span class="cs-label">任务看板</span>
          </div>
          <!-- 置顶：图文教程（前台只读·类公众号；编辑在管理后台）-->
          <div class="cs-item pinned-item" :class="{ active: docs }" @click="openDocs">
            <span class="cs-ic">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h8" /></svg>
            </span>
            <span class="cs-label">图文教程</span>
          </div>
          <div class="cs-item pinned-item" :class="{ active: org }" @click="openOrg">
            <span class="cs-ic">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
            </span>
            <span class="cs-label">组织/人事</span>
          </div>

          <!-- 收藏 group（m.favourite 标签的频道置顶；无收藏则整组不显示）-->
          <div v-if="favRooms.length" class="cs-group">
            <button class="cs-group-head" @click="favOpen = !favOpen">
              <svg class="caret" :class="{ open: favOpen }" width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M9 6 15 12 9 18z" /></svg>
              <span>⭐ 收藏</span>
            </button>
            <template v-if="favOpen">
              <div
                v-for="r in favRooms"
                :key="'fav' + r.id"
                class="cs-item ch-row"
                :class="{ active: r.id === currentRoom, archived: isArchived(r.id) }"
                @click="openRoom(r.id)"
              >
                <span class="cs-chan-av" :style="{ background: colorOf(r.name) }">{{ iconChar(r.name) }}</span>
                <span class="cs-label" :title="r.name">{{ r.name }}</span>
                <span v-if="isArchived(r.id)" class="cs-archived-tag" title="专班已归档收尾">🗄</span>
              </div>
            </template>
          </div>

          <!-- 频道 group（真实房间）-->
          <div class="cs-group">
            <button class="cs-group-head" @click="channelsOpen = !channelsOpen">
              <svg class="caret" :class="{ open: channelsOpen }" width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M9 6 15 12 9 18z" /></svg>
              <span>频道</span>
            </button>
            <template v-if="channelsOpen">
              <div
                v-for="r in channelRooms"
                :key="r.id"
                class="cs-item ch-row"
                :class="{ active: r.id === currentRoom, archived: isArchived(r.id) }"
                @click="openRoom(r.id)"
              >
                <span class="cs-chan-av" :style="{ background: colorOf(r.name) }">{{ iconChar(r.name) }}</span>
                <span class="cs-label" :title="r.name">{{ r.name }}</span>
                <span v-if="isArchived(r.id)" class="cs-archived-tag" title="专班已归档收尾">🗄</span>
              </div>
              <p v-if="!channelRooms.length" class="cs-empty">还没有频道</p>
              <div class="cs-item cs-add-row" @click="openNewChannel">
                <span class="cs-ic-box"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5v14" /></svg></span>
                <span class="cs-label">添加频道</span>
              </div>
            </template>
          </div>

          <!-- 未归类 group（不属于任何工作区的孤儿房：AI 建的专班/别人拉我进的群。
               每个工作区下都显示这一组（它们本来就没归属）；点「归入」挂进当前工作区后就只在那里出现。）-->
          <div v-if="orphanRooms.length" class="cs-group">
            <button class="cs-group-head" @click="orphanOpen = !orphanOpen" title="不属于任何工作区的频道；点频道右侧「归入」可挂进当前工作区">
              <svg class="caret" :class="{ open: orphanOpen }" width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M9 6 15 12 9 18z" /></svg>
              <span>未归类</span>
              <span class="cs-orphan-n">{{ orphanRooms.length }}</span>
            </button>
            <template v-if="orphanOpen">
              <div
                v-for="r in orphanRooms"
                :key="r.id"
                class="cs-item ch-row"
                :class="{ active: r.id === currentRoom }"
                @click="openRoom(r.id)"
              >
                <span class="cs-chan-av" :style="{ background: colorOf(r.name) }">{{ iconChar(r.name) }}</span>
                <span class="cs-label" :title="r.name">{{ r.name }}</span>
                <button class="cs-adopt" :disabled="!!adoptBusy" title="归入当前工作区" @click.stop="adoptOrphan(r)">
                  {{ adoptBusy === r.id ? '…' : '归入' }}
                </button>
              </div>
            </template>
          </div>

          <!-- 私信 group（中枢 AI）-->
          <div class="cs-group">
            <button class="cs-group-head" @click="dmsOpen = !dmsOpen">
              <svg class="caret" :class="{ open: dmsOpen }" width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M9 6 15 12 9 18z" /></svg>
              <span>私信</span>
            </button>
            <template v-if="dmsOpen">
              <!-- 高亮互斥(负责人报:两条同时亮):中枢 AI 只在「主区被它占据」时亮——
                   放大态,或 AI 面板开着且没在看任何会话;打开了某个私信/频道时让位给那条 -->
              <div class="cs-item dm-row" :class="{ active: aiMax || (aiOpen && !currentRoom) }" @click="openAiMax">
                <span class="cs-dm-av bot">智<span class="dot-online" /></span>
                <span class="cs-label">中枢 AI</span>
              </div>
              <!-- 真人私信列表:点开在主区聊天;有未读时名字加粗 + 红色未读数 -->
              <!-- !aiMax:放大版主 AI 弹窗占据主区时,底下的会话高亮让位给「中枢 AI」条目 -->
              <div v-for="d in dms" :key="d.id" class="cs-item dm-row" :class="{ active: currentRoom === d.id && !aiMax, unread: (d.unread || 0) > 0 }" @click="openRoom(d.id)" :title="d.pending ? '新私信邀请,点开即接受' : ''">
                <span class="cs-dm-av">{{ initials(d.name) }}</span>
                <span class="cs-label">{{ d.name }}</span>
                <!-- 收藏的联系人:标 ⭐ 并置顶(此前收藏对私信无可见效果) -->
                <span v-if="d.fav" class="cs-dm-fav" title="已收藏">★</span>
                <span v-if="d.pending" class="cs-dm-new">新</span>
                <span v-else-if="(d.unread || 0) > 0" class="cs-dm-unread">{{ d.unread! > 99 ? '99+' : d.unread }}</span>
              </div>
              <div class="cs-item cs-add-row" @click="openStartDm">
                <span class="cs-ic-box"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5v14" /></svg></span>
                <span class="cs-label">邀请成员</span>
              </div>
            </template>
          </div>
        </div>
      </aside>

      <!-- 中：数据看板 / 频道（浮卡）-->
      <main class="main">
        <!-- ===== 数据看板（影视公司制作驾驶舱）===== -->
        <template v-if="board">
          <div class="ch-header">
            <div class="title">📊 数据看板</div>
            <div class="ch-actions">
              <!-- 数据源：点开右侧「数据源」面板（展示 + 增删）-->
              <button class="ch-ic-btn bs-srcbtn" :class="{ active: boardPanelOpen }" :title="`数据源（${sources.dashboard.length}）`" @click="toggleSourcePanel('dashboard')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" /><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3" /></svg>
                <span v-if="sources.dashboard.length" class="bs-badge">{{ sources.dashboard.length }}</span>
              </button>
            </div>
          </div>
          <div class="board-scroll">
            <div class="canvas">
              <div class="ctitle">{{ activeSpaceName }}</div>
              <div class="csub">// 实时运营画布 · 由 CosMac Star 自动维护</div>
              <!-- 一句话下达目标：真的发给中枢 AI（复用 aiSend），不再是 mock 卡片 -->
              <div class="board-ask">
                <div class="board-ask-h">⚡ 一句话下达目标</div>
                <div class="board-ask-row">
                  <span class="board-ask-mark">&gt;</span>
                  <input
                    v-model="boardAsk"
                    class="board-ask-input"
                    placeholder="比如：帮我建个商单专班并拉人 · 查工作室任务状态 · 跑某个工作流"
                    @keyup.enter="askFromBoard"
                  />
                  <button class="board-ask-send" :disabled="!boardAsk.trim()" @click="askFromBoard">下达</button>
                </div>
                <div class="board-ask-tip">交给中枢 AI 执行（建群 / 查任务 / 跑工作流…），结果在右侧中枢 AI 面板。</div>
              </div>
              <!-- 社媒数据：跟工作区「接入数据源」配置走（cosmac.social_sources）。
                   数值待社媒采集器(P2~P4)接上才有真数，现在显示「待接入」占位。 -->
              <div class="board-group-h">
                📈 社媒数据
                <button class="board-src-btn" title="接入社媒数据源（账号 API / AI 爬取）" @click="openSocialModal">
                  🔌 接入数据源
                </button>
              </div>
              <!-- 没配数据源：引导去接入 -->
              <div v-if="!socialSources.length" class="board-empty">
                <div class="board-empty-ic">📡</div>
                <div class="board-empty-t">还没接入社媒数据源</div>
                <div class="board-empty-d">配置抖音 / Instagram / YouTube 等平台账号后，这里展示粉丝、播放、互动等数据。</div>
                <button class="board-empty-btn" @click="openSocialModal">🔌 接入数据源</button>
              </div>
              <!-- 配了数据源：每个平台一张卡（指标待采集器接入）-->
              <div v-else class="src-grid">
                <div v-for="(s, i) in socialSources" :key="i" class="src-card" :style="{ animationDelay: (200 + i * 80) + 'ms' }">
                  <div class="src-head">
                    <span class="src-plat">{{ platformIcon(s.platform) }} {{ platformLabel(s.platform) }}</span>
                    <span class="src-mode" :class="s.mode">{{ s.mode === 'api' ? '官方 API' : 'AI 爬取' }}</span>
                  </div>
                  <div class="src-acc">{{ s.account || '—' }}</div>
                  <div class="src-metrics">
                    <div class="src-m"><span class="src-m-l">粉丝</span><span class="src-m-v">待接入</span></div>
                    <div class="src-m"><span class="src-m-l">播放</span><span class="src-m-v">待接入</span></div>
                    <div class="src-m"><span class="src-m-l">互动</span><span class="src-m-v">待接入</span></div>
                  </div>
                  <div class="src-status" :class="{ off: !s.enabled }">
                    {{ !s.enabled ? '已停用' : (s.lastSync ? '已同步' : '待采集器接入') }}
                  </div>
                </div>
              </div>
              <!-- 平台运营（真实）：会员 / 工作流 / 订单 / 知识库；拿不到数据时整组不渲染 -->
              <template v-if="opsKpis.length">
                <div class="board-group-h">⚙️ 平台运营 <span class="board-group-tag real">真实</span></div>
                <div class="kpis">
                  <KpiCard v-for="(k, i) in opsKpis" :key="k.label" :data="k" :delay="200 + i * 80" />
                </div>
              </template>
            </div>
          </div>
        </template>

        <!-- ===== 任务看板（AI 拆解 → 待办/进行中/已完成 三列 · 真实数据）===== -->
        <template v-else-if="tasks">
          <div class="ch-header">
            <div class="title">📋 任务看板</div>
            <div class="ch-actions">
              <span class="board-sub">{{ scopedTasks.length }} 个任务 · 主 AI 拆解</span>
              <button class="ch-ic-btn" title="刷新" @click="loadTasks">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" /></svg>
              </button>
            </div>
          </div>
          <div class="board-scroll">
            <div class="kan-wrap">
            <p class="kan-tip">💡 在数据看板「一句话下达目标」让中枢 AI 拆解任务，会出现在这里。用卡片上的按钮改状态。</p>

            <!-- 项目/剧集进度：每个目标(goal)一张卡，点选过滤下面的看板 -->
            <div v-if="projects.length" class="proj-strip">
              <button class="proj-card all" :class="{ active: activeGoal === '' }" @click="activeGoal = ''">
                <div class="proj-name">📁 全部项目</div>
                <div class="proj-meta">{{ scopedTasks.length }} 个任务 · {{ projects.length }} 个项目</div>
              </button>
              <button
                v-for="p in activeProjects" :key="p.goal"
                class="proj-card" :class="{ active: activeGoal === p.goal }"
                :title="p.goal"
                @click="activeGoal = p.goal"
              >
                <div class="proj-name">🎬 {{ p.goal }}</div>
                <div class="proj-bar"><div class="proj-bar-fill" :style="{ width: p.pct + '%' }" /></div>
                <div class="proj-meta">{{ p.done }}/{{ p.total }} 完成 · {{ p.pct }}%</div>
              </button>
              <!-- 已完成项目折叠区:默认收起,点开才展示(负责人建议,防 100% 的卡占满首屏) -->
              <button
                v-if="doneProjects.length"
                class="proj-card proj-fold" :class="{ open: showDoneProjects }"
                @click="doneProjectsOpen = !doneProjectsOpen"
              >
                <div class="proj-name">✅ 已完成项目 {{ doneProjects.length }} 个</div>
                <div class="proj-meta">{{ showDoneProjects ? '点击收起 ▲' : '点击展开 ▼' }}</div>
              </button>
              <template v-if="showDoneProjects">
                <button
                  v-for="p in doneProjects" :key="p.goal"
                  class="proj-card proj-done" :class="{ active: activeGoal === p.goal }"
                  :title="p.goal"
                  @click="activeGoal = p.goal"
                >
                  <div class="proj-name">🎬 {{ p.goal }}</div>
                  <div class="proj-bar"><div class="proj-bar-fill" :style="{ width: p.pct + '%' }" /></div>
                  <div class="proj-meta">{{ p.done }}/{{ p.total }} 完成 · {{ p.pct }}%</div>
                </button>
              </template>
            </div>

            <div class="kanban">
              <div v-for="col in TASK_COLS" :key="col.key" class="kan-col" :class="'kan-' + col.key">
                <div class="kan-col-h">
                  <span class="kan-col-dot" />
                  <span class="kan-col-label">{{ col.label }}</span>
                  <span class="kan-n">{{ tasksByStatus(col.key).length }}</span>
                </div>
                <div class="kan-cards">
                  <div v-for="t in tasksByStatus(col.key)" :key="t.id" class="kan-card" :class="{ done: t.status === 'done' }" @click="col.key !== 'done' && moveTask(t, nextStatus(col.key))">
                    <div class="kan-title">{{ t.title }}</div>
                    <div v-if="dueMeta(t)" class="kan-due" :class="dueMeta(t)!.cls">🕒 {{ dueMeta(t)!.text }}</div>
                    <div v-if="t.assignee || execLabel(t) || t.progress > 0" class="kan-foot">
                      <span v-if="t.assignee" class="kan-who">
                        <span class="kan-who-ava">{{ t.assignee.slice(0, 1) }}</span>{{ t.assignee }}
                      </span>
                      <span v-if="execLabel(t)" class="kan-exec" :title="execLabel(t)">{{ execLabel(t) }}</span>
                      <span v-if="t.progress > 0" class="kan-prog">{{ t.progress }}%</span>
                    </div>
                    <div v-if="t.progress > 0 && t.status !== 'done'" class="kan-barwrap">
                      <div class="kan-bar" :style="{ width: t.progress + '%' }" />
                    </div>
                    <div class="kan-btns">
                      <button v-if="col.key !== 'todo'" class="kan-btn" title="退回" @click.stop="moveTask(t, prevStatus(col.key))">←</button>
                      <span class="kan-spacer" />
                      <button v-if="col.key !== 'done'" class="kan-btn primary" @click.stop="moveTask(t, nextStatus(col.key))">{{ col.key === 'todo' ? '开始 →' : '完成 ✓' }}</button>
                    </div>
                  </div>
                  <div v-if="!tasksByStatus(col.key).length" class="kan-empty">
                    <span class="kan-empty-ic">{{ col.key === 'done' ? '🎉' : col.key === 'doing' ? '⚡' : '📥' }}</span>
                    暂无任务
                  </div>
                </div>
              </div>
            </div>
            </div>
          </div>
        </template>

        <!-- ===== 图文教程（全平台一份·前台只读·类公众号；付费可见；编辑在管理后台）===== -->
        <template v-else-if="docs">
          <DocReader />
        </template>

        <!-- ===== 组织/人事（员工花名册·数据智能演示；仅管理员可见数据）===== -->
        <template v-else-if="org">
          <OrgView />
        </template>

        <!-- ===== 频道 ===== -->
        <template v-else>
        <div v-if="currentRoom" class="ch-header">
          <button class="ch-fav" :class="{ active: fav }" :title="fav ? '取消收藏' : '收藏'" @click="toggleFav">
            <svg width="16" height="16" viewBox="0 0 24 24" :fill="fav ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" /></svg>
          </button>
          <span class="ch-av" :style="{ background: colorOf(currentName) }">{{ currentIsDm ? initials(currentName) : iconChar(currentName) }}</span>
          <!-- 私信:标题就是对方名字,没有"频道设置"下拉;频道:可点开频道设置 -->
          <span v-if="currentIsDm" class="title">{{ currentName }}</span>
          <button v-else class="title title-btn" :title="'频道设置'" @click="openChannelSettings">{{ currentName }}<svg class="chev" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg></button>
          <span v-if="currentIsDm" class="ch-vis dm" title="一对一私信：内容仅你们两人可见">私信</span>
          <span v-else-if="currentVis" class="ch-vis" :class="currentVis === '公开' ? 'pub' : 'pri'"
                :title="currentVis === '公开' ? '公开频道：本服务器任何人可自行加入' : '私密频道：仅受邀成员可进'">{{ currentVis }}</span>
          <div v-if="currentTopic && !currentIsDm" class="ch-topic">{{ currentTopic }}</div>
          <div class="ch-actions">
            <!-- 私信管理入口(负责人建议:此前私信没有任何管理入口) -->
            <button v-if="currentIsDm" class="ch-ic-btn" title="修改备注名" @click="renameDmContact">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /></svg>
            </button>
            <button v-if="currentIsDm" class="ch-ic-btn dm-del" title="删除会话（仅从你的列表移除）" @click="deleteDmChat">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /></svg>
            </button>
            <button v-if="!currentIsDm" class="ch-members-btn" title="频道管理 · 成员 / 技能 / 知识库 / 规则" @click="openAdmin(currentName, currentRoom)">
              <div class="ava-stack">
                <div v-for="m in channelMembers.slice(0, 3)" :key="m.id" class="a" :class="{ bot: m.isBot }">{{ m.isBot ? '智' : initials(m.name) }}</div>
              </div>
              <span class="ch-members-count">{{ channelMembers.length }}</span>
            </button>
            <button class="ch-ic-btn" :class="{ active: focused }" :title="focused ? '退出专注' : '专注模式'" @click="focused = !focused">
              <svg v-if="focused" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7V3h4M21 7V3h-4M3 17v4h4M21 17v4h-4" /></svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M12 3v18M3 12h18" /></svg>
            </button>
            <!-- ℹ「关于此频道」：复刻 DEMO，开/关右侧频道信息面板（真实成员+技能/知识库/规则总览）。
                 私信不是频道,没有成员/技能/知识库这些概念,故隐藏(与"频道设置/成员管理"同口径)。-->
            <button v-if="!currentIsDm" class="ch-ic-btn" :class="{ active: rightPanelVisible }" :title="rightPanelVisible ? '关闭关于此频道' : '关于此频道'" @click="toggleRightPanel">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" /></svg>
            </button>
          </div>
        </div>

        <!-- 消息流（Discord 风：分组 / 日期线 / 回复 / 反应 / 悬停工具条）-->
        <div class="stream" ref="streamRef">
          <template v-for="m in groupedMsgs" :key="m.id">
          <!-- 日期分隔线 -->
          <div v-if="m.showDay" class="day-sep"><span>{{ dayLabel(m.ts) }}</span></div>
          <div class="msg" :class="{ bot: isBot(m.sender), me: isMe(m.sender), grouped: !m.showHeader }">
            <!-- 回复预览：整行浮在头像上方（Discord 风：弯角连接线 + ↩ + 名字上色 + 正文淡色）-->
            <div v-if="m.replyToId" class="msg-reply">
              <span class="reply-av" :class="{ bot: isBot(m.replyToSender || '') }" :style="isBot(m.replyToSender || '') ? undefined : { background: nameColor(m.replyToName || '') }">{{ isBot(m.replyToSender || '') ? '智' : initials(m.replyToName || '') }}</span>
              <span class="reply-name" :style="{ color: nameColor(m.replyToName || '') }">{{ (m.replyToName || '').replace(/^@/, '') }}</span>
              <span v-if="isBot(m.replyToSender || '')" class="reply-app">APP</span>
              <span class="reply-body">{{ m.replyToBody }}</span>
            </div>
            <div class="msg-main">
            <!-- 左槽：首条显头像，分组内显悬停时间 -->
            <div class="msg-gutter">
              <div v-if="m.showHeader" class="ava">{{ isBot(m.sender) ? '智' : initials(m.senderName) }}</div>
              <span v-else class="gutter-time">{{ fmtTime(m.ts) }}</span>
            </div>
            <div class="msg-body">
              <div v-if="m.showHeader" class="head">
                <span class="name" :style="{ color: nameColor(m.senderName) }">{{ m.senderName }}</span>
                <span v-if="isBot(m.sender)" class="app-tag">APP</span>
                <span class="time">{{ fmtTime(m.ts) }}</span>
              </div>
              <!-- 附件：图片/视频/音频/文件——AttachmentView 带 token 拉已认证媒体、内嵌预览/下载 -->
              <AttachmentView v-if="m.attachment" :att="m.attachment" />
              <div v-else-if="!m.card" class="text"><span v-html="renderMd(m.body)"></span><span v-if="m.edited" class="edited">（已编辑）</span></div>
              <ChoiceCard v-else-if="m.card.kind === 'choice'" :card="m.card" @pick="(t) => pickChoice(t, currentRoom)" />
              <div v-else-if="m.card.kind === 'team_created'" class="rich team">
                <div class="team-h">✅ 专班「{{ m.card.project }}」已建好，已加入「{{ activeSpaceName }}」</div>
                <button class="team-enter" @click="enterTeam(m.card.team_room)">进入专班 →</button>
              </div>
              <div v-else class="rich info">
                <div class="r-head"><span class="t">🗂 {{ m.card.title }}</span></div>
                <p v-if="m.card.subtitle">{{ m.card.subtitle }}</p>
                <div class="kv">
                  <template v-for="(rw, i) in (m.card.rows || [])" :key="i">
                    <span class="k">{{ rw.task }}</span>
                    <span class="v" :class="rw.type">{{ rw.owner }}</span>
                  </template>
                </div>
              </div>
              <!-- 反应条 -->
              <div v-if="reactions[m.id]?.length" class="reactions">
                <button v-for="r in reactions[m.id]" :key="r.key" class="rxn" :class="{ mine: r.mine }" @click="toggleReaction(m.id, r.key)">{{ r.key }} <b>{{ r.count }}</b></button>
                <button class="rxn add" title="加表情" @click="openEmojiPicker(m.id, $event)">＋</button>
              </div>
            </div>
            </div>
            <!-- 悬停工具条（表情 / 回复 / 编辑(自己) / 复制）-->
            <div class="msg-tools">
              <button title="表情" @click="openEmojiPicker(m.id, $event)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" /><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01" /></svg>
              </button>
              <button title="回复" @click="startReply(m)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 17 4 12 9 7" /><path d="M20 18v-2a4 4 0 0 0-4-4H4" /></svg>
              </button>
              <button v-if="isMe(m.sender) && !m.card" title="编辑" @click="startEdit(m)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
              </button>
              <button title="复制" @click="copyMsg(m.body)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
              </button>
            </div>
          </div>
          </template>
          <p v-if="currentRoom && !msgs.length" class="hint pad">{{ currentIsDm ? '还没有聊天记录，发条消息打个招呼吧' : '这个频道还没有消息' }}</p>
          <p v-if="!currentRoom" class="hint pad">← 选一个频道开始</p>
        </div>

        <!-- emoji 选择器面板 -->
        <div v-if="emojiPicker" class="emoji-pop" :style="{ left: emojiPicker.x + 'px', top: emojiPicker.y + 'px' }" @click.stop>
          <div class="emoji-grid">
            <button v-for="e in EMOJIS" :key="e" class="emoji-cell" @click="pickEmoji(e)">{{ e }}</button>
          </div>
        </div>

        <!-- Composer -->
        <div v-if="currentRoom" class="composer">
          <!-- 私信送不达提醒：对方已停用/退出,发出去也没人收 -->
          <div v-if="dmUndeliverable.show" class="dm-undeliverable">
            ⚠ {{ dmUndeliverable.deactivated
              ? '该用户账号已被停用，消息无法送达。如需继续沟通，请重新邀请对方加入。'
              : '对方已不在此私信中（可能已停用或退出），消息可能无法送达。如需继续沟通，请重新邀请对方加入。' }}
          </div>
          <!-- 回复横幅 -->
          <div v-if="replyTo" class="reply-bar">
            <span class="reply-bar-txt">↩ 回复 <b>{{ replyTo.name }}</b>：{{ replyTo.body.slice(0, 40) }}</span>
            <button class="reply-bar-x" title="取消回复" @click="cancelReply">×</button>
          </div>
          <!-- 编辑横幅 -->
          <div v-if="editingId" class="reply-bar">
            <span class="reply-bar-txt">✏️ 正在<b>编辑</b>消息 · Enter 保存，Esc 取消</span>
            <button class="reply-bar-x" title="取消编辑" @click="cancelEdit">×</button>
          </div>
          <!-- @ 补全面板:成员 + 本频道/我的/已获取 AI Agent(↑↓选,Enter/Tab/点击确认) -->
          <div v-if="mentionOpen" class="mention-pop">
            <button
              v-for="(c, i) in mentionList"
              :key="c.key"
              class="mention-item"
              :class="{ active: i === mentionIdx }"
              @mousedown.prevent="pickMention(c)"
              @mouseenter="mentionIdx = i"
            >
              <span class="mention-ava" :class="{ agent: c.isAgent }">{{ c.isAgent ? '智' : initials(c.label) }}</span>
              <span class="mention-name">{{ c.label }}</span>
              <span class="mention-sub">{{ c.sub }}</span>
            </button>
          </div>
          <div class="composer-box">
            <textarea
              ref="taRef"
              v-model="draft"
              :placeholder="currentIsDm ? `发消息给 ${currentName}` : `发送到 #${currentName}；叫主 AI 试：CosMac 建专班 测试专班`"
              @keydown="onComposerKeydown"
              @input="detectMention"
              @click="detectMention"
              @blur="mentionOpen = false"
            />
            <div class="composer-toolbar">
              <div class="tb-left">
                <button class="tb-btn tb-ai" title="AI 辅助" @click="aiOpen = true"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.9 5.6L19.5 9.5 13.9 11.4 12 17l-1.9-5.6L4.5 9.5l5.6-1.9L12 2z" /></svg><span>AI</span></button>
                <span class="tb-sep" />
                <button class="tb-btn" title="加粗" @click="tb.bold"><b>B</b></button>
                <button class="tb-btn" title="斜体" @click="tb.italic"><i>I</i></button>
                <button class="tb-btn" title="删除线" @click="tb.strike"><s>S</s></button>
                <button class="tb-btn tb-heading" title="标题" @click="tb.heading">H</button>
                <span class="tb-sep" />
                <button class="tb-btn" title="链接" @click="tb.link"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></svg></button>
                <button class="tb-btn" title="代码" @click="tb.code"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg></button>
                <button class="tb-btn" title="引用" @click="tb.quote"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 7v6H4V9c0-1.1.9-2 2-2h1Zm10 0v6h-3V9c0-1.1.9-2 2-2h1Z" /></svg></button>
                <button class="tb-btn" title="无序列表" @click="tb.ul"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" /></svg></button>
                <button class="tb-btn" title="@提及" @click="tb.at"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8" /></svg></button>
                <span class="tb-sep" />
                <!-- 上传图片/附件：点开系统文件框，图片走缩略图、其余走下载卡片 -->
                <button class="tb-btn" :title="uploading ? '上传中…' : '上传图片/附件'" :disabled="uploading" @click="pickAttachment">
                  <svg v-if="!uploading" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" /></svg>
                  <span v-else class="tb-spin" />
                </button>
              </div>
              <div class="tb-right">
                <button class="send" :disabled="!draft.trim()" title="发送 (Enter)" @click="send"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13" /><path d="M22 2 15 22l-4-9-9-4Z" /></svg></button>
              </div>
              <!-- 隐藏的文件选择框：多选;图片+常见文档都可 -->
              <input ref="fileInputRef" type="file" multiple style="display:none" @change="onAttachmentPicked" />
            </div>
          </div>
        </div>
        </template>
      </main>

      <!-- 右：关于此频道（复刻 DEMO，ℹ 按钮开关；真实成员 + 技能/知识库/规则总览）-->
      <RightPanel v-if="rightPanelVisible && currentRoom && !currentIsDm && !focused" />

      <!-- 右：数据源面板（数据看板/任务看板头的数据源按钮开关）-->
      <BoardSourcePanel v-if="boardPanelOpen && !focused" />

      <!-- 社媒数据源配置弹窗（看板「接入数据源」按钮打开）-->
      <SocialSourceModal />

      <!-- 首次引导：注册/登录后的「主 AI 问答」向导（全屏覆盖，建工作区/频道/AI人设）-->
      <OnboardingWizard @done="onOnboardingDone" @skip="onOnboardingSkip" />

      <!-- 放大态遮罩：盖住整页，点空白处还原 -->
      <div v-if="aiOpen && aiMax && !focused" class="ai-backdrop" @click="aiMax = false" />

      <!-- 右：中枢 AI 面板（浮卡；放大态撑成 Cowork 式全屏弹窗）-->
      <aside class="ai-panel" :class="{ maximized: aiMax }" v-if="aiOpen && !focused">
        <!-- 顶栏（放大态作为弹窗标题栏，横跨三栏）-->
        <div class="ai-head">
          <span class="ai-dot" />
          <span class="ai-title">中枢 AI · CosMac Star</span><span class="ai-dm-badge" title="这是你与中枢 AI 的一对一私人会话，内容仅你们可见；邀请成员请到目标频道里 @AI 操作">私人会话</span>
          <div class="ai-head-actions">
            <!-- 放大 / 还原 -->
            <button class="ai-ic-btn" :title="aiMax ? '还原' : '放大'" @click="aiMax = !aiMax">
              <svg v-if="aiMax" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" /></svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" /></svg>
            </button>
            <button class="ai-ic-btn" title="收起" @click="aiOpen = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
            </button>
          </div>
        </div>

        <!-- 主体：默认单列；放大态三栏（左导航 + 中对话 + 右进度/文件）-->
        <div class="ai-main">

          <!-- 左栏（仅放大态）：Recents 历史会话列表 + 新建会话（参考 Claude；复用 Cowork 左栏样式）-->
          <div v-if="aiMax" class="ai-cw-left">
            <button class="ai-cw-newtask" @click="newAiSession">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
              新建会话
            </button>
            <div class="ai-cw-recents">
              <div class="ai-cw-recents-h"><span>最近会话</span></div>
              <ul class="ai-cw-list">
                <li v-for="s in aiSessions" :key="s.roomId"
                    class="ai-recent-li" :class="{ act: s.roomId === aiRoom }"
                    @click="switchAiSession(s.roomId)">
                  <span class="ai-recent-t">{{ s.title }}</span>
                  <button class="ai-recent-del" title="删除会话" @click.stop="removeAiSession(s.roomId)">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
                  </button>
                </li>
                <li v-if="!aiSessions.length" class="ai-recents-empty">还没有会话，点上方「新建会话」。</li>
              </ul>
            </div>
          </div>

          <!-- 中栏：对话 + 输入（dock / 放大 共用）-->
          <div class="ai-center">
            <div ref="aiBodyRef" class="ai-body">
              <div v-for="m in aiMsgs" :key="m.id" class="ai-msg" :class="{ mine: isMe(m.sender) }">
                <div v-if="!m.card" class="ai-bubble" v-html="renderMd(m.body)"></div>
                <ChoiceCard v-else-if="m.card.kind === 'choice'" :card="m.card" @pick="(t) => pickChoice(t, aiRoom)" />
                <div v-else-if="m.card.kind === 'team_created'" class="rich team">
                  <div class="team-h">✅ 专班「{{ m.card.project }}」已建好，已加入「{{ activeSpaceName }}」</div>
                  <button class="team-enter" @click="enterTeam(m.card.team_room)">进入专班 →</button>
                </div>
                <div v-else class="rich info">
                  <div class="r-head"><span class="t">🗂 {{ m.card.title }}</span></div>
                  <p v-if="m.card.subtitle">{{ m.card.subtitle }}</p>
                  <div class="kv">
                    <template v-for="(rw, i) in (m.card.rows || [])" :key="i">
                      <span class="k">{{ rw.task }}</span>
                      <span class="v" :class="rw.type">{{ rw.owner }}</span>
                    </template>
                  </div>
                </div>
              </div>
              <!-- ③ 流式体感：bot 生成回复期间显示"正在输入…"，长回复不再死寂 -->
              <div v-if="botTyping" class="ai-msg">
                <div class="ai-bubble typing"><span class="td" /><span class="td" /><span class="td" /></div>
              </div>
              <p v-if="!aiMsgs.length && !botTyping" class="hint pad">跟中枢 AI 说句话，比如"帮我建个爆款专班"</p>
            </div>
            <div class="ai-composer">
              <!-- 作用域提示条(可关闭,关闭后记住):消除"每个频道打开面板内容都一样=数据未隔离"的误解 -->
              <div v-if="!aiScopeTipDismissed" class="ai-scope-tip">
                <span>💡 这里是<b>全局助理</b>·跨频道统筹，内容不随频道切换；要找<b>本频道的 AI</b>，请在频道消息框里 @ 它</span>
                <button class="ai-scope-tip-x" title="知道了，不再提示" @click="dismissAiScopeTip">×</button>
              </div>
              <div class="ai-input-box">
                <input v-model="aiDraft" placeholder="一句话下达目标…" @keyup.enter="aiSend" />
                <div class="ai-toolbar">
                  <div class="ai-tb-left"></div>
                  <button class="ai-send-ic" :disabled="!aiDraft.trim()" @click="aiSend"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13" /><path d="M22 2 15 22l-4-9-9-4Z" /></svg></button>
                </div>
              </div>
            </div>
          </div>

          <!-- 右栏（仅放大态）：进度=真实任务看板 / 项目文件=真实知识库文档 -->
          <div v-if="aiMax" class="ai-cw-right">
            <div class="ai-cw-sec">
              <div class="ai-cw-sec-h with-meta"><span>进度</span><span class="ai-cw-meta">{{ doneCount }}/{{ scopedTasks.length }}</span></div>
              <ul v-if="scopedTasks.length" class="ai-cw-progress">
                <li v-for="t in scopedTasks.slice(0, 9)" :key="t.id"
                    :class="{ done: t.status === 'done', in: t.status === 'doing' }">
                  {{ t.title }}<template v-if="t.status === 'doing' && t.progress"> · {{ t.progress }}%</template>
                </li>
              </ul>
              <div v-else class="ai-cw-empty">还没有任务。在数据看板「一句话下达目标」让中枢 AI 拆解。</div>
            </div>
            <div class="ai-cw-sec">
              <div class="ai-cw-proj-h">
                <span class="ai-cw-proj-nm">知识库 · {{ activeSpaceName }}</span>
                <button class="ai-cw-manage" title="管理知识库" @click="openKnowledge">管理</button>
              </div>
              <ul v-if="kbDocsMine.length" class="ai-cw-files">
                <li v-for="d in kbDocsMine" :key="d.id"><span class="ic">📄</span>{{ d.title || '(无标题)' }}</li>
              </ul>
              <div v-else class="ai-cw-empty">还没有知识库文档。点「管理」上传，或在频道里发「知识库 添加 标题|内容」。</div>
            </div>
          </div>

        </div>
      </aside>

      <!-- 最右：插件竖栏 -->
      <nav v-if="!focused" class="plugin-rail">
        <div class="pr-list">
          <div class="pr-icon active" title="中枢 AI" @click="aiOpen = !aiOpen">智</div>
          <!-- 插件商城装的插件（存 account data,刷新恢复）;点击进商城管理(卸载/换) -->
          <div
            v-for="p in installedPlugins"
            :key="p.id"
            class="pr-icon"
            :title="p.title"
            :style="p.color ? { background: p.color, color: '#fff' } : undefined"
            @click="onPluginStore"
          >{{ p.label }}</div>
          <div class="pr-icon plus" title="添加插件" @click="onPluginStore">+</div>
        </div>
        <div class="pr-divider" />
        <div class="pr-icon assets" title="资产 · 自定义配置" @click="onCustomAssets">◈</div>
        <div class="pr-icon gear" title="插件商城" @click="onPluginStore">⚙</div>
      </nav>
    </div>

    <!-- 弹窗/面板（常驻挂载，内部按各自 composable 的 visible 控制显隐）-->
    <!-- AI Agent 商城已接真数据（bot /cosmac/market/catalog）；等级不够点「升级解锁」→ 会员弹窗 -->
    <MarketplaceModal @upgrade="showMembership = true" />
    <PluginStoreModal />
    <CustomAssetsModal />
    <UserSettingsModal />

    <!-- 我的AI工坊:自建智能体/技能(归属本人,计入存储) -->
    <MyStudioModal :visible="myStudioOpen" @close="myStudioOpen = false" />
    <ProfileHome />
    <CliConsole />
    <ChannelAdminModal />
    <KnowledgeModal />
    <MyPeopleModal />
    <MyUsageModal />

    <!-- 平台管理后台（全屏覆盖层；仅管理员可从用户菜单进入）-->
    <AdminView v-if="adminOpen" @close="adminOpen = false" />

    <!-- 升级会员弹窗（模块4 交易系统）-->
    <MembershipModal v-if="showMembership" @close="showMembership = false" />


    <!-- 新建工作区（完整表单 · 真建 Matrix Space + 默认频道）-->
    <div v-if="newWsOpen" class="nw-overlay" @click.self="newWsOpen = false">
      <div class="nw-modal">
        <div class="nw-title">新建工作区</div>
        <div class="nw-sub">工作区 = 一个独立空间（Space），底下挂自己的频道、成员独立</div>

        <!-- 类型 -->
        <div class="nw-field-label">类型</div>
        <div class="nw-types">
          <button
            v-for="t in WS_TYPES"
            :key="t.key"
            class="nw-type"
            :class="{ on: newWsType === t.key }"
            @click="newWsType = t.key"
          >{{ t.title }}</button>
        </div>

        <!-- 名称 -->
        <div class="nw-field-label">{{ curWsType.nameLabel }}</div>
        <input v-model="newWsName" class="nw-input" maxlength="50" :placeholder="curWsType.namePh" @keyup.enter="createWorkspace" />

        <!-- 简称（全宽）-->
        <div class="nw-field-label">简称 <span class="nw-hint">左栏图标 · 最多 2 字 · 可留空</span></div>
        <input v-model="newWsLabel" class="nw-input" :placeholder="newWsSpaceName ? wsLabel(newWsSpaceName) : '如 制作'" />

        <!-- 可见性（全宽，两个等宽按钮）-->
        <div class="nw-field-label">可见性</div>
        <div class="nw-vis">
          <button class="nw-vis-btn" :class="{ on: !newWsPublic }" @click="newWsPublic = false">私密 · 邀请制</button>
          <button class="nw-vis-btn" :class="{ on: newWsPublic }" @click="newWsPublic = true">公开 · 可加入</button>
        </div>

        <!-- 预览：将创建什么 -->
        <div v-if="newWsName.trim()" class="nw-preview">
          <div class="nw-prev-h">将创建</div>
          <div class="nw-prev-ws"><span class="nw-prev-ic">{{ newWsLabel.trim() || wsLabel(newWsSpaceName) }}</span>工作区「{{ newWsSpaceName }}」</div>
          <div v-for="c in newWsChannels" :key="c" class="nw-prev-ch"># {{ c }}<span class="nw-prev-tip">含主 AI</span></div>
        </div>

        <div class="nw-foot">
          <button class="nw-btn" :disabled="newWsCreating" @click="newWsOpen = false">取消</button>
          <button class="nw-btn primary" :disabled="!newWsName.trim() || newWsCreating" @click="createWorkspace">{{ newWsCreating ? '创建中…' : '创建' }}</button>
        </div>
      </div>
    </div>

    <!-- 新建频道（在当前工作区下真建）-->
    <div v-if="newChOpen" class="nw-overlay" @click.self="newChOpen = false">
      <div class="nw-modal">
        <div class="nw-title">新建频道</div>
        <div class="nw-sub">将建在「{{ activeSpaceName }}」工作区下，并自动拉主 AI 进群</div>
        <div class="nw-field-label">频道名称</div>
        <input v-model="newChName" class="nw-input" maxlength="50" placeholder="如：第二季筹备 / 海报评审" @keyup.enter="createChannel" />
        <div class="nw-field-label">简介（可选，显示在频道头）</div>
        <textarea v-model="newChTopic" class="nw-input nw-textarea" rows="2" maxlength="200" placeholder="一句话说明这个频道是干嘛的" />
        <div class="nw-field-label">可见性</div>
        <div class="nw-vis">
          <button class="nw-vis-btn" :class="{ on: !newChPublic }" @click="newChPublic = false">私密 · 邀请制</button>
          <button class="nw-vis-btn" :class="{ on: newChPublic }" @click="newChPublic = true">公开 · 可加入</button>
        </div>
        <div v-if="newChName.trim()" class="nw-preview">
          <div class="nw-prev-h">将创建</div>
          <div class="nw-prev-ch"># {{ newChName.trim() }}<span class="nw-prev-tip">含主 AI · 归属「{{ activeSpaceName }}」</span></div>
        </div>
        <div class="nw-foot">
          <button class="nw-btn" :disabled="newChCreating" @click="newChOpen = false">取消</button>
          <button class="nw-btn primary" :disabled="!newChName.trim() || newChCreating" @click="createChannel">{{ newChCreating ? '创建中…' : '创建' }}</button>
        </div>
      </div>
    </div>

    <!-- 频道设置：改名称 / 简介（真写进 Matrix 房间）-->
    <div v-if="chSetOpen" class="nw-overlay" @click.self="chSetOpen = false">
      <div class="nw-modal">
        <div class="nw-title">频道设置</div>
        <div class="nw-sub">改这个频道的名称和简介（实时写进后端）</div>
        <div class="nw-field-label">频道名称</div>
        <input v-model="chSetName" class="nw-input" maxlength="50" placeholder="频道名称" @keyup.enter="saveChannelSettings" />
        <div class="nw-field-label">简介</div>
        <textarea v-model="chSetTopic" class="nw-input nw-textarea" rows="2" maxlength="200" placeholder="一句话说明这个频道是干嘛的" />
        <!-- 移动到工作区：有 ≥2 个工作区才显示;选了别的工作区,保存时就真移动过去 -->
        <template v-if="spaces.length > 1">
          <div class="nw-field-label">所在工作区</div>
          <select v-model="chSetSpace" class="nw-input">
            <option v-for="s in spaces" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
          <p v-if="chSetSpace && chSetSpace !== activeSpace" class="nw-hint">保存后此频道将移动到「{{ spaces.find((s) => s.id === chSetSpace)?.name }}」，成员和聊天记录不受影响</p>
        </template>
        <div v-if="chDeleteArm && chDeleteTaskWarn > 0" class="ch-del-warn">
          ⚠️ 本频道还有 <b>{{ chDeleteTaskWarn }}</b> 个未完成任务。退出后这些任务仍在任务看板里，
          但你将失去从这个频道跟进它们的入口。确认要退出吗？
        </div>
        <div class="nw-foot nw-foot-split">
          <div class="nw-foot-left">
            <button v-if="!chDeleteArm" class="nw-btn danger-outline" :disabled="chSetBusy" @click="chDeleteArm = true" title="从你的列表移除此频道（频道本身仍在，其他成员不受影响）">退出频道</button>
            <template v-else>
              <button class="nw-btn danger" :disabled="chSetBusy" @click="deleteChannel">
                {{ chSetBusy ? '处理中…' : (chDeleteTaskWarn > 0 ? '仍要退出' : '确认退出') }}
              </button>
              <button class="nw-btn" :disabled="chSetBusy" title="取消" @click="chDeleteArm = false; chDeleteTaskWarn = 0">×</button>
            </template>
          </div>
          <div class="nw-foot-right">
            <button class="nw-btn" :disabled="chSetBusy" @click="chSetOpen = false">取消</button>
            <button class="nw-btn primary" :disabled="!chSetName.trim() || chSetBusy" @click="saveChannelSettings">{{ chSetBusy ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 工作区设置：改名称 / 简称（真写进 Matrix Space）-->
    <div v-if="wsSetOpen" class="nw-overlay" @click.self="wsSetOpen = false">
      <div class="nw-modal">
        <div class="nw-title">工作区设置</div>
        <div class="nw-sub">改这个工作区的名称和左栏简称（实时写进后端）</div>
        <div class="nw-field-label">名称</div>
        <input v-model="wsSetName" class="nw-input" maxlength="50" placeholder="工作区名称" @keyup.enter="saveWsSettings" />
        <div class="nw-field-label">简称（左栏图标，最多 2 字；上传图片后以图片为准）</div>
        <input v-model="wsSetLabel" class="nw-input" maxlength="2" :placeholder="wsSetName ? wsLabel(wsSetName) : '如 制作'" />

        <div class="nw-field-label">图标（上传图片，可选）</div>
        <div class="nw-avatar-row">
          <span class="nw-avatar-prev" :style="!wsSetAvatarPreview ? { background: 'var(--action)' } : undefined">
            <img v-if="wsSetAvatarPreview" :src="wsSetAvatarPreview" alt="" />
            <template v-else>{{ wsSetLabel.trim() || wsLabel(wsSetName) || '?' }}</template>
          </span>
          <button class="nw-btn" :disabled="wsUploading" @click="wsFileInput?.click()">{{ wsUploading ? '上传中…' : (wsSetAvatarPreview ? '更换图片' : '上传图片') }}</button>
          <button v-if="wsSetAvatarPreview" class="nw-btn" :disabled="wsUploading" @click="removeWsImage">移除</button>
          <input ref="wsFileInput" type="file" accept="image/*" hidden @change="onPickWsImage" />
        </div>

        <div class="nw-preview" v-if="wsSetName.trim()">
          <div class="nw-prev-ws">
            <span class="nw-prev-ic" :style="wsSetAvatarPreview ? { padding: 0, overflow: 'hidden' } : undefined">
              <img v-if="wsSetAvatarPreview" :src="wsSetAvatarPreview" alt="" style="width:100%;height:100%;object-fit:cover" />
              <template v-else>{{ wsSetLabel.trim() || wsLabel(wsSetName) }}</template>
            </span>{{ wsSetName }}
          </div>
        </div>

        <!-- 社区服务器：开放加入 + 邀请链接（像 Discord 那样发链接拉人进来）-->
        <div class="ws-join">
          <div class="ws-join-row">
            <div>
              <div class="ws-join-title">🌐 公开分享（社区服务器）</div>
              <div class="ws-join-sub">{{ wsOpenJoin ? '已公开：任何人凭下面的链接可加入本工作区的全部频道' : '当前私密：要生成分享链接，需先公开本工作区（精确控制请改用「成员与角色管理」逐个邀请）' }}</div>
            </div>
            <button class="ws-toggle" :class="{ on: wsOpenJoin }" :disabled="wsJoinBusy" @click="toggleWsOpenJoin">
              <span class="ws-toggle-dot" />
            </button>
          </div>
          <!-- 公开前的后果确认:公开=无审批+全部频道,必须看清再点(防误开) -->
          <div v-if="wsOpenConfirm && !wsOpenJoin" class="ws-join-warn">
            <div class="ws-join-warn-title">⚠️ 确认要公开「{{ wsSetName }}」吗？</div>
            <ul class="ws-join-warn-list">
              <li>任何拿到链接的人都能<b>直接加入，没有审批环节</b></li>
              <li>对方将进入本工作区的<b>全部频道</b>（无法只分享部分频道）</li>
              <li>之后关闭公开，链接会失效，但<b>已加入的成员不会被自动移除</b></li>
            </ul>
            <div class="ws-join-warn-actions">
              <button class="nw-btn danger" :disabled="wsJoinBusy" @click="applyWsOpenJoin(true)">{{ wsJoinBusy ? '开启中…' : '我已了解，公开并生成链接' }}</button>
              <button class="nw-btn" :disabled="wsJoinBusy" @click="wsOpenConfirm = false">取消</button>
            </div>
          </div>
          <div v-if="wsOpenJoin" class="ws-join-link">
            <input class="nw-input" :value="wsJoinLink" readonly @focus="($event.target as HTMLInputElement).select()" />
            <button class="nw-btn" @click="copyWsJoinLink">{{ wsLinkCopied ? '已复制 ✓' : '复制链接' }}</button>
          </div>
          <button class="nw-btn ws-members-btn" @click="openServerMembers">👥 成员与角色管理</button>
        </div>

        <div class="nw-foot nw-foot-split">
          <!-- 左：删除工作区（红色按钮 → 点一下变二次确认）-->
          <div class="nw-foot-left">
            <button v-if="!wsDeleteArm" class="nw-btn danger-outline" :disabled="wsSetBusy" @click="wsDeleteArm = true">删除工作区</button>
            <template v-else>
              <button class="nw-btn danger" :disabled="wsSetBusy" :title="`删除「${wsSetName}」及其 ${wsChildCount} 个频道，不可撤销`" @click="deleteWorkspace">{{ wsSetBusy ? '删除中…' : `确认删除（含 ${wsChildCount} 频道）` }}</button>
              <button class="nw-btn" :disabled="wsSetBusy" title="取消删除" @click="wsDeleteArm = false">×</button>
            </template>
          </div>
          <!-- 右：取消 / 保存 -->
          <div class="nw-foot-right">
            <button class="nw-btn" :disabled="wsSetBusy" @click="wsSetOpen = false">取消</button>
            <button class="nw-btn primary" :disabled="!wsSetName.trim() || wsSetBusy" @click="saveWsSettings">{{ wsSetBusy ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 社区服务器：成员与角色管理 -->
    <div v-if="memberMgrOpen" class="nw-overlay" @click.self="memberMgrOpen = false">
      <div class="nw-modal">
        <div class="nw-title">成员与角色</div>
        <div class="nw-sub">「{{ activeSpaceName }}」的成员（{{ serverMembers.length }} 人）· {{ myServerPower >= 100 ? '你是群主' : myServerPower >= 50 ? '你是管理员' : '你是成员' }}</div>
        <div class="nw-note">这里是<b>工作区级</b>成员（能管理整个工作区的人）。各频道的成员是独立的——加入某个频道并不等于加入工作区；要看某频道有哪些人，请到该频道的「关于此频道」面板查看。</div>
        <div class="mmg-list">
          <div v-for="m in serverMembers" :key="m.id" class="mmg-row">
            <span class="mmg-ava" :class="{ bot: m.isBot }">
              <img v-if="m.avatar" :src="m.avatar" alt="" /><template v-else>{{ initials(m.name) }}</template>
            </span>
            <div class="mmg-info">
              <div class="mmg-name">{{ m.name }}<span v-if="m.id === me" class="mmg-you">你</span></div>
              <div class="mmg-role" :class="m.role">{{ m.isBot ? '主 AI' : m.roleLabel }}{{ m.pending ? ' · 待接受' : '' }}</div>
            </div>
            <div class="mmg-ops" v-if="canManage(m)">
              <button v-if="myServerPower >= 100 && m.power < 50" class="nw-btn sm" :disabled="memberMgrBusy === m.id" @click="setMemberRole(m, 50)">设为管理员</button>
              <button v-if="myServerPower >= 100 && m.power >= 50" class="nw-btn sm" :disabled="memberMgrBusy === m.id" @click="setMemberRole(m, 0)">取消管理员</button>
              <button class="nw-btn sm" :disabled="memberMgrBusy === m.id" @click="removeServerMember(m)">移出</button>
              <button class="nw-btn sm danger-outline" :disabled="memberMgrBusy === m.id" @click="banServerMember(m)">封禁</button>
            </div>
          </div>
          <p v-if="!serverMembers.length" class="mmg-empty">还没有成员</p>

          <!-- 已封禁（仅管理员可见） -->
          <template v-if="bannedMembers.length">
            <div class="mmg-section">已封禁（{{ bannedMembers.length }}）· 无法加入，直到解封</div>
            <div v-for="u in bannedMembers" :key="u.id" class="mmg-row">
              <span class="mmg-ava banned"><img v-if="u.avatar" :src="u.avatar" alt="" /><template v-else>{{ initials(u.name) }}</template></span>
              <div class="mmg-info"><div class="mmg-name">{{ u.name }}</div><div class="mmg-role">已封禁</div></div>
              <div class="mmg-ops"><button class="nw-btn sm" :disabled="memberMgrBusy === u.id" @click="unbanServerMember(u)">解封</button></div>
            </div>
          </template>
        </div>
        <div class="nw-foot">
          <!-- 二级弹窗:给一条回到「工作区设置」的路(此前进来后只能关掉、回不去上一级) -->
          <button class="nw-btn mmg-back" @click="backToWsSettings">← 返回工作区设置</button>
          <button class="nw-btn" :disabled="mmgRefreshing" @click="refreshServerMembers">
            {{ mmgRefreshing ? '刷新中…' : '刷新' }}
          </button>
          <button class="nw-btn primary" @click="memberMgrOpen = false">完成</button>
        </div>
      </div>
    </div>

    <!-- 成员管理：邀请已有用户进当前频道/工作区（真功能 · Matrix invite）-->
    <!-- 发起真人私信(DM):一对一,与"邀请进频道"彻底分开 -->
    <div v-if="dmDialogOpen" class="nw-overlay" @click.self="dmDialogOpen = false">
      <div class="nw-modal">
        <div class="nw-title">发起私信</div>
        <div class="nw-sub">和某个人开一个<b>一对一私聊</b>,聊天出现在左侧「私信」区。<br>这不是邀请进频道——邀请进频道请到目标频道里操作。</div>
        <div class="nw-field-label">对方用户名</div>
        <div class="nw-inline">
          <input v-model="dmUserInput" class="nw-input" placeholder="用户名 或 @用户:cosmac.cc" @keyup.enter="doStartDm" />
          <button class="nw-btn primary" :disabled="!dmUserInput.trim() || dmBusy" @click="doStartDm">{{ dmBusy ? '发起中…' : '发起私信' }}</button>
        </div>
        <div class="nw-note">💡 对方需已有账号。发起后对方会收到私信邀请,接受即可开始聊天。</div>
        <div class="nw-foot">
          <button class="nw-btn" :disabled="dmBusy" @click="dmDialogOpen = false">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="memberOpen" class="nw-overlay" @click.self="memberOpen = false">
      <div class="nw-modal">
        <div class="nw-title">邀请成员</div>
        <div class="nw-sub">
          邀请进：<b v-if="memberTarget">{{ memberTarget.name }}</b><span v-else class="nw-warn">请先打开一个频道</span>
        </div>

        <div class="nw-field-label">邀请用户名</div>
        <div class="nw-inline">
          <input v-model="inviteUserInput" class="nw-input" placeholder="用户名 或 @用户:cosmac.cc" @keyup.enter="doInvite" />
          <button class="nw-btn primary" :disabled="!inviteUserInput.trim() || !memberTarget || memberBusy" @click="doInvite">{{ memberBusy ? '邀请中…' : '邀请' }}</button>
        </div>

        <!-- 当前真实成员 -->
        <div class="nw-field-label">当前成员 <span class="nw-hint">{{ memberList.length }} 人</span></div>
        <div class="nw-mem-list">
          <div v-for="m in memberList" :key="m.id" class="nw-mem">
            <span class="nw-mem-av" :class="{ bot: m.isBot }">{{ m.isBot ? '智' : initials(m.name) }}</span>
            <span class="nw-mem-name">{{ m.name }}</span>
            <span v-if="m.isBot" class="nw-mem-tag">AI</span>
            <span v-else-if="m.pending" class="nw-mem-tag pending">待接受</span>
          </div>
          <p v-if="!memberList.length" class="nw-mem-empty">还没有成员</p>
        </div>

        <div class="nw-note">
          💡 <b>新建账号 / 邀请链接</b> 需要后端支持（后端管理接口不对外开放，不能从浏览器用管理员令牌建号），放到后续「成员管理后台」模块做。现在可邀请<b>已有账号</b>的用户。
        </div>

        <div class="nw-foot">
          <button class="nw-btn" :disabled="memberBusy" @click="memberOpen = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- toast(本地队列 + 全局 useToast 队列;后者供协作人/知识库/后台等 composable 使用) -->
    <div class="toast-host">
      <div v-for="t in toasts" :key="t.id" class="toast">
        <div class="toast-title">{{ t.title }}</div>
        <div v-if="t.msg" class="toast-msg">{{ t.msg }}</div>
      </div>
      <div v-for="t in globalToasts" :key="'g' + t.id" class="toast" :class="t.kind">
        <div class="toast-title">{{ t.text }}</div>
        <div v-if="t.desc" class="toast-msg">{{ t.desc }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
* { box-sizing: border-box; }

/* 填充式控件的暖色（替代演示版的中性灰 rgb(202,204,207)）*/
.shell { --chip: #e7ddcd; --chip-hover: #ddd0bb; }

/* ════════ 登录页 ════════ */
.login { height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(180deg, var(--bg-panel), var(--bg-soft)); font-family: var(--font-body); }
.login-card { width: 640px; max-width: 92vw; min-height: 502px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between; gap: 20px; padding: 40px; background: #fff; border: 1px solid var(--border); border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,.08); }
/* 三段式：顶部品牌/tab、中部字段、底部按钮——space-between 把多出来的高度分配到段间，
   内容均匀填满高框，不再挤成一团浮在中间。 */
.auth-top { display: flex; flex-direction: column; gap: 16px; }
.auth-fields { display: flex; flex-direction: column; gap: 14px; }
.auth-bottom { display: flex; flex-direction: column; gap: 12px; }
.login-brand { font-weight: 800; font-size: 22px; color: var(--text); display: inline-flex; align-items: center; gap: 8px; }
.login-brand span { color: var(--accent); margin-left: 4px; }
.brand-logo { width: 26px; height: 26px; object-fit: contain; border-radius: 6px; }
.login-card input { padding: 13px 15px; border: 1px solid var(--border); border-radius: 10px; font-size: 15px; }
.login-btn { padding: 14px; border: 0; border-radius: 10px; background: var(--action); color: #fff; font-size: 15px; font-weight: 600; cursor: pointer; }
.login-btn:disabled { opacity: .6; cursor: default; }
/* 登录 / 注册 分段切换 */
.auth-tabs { display: flex; gap: 4px; padding: 4px; background: var(--bg, #f1efe9); border: 1px solid var(--border); border-radius: 10px; }
.auth-tab { flex: 1; padding: 10px; border: 0; background: transparent; color: var(--text-3); font-size: 15px; font-weight: 600; border-radius: 8px; cursor: pointer; }
.auth-tab.active { background: #fff; color: var(--text); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
/* 登录方式子切换：账号 / 邮箱（比主 tab 轻量）*/
.auth-subtabs { display: flex; gap: 18px; padding: 0 2px; }
.auth-subtab { border: 0; background: transparent; color: var(--text-3); font-size: 14px; font-weight: 600; padding: 2px 0 6px; cursor: pointer; border-bottom: 2px solid transparent; }
.auth-subtab.active { color: var(--accent); border-bottom-color: var(--accent); }
/* 注册：邮箱 + 发送验证码 一行 */
.auth-code-row { display: flex; gap: 8px; }
.auth-code-row input { flex: 1; min-width: 0; }
.auth-code-btn { flex-shrink: 0; padding: 0 12px; border: 1px solid var(--border); background: var(--bg-panel, #fff); color: var(--accent); font-size: 13px; font-weight: 600; border-radius: 10px; cursor: pointer; white-space: nowrap; }
.auth-code-btn:disabled { opacity: .5; cursor: default; color: var(--text-3); }
.auth-reset-title { font-size: 16px; font-weight: 700; color: var(--text); text-align: center; padding: 2px 0; }
.auth-switch { color: var(--text-3); font-size: 13px; text-align: center; margin: 0; }
.auth-switch a { color: var(--accent); cursor: pointer; font-weight: 600; }
.auth-switch a:hover { text-decoration: underline; }
.err { color: var(--danger); font-size: 13px; }
.live-splash { height: 100vh; display: flex; align-items: center; justify-content: center; color: var(--text-3); font-size: 14px; background: linear-gradient(180deg, var(--bg-panel), var(--bg-soft)); }
/* 频道类型角标:私密(灰)/公开(绿),挂在频道名旁 */
.ch-vis { flex-shrink: 0; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; line-height: 1.4; }
.ch-vis.pri { background: var(--bg, #f1efe9); color: var(--text-3); border: 1px solid var(--border); }
.ch-vis.pub { background: #e8f2e6; color: #4c7a4f; border: 1px solid #cfe3cd; }
.ch-vis.dm { background: #fdf1e3; color: var(--accent); border: 1px solid #f0ddc2; }
/* 私信列表"新邀请"红标 */
.cs-dm-new { flex-shrink: 0; font-size: 10px; font-weight: 700; color: #fff; background: #c0392b; border-radius: 999px; padding: 1px 6px; }
/* 已收藏联系人的星标(与头部收藏星同色系) */
.cs-dm-fav { flex-shrink: 0; font-size: 12px; color: var(--accent); }
/* 私信未读:红色计数徽章 + 未读行名字加粗 */
.cs-dm-unread { flex-shrink: 0; min-width: 16px; height: 16px; padding: 0 5px; border-radius: 8px; background: #c0392b; color: #fff; font-size: 10px; font-weight: 700; line-height: 16px; text-align: center; }
.dm-row.unread .cs-label { font-weight: 700; color: var(--text); }
/* AI 面板"私人会话"角标 */
.ai-dm-badge { flex-shrink: 0; margin-left: 8px; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; background: var(--bg, #f1efe9); color: var(--text-3); border: 1px solid var(--border); }
.hint { color: var(--text-3); font-size: 12px; }
.hint.pad { padding: 16px; }

/* ════════ 外壳 ════════ */
.shell { height: 100vh; display: flex; flex-direction: column; font-family: var(--font-body); color: var(--text); background: var(--bg-soft); }

/* ──── 顶栏（46 高，无下边框）──── */
.topbar { height: var(--topbar-h); display: flex; align-items: center; padding: 0 12px; gap: 10px; background: var(--bg-soft); position: relative; z-index: 20; flex-shrink: 0; }
.tas-wrap { position: relative; display: inline-flex; flex-shrink: 0; }
.top-brand-btn { display: inline-flex; align-items: center; gap: 10px; height: 36px; padding: 0 12px; background: transparent; border: none; border-radius: 8px; cursor: pointer; color: var(--text); transition: background .12s ease; }
.top-brand-btn:hover { background: var(--bg-hover); }
.top-brand-btn:active, .top-brand-btn.open { background: var(--bg-active); }
.apps-ic { color: var(--text-3); flex-shrink: 0; }
.top-brand-btn .logo { width: 26px; height: 26px; object-fit: contain; border-radius: 6px; display: block; flex-shrink: 0; }
.product-name { font-family: var(--font-heading); font-size: var(--fs-200); line-height: var(--lh-200); font-weight: var(--fw-bold); color: var(--text); letter-spacing: -.2px; display: inline-flex; align-items: center; white-space: nowrap; }
.product-x { color: var(--accent); font-weight: 800; margin: 0 8px; font-family: var(--font-heading); font-size: var(--fs-200); font-style: italic; letter-spacing: 0; }
.tas-pop { position: absolute; top: calc(100% + 6px); left: 6px; z-index: 60; min-width: 220px; padding: 8px; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 12px 36px rgba(0,0,0,.14); }
.tas-item { width: 100%; display: flex; align-items: center; gap: 12px; padding: 9px 10px; background: transparent; border: 0; border-radius: 8px; cursor: pointer; text-align: left; font-size: 14px; color: var(--text); }
.tas-item:hover { background: var(--bg-soft); }
.tas-ic { width: 18px; text-align: center; color: var(--text-3); }
.tas-ic.accent { color: var(--accent); }
.tas-label { flex: 1; }
.tas-item.active .tas-label { font-weight: 700; }
.tas-check { color: var(--accent); }
.tas-sep { height: 1px; background: var(--border-soft); margin: 6px 4px; }

.top-mid { flex: 1; min-width: 0; }
.search { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); width: 360px; height: 32px; background: var(--chip); border: 1px solid transparent; border-radius: 6px; display: flex; align-items: center; padding: 0 14px; gap: 10px; color: var(--text-2); font-size: 13px; cursor: pointer; transition: background .12s ease; }
.search:hover { background: var(--chip-hover); }

.top-right { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.top-upgrade { border: none; background: linear-gradient(90deg, var(--accent), var(--warn)); color: #fff; font-size: 12px; font-weight: var(--fw-bold); padding: 7px 14px; border-radius: 999px; cursor: pointer; white-space: nowrap; flex-shrink: 0; margin-right: 4px; transition: filter .12s ease; }
.top-upgrade:hover { filter: brightness(1.06); }
.ic-btn { width: 32px; height: 32px; border: none; background: transparent; color: var(--text-3); border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; transition: background .12s ease, color .12s ease; }
.ic-btn:hover { background: var(--bg-hover); color: var(--text); }
.ic-btn.active { background: var(--accent-soft); color: var(--accent); }

.um-wrap { position: relative; display: inline-flex; }
.user-chip { position: relative; width: 32px; height: 32px; border: none; background: transparent; cursor: pointer; padding: 0; margin-left: 4px; }
.user-chip .avatar { width: 28px; height: 28px; border-radius: 50%; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-weight: 600; font-size: 13px; line-height: 1; }
.user-chip.open .avatar { box-shadow: 0 0 0 2px var(--accent); }
.user-chip:hover .avatar { filter: brightness(1.05); }
.online-dot { position: absolute; right: 0; bottom: 0; width: 10px; height: 10px; border-radius: 50%; background: var(--ok); border: 2px solid var(--bg-soft); }
/* max-height+滚动:切换账号列表多于一屏时菜单会超出视口,底部「退出登录」被遮挡且滚不到(负责人报的) */
.um-pop { position: absolute; top: calc(100% + 8px); right: 0; z-index: 60; width: 280px; padding: 8px; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 12px 36px rgba(0,0,0,.14); max-height: calc(100vh - 72px); overflow-y: auto; overscroll-behavior: contain; }
.um-head { display: flex; align-items: center; gap: 10px; padding: 8px; }
.um-ava { width: 38px; height: 38px; border-radius: 9px; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 15px; font-weight: 600; }
.um-name { font-size: 14px; font-weight: 700; word-break: break-all; }
.um-handle { font-size: 11px; color: var(--text-3); margin-top: 2px; word-break: break-all; }
.um-online { color: var(--ok); }
.um-sep { height: 1px; background: var(--border-soft); margin: 6px 4px; }
.um-item { width: 100%; display: flex; align-items: center; gap: 10px; padding: 8px; background: transparent; border: 0; border-radius: 8px; cursor: pointer; text-align: left; font-size: 14px; color: var(--text-2); }
.um-item:hover { background: var(--bg-soft); color: var(--text); }
.um-ic { width: 18px; text-align: center; }
.um-item.danger { color: var(--danger); }
/* 切换账号 */
.um-label { font-size: 11px; color: var(--text-3); padding: 4px 8px 2px; }
.um-acct { gap: 8px; }
.um-acct-ava { width: 22px; height: 22px; flex-shrink: 0; border-radius: 50%; background: var(--accent); color: #fff; font-size: 11px; display: flex; align-items: center; justify-content: center; }
.um-acct-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.add-acct-back { align-self: flex-start; border: none; background: transparent; color: var(--accent); font-size: 13px; cursor: pointer; padding: 0 0 8px; }
.um-item.danger:hover { background: #fdecec; }

/* ──── 主体（flex，浮卡靠 margin + 缝隙露灰底）──── */
.body { flex: 1; display: flex; min-height: 0; background: var(--bg-soft); }
.body.focused .main { margin: 8px; }

/* WorkspaceRail */
.ws-rail { width: var(--ws-rail-w); background: var(--bg-soft); display: flex; flex-direction: column; align-items: center; padding: 12px 0; gap: 8px; flex-shrink: 0; }
.ws-icon { width: 40px; height: 40px; border-radius: 10px; background: var(--chip); border: 2px solid transparent; display: flex; align-items: center; justify-content: center; font-family: var(--font-heading); font-weight: var(--fw-bold); color: var(--text); cursor: pointer; font-size: 13px; line-height: 1; letter-spacing: -.5px; user-select: none; transition: background .12s ease, border-color .12s ease, box-shadow .12s ease, color .12s ease; }
.ws-icon:hover { background: var(--chip-hover); }
.ws-icon.active { background: var(--bg-panel); color: var(--text); border-color: var(--ws-active); box-shadow: 0 0 0 2px var(--ws-active-soft); }
.ws-icon.has-img { background: var(--bg-panel); overflow: hidden; padding: 0; }
.ws-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.ws-icon.plus { color: var(--text-3); font-size: 18px; border-style: dashed; border-color: var(--border); background: transparent; }
.ws-icon.plus:hover { border-color: var(--text-3); background: var(--bg-hover); }
.ws-sep { width: 24px; height: 1px; background: var(--border); margin-top: auto; flex-shrink: 0; }
.ws-icon.ws-tool { background: transparent; color: var(--text-3); font-size: 16px; }
.ws-icon.ws-tool:hover { background: var(--bg-hover); color: var(--text); }

/* ChannelSidebar（浮卡）*/
.channels { width: var(--channels-w); background: var(--bg-side); border: none; border-radius: 12px; margin: 8px 0 8px 8px; overflow: hidden; display: flex; flex-direction: column; flex-shrink: 0; }
.cs-ws-head { display: flex; align-items: center; padding: 8px 8px 8px 14px; gap: 6px; height: 48px; flex-shrink: 0; }
.cs-ws-name { flex: 1; display: inline-flex; align-items: center; gap: 6px; background: transparent; border: none; padding: 4px 6px; border-radius: 6px; cursor: pointer; text-align: left; min-width: 0; }
.cs-ws-name:hover { background: var(--bg-hover); }
.cs-ws-name .name { font-family: var(--font-heading); font-size: var(--fs-200); line-height: var(--lh-200); font-weight: var(--fw-bold); color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cs-ws-name .chev { color: var(--text-3); flex-shrink: 0; }
.cs-add { width: 28px; height: 28px; background: transparent; border: none; color: var(--text-3); border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; }
.cs-add:hover { background: var(--bg-hover); color: var(--text); }
.cs-filter { display: flex; align-items: center; padding: 4px 8px 10px; gap: 6px; flex-shrink: 0; }
.cs-filter-funnel { width: 28px; height: 28px; background: transparent; border: none; color: var(--text-3); border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; }
.cs-filter-funnel:hover { background: var(--bg-hover); color: var(--text); }
.cs-filter-input { flex: 1; height: 28px; border: 1px solid var(--border); background: var(--bg-panel); border-radius: 6px; padding: 0 12px; font-size: 13px; font-family: var(--font-body); color: var(--text); outline: none; min-width: 0; }
.cs-filter-input:focus { border-color: var(--text-3); }
.cs-filter-input::placeholder { color: var(--text-dim); }
.cs-list { flex: 1; overflow-y: auto; padding: 0 8px 14px; }
.cs-group { margin-top: 8px; }
.cs-group-head { display: flex; align-items: center; gap: 6px; padding: 6px 8px; background: transparent; border: none; color: var(--text-3); font-size: 13px; font-weight: 500; cursor: pointer; width: 100%; text-align: left; border-radius: 6px; }
.cs-group-head:hover { background: var(--bg-hover); color: var(--text); }
.cs-group-head .caret { transition: transform .12s ease; flex-shrink: 0; }
.cs-group-head .caret.open { transform: rotate(90deg); }
.cs-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; margin: 1px 0; border-radius: 6px; cursor: pointer; color: var(--text-2); font-size: 14px; min-width: 0; position: relative; }
.cs-item:hover { background: var(--bg-hover); color: var(--text); }
.cs-item.active { background: var(--bg-panel); color: var(--text); font-weight: 600; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
.cs-item.active::before { content: ""; position: absolute; left: -4px; top: 6px; bottom: 6px; width: 3px; border-radius: 2px; background: var(--accent); }
.cs-ic { width: 18px; height: 18px; display: inline-flex; align-items: center; justify-content: center; color: var(--text-3); flex-shrink: 0; }
/* 频道彩色图标（按名字取色 + 代表字）*/
.cs-chan-av { width: 20px; height: 20px; border-radius: 6px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; color: #fff; font-size: 11px; font-weight: 700; line-height: 1; }
.cs-item.active .cs-chan-av { box-shadow: 0 0 0 1.5px rgba(255,255,255,.5); }
.cs-item.active .cs-ic { color: var(--text); }
.cs-label { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* 已归档专班频道：灰显（仍可点开查看留档），右侧 🗄 角标 */
.cs-item.archived { opacity: 0.5; }
.cs-item.archived:hover { opacity: 0.72; }
.cs-item.archived.active { opacity: 0.85; }
.cs-archived-tag { flex-shrink: 0; font-size: 12px; opacity: 0.8; }
/* 未归类组:计数小标 + 悬浮出现的「归入」按钮 */
.cs-orphan-n { margin-left: auto; font-size: 11px; color: var(--text-3); background: var(--bg-soft); border-radius: 999px; padding: 0 7px; }
.cs-adopt { flex-shrink: 0; display: none; border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-2); font-size: 11px; padding: 1px 8px; border-radius: 6px; cursor: pointer; }
.ch-row:hover .cs-adopt { display: inline-block; }
.cs-adopt:hover { color: var(--accent); border-color: var(--accent); }
/* 看板头数据源按钮（带数量角标）*/
.bs-srcbtn { position: relative; }
.bs-badge { position: absolute; top: -3px; right: -3px; min-width: 14px; height: 14px; padding: 0 3px; border-radius: 7px; background: var(--accent); color: #fff; font-size: 9px; line-height: 14px; text-align: center; font-weight: 700; }
.cs-empty { font-size: 12px; color: var(--text-3); padding: 6px 10px; }
.cs-add-row { color: var(--text-3); }
.cs-ic-box { width: 18px; height: 18px; border: 1px dashed var(--border); border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; color: var(--text-3); flex-shrink: 0; }
.cs-dm-av { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; flex-shrink: 0; position: relative; }
.cs-dm-av.bot { background: var(--text); border-radius: 6px; }
.dot-online { position: absolute; right: -2px; bottom: -2px; width: 8px; height: 8px; border-radius: 50%; background: var(--ok); border: 1.5px solid var(--bg-side); }

/* main（浮卡）*/
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; background: var(--bg); border-radius: 12px; margin: 8px; overflow: hidden; }
/* 数据看板滚动容器 */
/* 看板滚动容器：只允许纵向滚动。
   关键修复：CSS 规范里只要 overflow-y 设成 auto/scroll、而 overflow-x 仍是 visible，
   浏览器会把 overflow-x 也强制算成 auto——于是当内容比列略宽时整块就能被横向「拖移/平移」，
   造成用户看到的拖移 BUG。这里显式把 overflow-x 钉成 hidden，彻底禁掉横向拖动。 */
.board-scroll { flex: 1; overflow-y: auto; overflow-x: hidden; min-height: 0; }
/* 看板"一句话下达目标"hero（真发给中枢 AI）*/
/* 看板分组小标题：区分「社媒数据」与「平台运营」两组 KPI */
.board-group-h { display: flex; align-items: center; gap: 8px; font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); margin: 18px 2px 10px; }
/* 社媒区：没配数据源的空态 */
.board-empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 8px; padding: 36px 24px; background: var(--bg-panel); border: 1px dashed var(--border); border-radius: 14px; }
.board-empty-ic { font-size: 30px; }
.board-empty-t { font-size: var(--fs-150, 15px); font-weight: var(--fw-bold); color: var(--text); }
.board-empty-d { font-size: var(--fs-75, 12px); color: var(--text-3); max-width: 380px; line-height: 1.6; }
.board-empty-btn { margin-top: 6px; border: none; background: var(--accent); color: #fff; font-size: 13px; font-weight: var(--fw-bold); padding: 8px 18px; border-radius: 9px; cursor: pointer; }
/* 社媒区：每个数据源一张卡 */
.src-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }
.src-card { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; animation: kpi-in .5s both; }
.src-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.src-plat { font-size: 14px; font-weight: var(--fw-bold); color: var(--text); }
.src-mode { font-size: 11px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border); color: var(--text-dim, #888); }
.src-mode.api { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
.src-acc { font-size: 12px; color: var(--text-2); font-family: var(--font-mono, monospace); margin-top: 4px; word-break: break-all; }
.src-metrics { display: flex; gap: 16px; margin-top: 12px; }
.src-m { display: flex; flex-direction: column; gap: 2px; }
.src-m-l { font-size: 11px; color: var(--text-3); }
.src-m-v { font-size: 14px; font-weight: var(--fw-bold); color: var(--text-dim, #999); }
.src-status { margin-top: 12px; font-size: 11px; color: var(--text-3); padding-top: 8px; border-top: 1px dashed var(--border); }
.src-status.off { color: #b94a4a; }
@keyframes kpi-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
/* 「接入数据源」按钮：靠右，弱化描边样式，不抢 KPI 视觉 */
.board-src-btn { margin-left: auto; border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-2); font-size: 12px; font-weight: var(--fw-bold); padding: 5px 12px; border-radius: 8px; cursor: pointer; white-space: nowrap; }
.board-src-btn:hover { border-color: var(--accent); color: var(--accent); }
.board-group-tag { font-size: var(--fs-75, 11px); font-weight: var(--fw-bold); padding: 1px 8px; border-radius: 999px; background: var(--bg); border: 1px solid var(--border); color: var(--text-dim, #888); }
.board-group-tag.real { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
.board-ask { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; margin-bottom: 16px; }
.board-ask-h { font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); margin-bottom: 10px; }
.board-ask-row { display: flex; align-items: center; gap: 8px; }
.board-ask-mark { font-family: var(--font-mono, monospace); color: var(--accent); font-weight: var(--fw-bold); }
.board-ask-input { flex: 1; border: 1px solid var(--border); border-radius: 9px; padding: 9px 12px; font-size: var(--fs-100); color: var(--text); background: var(--bg); outline: none; }
.board-ask-input:focus { border-color: var(--accent); }
.board-ask-send { border: none; background: linear-gradient(90deg, var(--accent), var(--warn, #e0883a)); color: #fff; font-weight: var(--fw-bold); padding: 9px 18px; border-radius: 9px; cursor: pointer; white-space: nowrap; }
.board-ask-send:disabled { opacity: .55; cursor: default; }
.board-ask-tip { font-size: var(--fs-75); color: var(--text-3); margin-top: 8px; }
/* 任务看板 Kanban */
.kan-wrap { padding: 22px var(--content-pad-x) 32px; max-width: 1180px; margin: 0 auto; }
/* 项目/剧集进度条 */
.proj-strip { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
.proj-card { flex: 1 1 220px; min-width: 200px; text-align: left; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 13px; padding: 12px 14px; cursor: pointer; transition: border-color .14s ease, box-shadow .14s ease; }
.proj-card:hover { box-shadow: 0 3px 12px rgba(0,0,0,.07); }
.proj-card.active { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.proj-card.all { flex: 0 0 auto; min-width: 160px; background: var(--bg-soft); }
/* 已完成项目折叠区:入口卡淡绿提示,展开后的已完成卡整体淡化(它们不再是关注重点) */
.proj-fold { flex: 0 0 auto; min-width: 160px; background: var(--bg-soft); border-style: dashed; }
.proj-fold .proj-name { color: var(--ok, #4a8c5c); }
.proj-done { opacity: .62; }
.proj-done:hover, .proj-done.active { opacity: 1; }
.proj-name { font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); line-height: 1.4; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.proj-bar { height: 6px; background: var(--bg-soft); border-radius: 4px; margin: 10px 0 7px; overflow: hidden; }
.proj-bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--warn, #e0883a)); border-radius: 4px; transition: width .3s ease; }
.proj-meta { font-size: var(--fs-75); color: var(--text-3); }
.kan-tip { font-size: var(--fs-75); color: var(--text-3); margin: 0 0 18px; line-height: 1.5; background: var(--bg-soft); border-radius: 10px; padding: 10px 13px; }
.kanban { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; align-items: start; }
.kan-col { border: 1px solid var(--border); border-radius: 16px; padding: 6px 6px 12px; min-height: 220px; background: var(--bg-soft); }
.kan-col-h { display: flex; align-items: center; gap: 8px; font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); padding: 12px 12px 12px; }
.kan-col-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.kan-col-label { flex: 1; }
.kan-n { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 999px; min-width: 22px; text-align: center; padding: 1px 7px; font-size: var(--fs-75); color: var(--text-2); font-weight: var(--fw-bold); }
/* 每列主题色：圆点 + 顶部细色条 */
.kan-col { position: relative; overflow: hidden; }
.kan-col::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; }
.kan-todo::before { background: #9aa0a6; }
.kan-doing::before { background: var(--accent, #c96442); }
.kan-done::before { background: var(--ok, #6b8e4e); }
.kan-todo .kan-col-dot { background: #9aa0a6; }
.kan-doing .kan-col-dot { background: var(--accent, #c96442); }
.kan-done .kan-col-dot { background: var(--ok, #6b8e4e); }
.kan-cards { display: flex; flex-direction: column; gap: 10px; padding: 0 6px; }
.kan-card { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px; padding: 13px 14px; box-shadow: 0 1px 2px rgba(0,0,0,.04); transition: box-shadow .14s ease, transform .14s ease, border-color .14s ease; }
.kan-card:hover { box-shadow: 0 4px 14px rgba(0,0,0,.09); transform: translateY(-1px); border-color: color-mix(in srgb, var(--accent) 35%, var(--border)); }
.kan-card.done { opacity: .68; }
.kan-card.done .kan-title { text-decoration: line-through; text-decoration-color: var(--text-3); }
.kan-title { font-size: var(--fs-100); color: var(--text); line-height: 1.55; font-weight: 500; }
/* 截止时间徽章：中性=灰、快到期=橙、逾期=红 */
.kan-due { display: inline-flex; align-items: center; gap: 3px; margin-top: 7px; font-size: var(--fs-75); color: var(--text-2); background: var(--bg-soft); border-radius: 999px; padding: 2px 9px; }
.kan-due.soon { color: #8a5a10; background: #f7e3b8; }
.kan-due.overdue { color: #b23b3b; background: #f6d6d6; }
.kan-foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 11px; }
.kan-who { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-75); color: var(--text-2); background: var(--bg-soft); border-radius: 999px; padding: 2px 10px 2px 2px; }
.kan-who-ava { width: 19px; height: 19px; border-radius: 50%; background: var(--accent); color: #fff; font-size: 10px; font-weight: var(--fw-bold); display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
.kan-exec { font-size: var(--fs-75); color: var(--text-2); background: var(--bg-soft); border-radius: 999px; padding: 2px 9px; max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kan-prog { font-size: var(--fs-75); color: var(--accent); font-weight: var(--fw-bold); margin-left: auto; }
.kan-barwrap { height: 5px; background: var(--bg-soft); border-radius: 3px; margin-top: 10px; overflow: hidden; }
.kan-bar { height: 100%; background: linear-gradient(90deg, var(--accent), var(--warn, #e0883a)); border-radius: 3px; }
.kan-btns { display: flex; align-items: center; gap: 6px; margin-top: 12px; }
.kan-spacer { flex: 1; }
.kan-btn { border: 1px solid var(--border); background: var(--bg-soft); color: var(--text-2); font-size: var(--fs-75); padding: 5px 11px; border-radius: 8px; cursor: pointer; transition: filter .12s ease; }
.kan-btn.primary { border: none; background: var(--accent); color: #fff; font-weight: var(--fw-bold); }
.kan-btn:hover { filter: brightness(1.06); }
.kan-empty { font-size: var(--fs-75); color: var(--text-3); text-align: center; padding: 30px 0; display: flex; flex-direction: column; align-items: center; gap: 7px; }
.kan-empty-ic { font-size: 24px; opacity: .6; }
.pinned-item { color: var(--text-2); }
.board-sub { font-size: 13px; color: var(--text-3); font-family: var(--mono); }

/* ── 任务看板（kanban 三列）── */
/* 任务看板顶部剧集 Tab */
.prod-tabs { display: flex; gap: 6px; margin-left: 14px; flex-wrap: wrap; }
.prod-tab { display: inline-flex; align-items: center; gap: 6px; padding: 4px 9px 4px 5px; border: 1px solid var(--border); border-radius: 20px; background: transparent; color: var(--text-2); font-size: 12px; cursor: pointer; transition: background .12s, border-color .12s; }
.prod-tab:hover { background: var(--bg-hover); color: var(--text); }
.prod-tab.active { background: var(--bg-panel); color: var(--text); border-color: var(--accent); font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.prod-tab-av { width: 18px; height: 18px; border-radius: 5px; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; flex-shrink: 0; }
.prod-tab-n { font-size: 10px; color: var(--text-3); background: var(--bg-hover); border-radius: 8px; padding: 0 5px; min-width: 14px; text-align: center; }
.prod-tab.active .prod-tab-n { background: var(--accent); color: #fff; }
/* 剧集制作流水线卡 + 时间线 */
.show-band { flex: 1; min-height: 0; overflow-y: auto; padding: 12px var(--content-pad-x) 16px; }
/* 每集一个区块：流水线卡 + 这一集任务 */
.ep-block { margin-bottom: 20px; }
.ep-block .prod-card { margin-bottom: 8px; }
.ep-tasks { padding: 2px 0 0 6px; }
.tl-empty { font-size: 12px; color: var(--text-3); padding: 6px; }
/* 整部剧进度（分段条：每段一集，已完成绿 / 当前集橙 / 未做灰）*/
.series-bar { margin-bottom: 12px; }
.series-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.series-title { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 600; color: var(--text); }
.series-av { width: 20px; height: 20px; border-radius: 6px; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; }
.series-meta { font-size: 12px; color: var(--text-2); }
.series-segs { display: flex; gap: 3px; }
.series-seg { flex: 1; height: 8px; border-radius: 3px; background: var(--bg-hover); transition: background .3s; }
.series-seg.done { background: #6b8e4e; }
.series-seg.current { background: var(--accent); box-shadow: 0 0 0 2px rgba(217,105,47,.18); }
.prod-card { flex: 1 1 360px; min-width: 320px; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 14px; padding: 14px 18px; box-shadow: 0 4px 14px rgba(0,0,0,.05); }
.prod-card.clickable { cursor: pointer; transition: box-shadow .15s, transform .15s, border-color .15s; }
.prod-card.clickable:hover { box-shadow: 0 8px 22px rgba(0,0,0,.1); transform: translateY(-2px); border-color: var(--accent); }
.prod-head { display: flex; align-items: center; gap: 9px; margin-bottom: 14px; }
.prod-av { width: 28px; height: 28px; border-radius: 8px; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 600; flex-shrink: 0; }
.prod-name { font-size: 15px; font-weight: 600; color: var(--text); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prod-status { margin-left: auto; font-size: 11px; font-weight: 600; color: var(--accent); background: rgba(217,105,47,.12); padding: 3px 10px; border-radius: 20px; flex-shrink: 0; white-space: nowrap; }
.prod-pipe { display: flex; align-items: flex-start; margin-bottom: 14px; }
.prod-step { display: flex; flex-direction: column; align-items: center; gap: 5px; flex-shrink: 0; }
.prod-dot { width: 26px; height: 26px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; background: var(--bg-hover); color: var(--text-3); }
.prod-step-label { font-size: 11px; color: var(--text-3); }
.prod-step.done .prod-dot { background: #6b8e4e; color: #fff; }
.prod-step.done .prod-step-label { color: #6b8e4e; }
.prod-step.current .prod-dot { background: var(--accent); color: #fff; box-shadow: 0 0 0 4px rgba(217,105,47,.18); }
.prod-step.current .prod-step-label { color: var(--accent); font-weight: 600; }
.prod-conn { flex: 1; height: 2px; background: var(--border); margin: 12px 4px 0; border-radius: 1px; }
.prod-conn.on { background: #6b8e4e; }
.prod-bar { height: 7px; border-radius: 6px; background: var(--bg-hover); overflow: hidden; margin-bottom: 9px; }
.prod-bar-fill { height: 100%; border-radius: 6px; transition: width .3s ease; }
.prod-foot { display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--text-3); }
.prod-assignee { display: inline-flex; align-items: center; gap: 5px; }
.prod-a-av { width: 18px; height: 18px; border-radius: 50%; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 9px; flex-shrink: 0; }
.show-tl { display: flex; flex-direction: column; padding-left: 3px; }
.tl-row { display: flex; align-items: center; gap: 10px; padding: 5px 0 5px 18px; position: relative; font-size: 13px; }
.tl-row::before { content: ''; position: absolute; left: 5px; top: 0; bottom: 0; width: 2px; background: var(--border); }
.tl-row:first-child::before { top: 50%; }
.tl-row:last-child::before { bottom: 50%; }
.tl-dot { position: absolute; left: 0; width: 12px; height: 12px; border-radius: 50%; background: var(--text-3); box-shadow: 0 0 0 3px var(--bg-soft); }
.tl-row.done .tl-dot { background: #6b8e4e; }
.tl-row.in_progress .tl-dot { background: var(--accent); }
.tl-name { color: var(--text); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tl-row.done .tl-name { color: var(--text-3); text-decoration: line-through; }
.tl-meta { font-size: 11px; color: var(--text-3); flex-shrink: 0; }
/* 单集甘特弹窗 */
.gantt-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,.32); display: flex; align-items: center; justify-content: center; }
.gantt-modal { width: 640px; max-width: calc(100vw - 48px); background: var(--bg-panel); border-radius: 14px; box-shadow: 0 24px 64px rgba(0,0,0,.22); padding: 18px 20px; }
.gantt-head { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.gantt-title { font-size: 15px; font-weight: 600; color: var(--text); }
.gantt-sub { font-size: 12px; color: var(--text-3); }
.gantt-close { margin-left: auto; width: 28px; height: 28px; border: none; background: transparent; color: var(--text-3); font-size: 20px; cursor: pointer; border-radius: 6px; }
.gantt-close:hover { background: var(--bg-hover); color: var(--text); }
.gantt-axis { display: flex; justify-content: space-between; padding-left: 64px; margin-bottom: 8px; font-size: 10px; color: var(--text-3); }
.gantt-rows { display: flex; flex-direction: column; gap: 8px; }
.gantt-row { display: flex; align-items: center; gap: 8px; }
.gantt-stage { width: 56px; flex-shrink: 0; font-size: 12px; color: var(--text-3); text-align: right; }
.gantt-stage.done { color: #6b8e4e; }
.gantt-stage.current { color: var(--accent); font-weight: 600; }
.gantt-track { position: relative; flex: 1; height: 22px; background: var(--bg-hover); border-radius: 6px; }
.gantt-bar { position: absolute; top: 0; height: 22px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #fff; }
.gantt-bar.done { background: #6b8e4e; }
.gantt-bar.current { background: var(--accent); box-shadow: 0 0 0 3px rgba(217,105,47,.18); }
.gantt-bar.todo { background: var(--border); }
.gantt-foot { display: flex; align-items: center; gap: 8px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-2); }
.gantt-legend { margin-left: auto; display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-3); }
.gantt-legend .gl { width: 10px; height: 10px; border-radius: 3px; display: inline-block; margin-left: 8px; }
.gantt-legend .gl.done { background: #6b8e4e; }
.gantt-legend .gl.current { background: var(--accent); }
.gantt-legend .gl.todo { background: var(--border); }
/* 任务行可点 + 任务详情弹窗 */
.tl-row.clickable { cursor: pointer; border-radius: 6px; padding-right: 8px; }
.tl-row.clickable:hover { background: var(--bg-hover); }
.tl-chev { margin-left: 4px; color: var(--text-3); flex-shrink: 0; opacity: 0; transition: opacity .12s; }
.tl-row.clickable:hover .tl-chev { opacity: 1; }
.td-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,.32); display: flex; align-items: center; justify-content: center; }
.td-modal { width: 460px; max-width: calc(100vw - 48px); background: var(--bg-panel); border-radius: 14px; box-shadow: 0 24px 64px rgba(0,0,0,.22); padding: 18px 20px; }
.td-head { display: flex; align-items: center; gap: 9px; margin-bottom: 12px; }
.td-status-dot { width: 12px; height: 12px; border-radius: 50%; background: var(--text-3); flex-shrink: 0; }
.td-status-dot.done { background: #6b8e4e; }
.td-status-dot.in_progress { background: var(--accent); }
.td-title { font-size: 16px; font-weight: 600; color: var(--text); flex: 1; }
.td-meta-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
.td-chip { font-size: 12px; color: var(--text-2); background: var(--bg-hover); padding: 3px 10px; border-radius: 20px; }
.td-prog { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.td-prog-bar { flex: 1; height: 8px; border-radius: 6px; background: var(--bg-hover); overflow: hidden; }
.td-prog-fill { height: 100%; border-radius: 6px; background: var(--accent); }
.td-prog-fill.done { background: #6b8e4e; }
.td-prog-pct { font-size: 13px; font-weight: 600; color: var(--text-2); min-width: 38px; text-align: right; }
.td-detail { font-size: 13px; color: var(--text); line-height: 1.6; background: var(--bg-soft); border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; }
.td-steps-h { font-size: 12px; font-weight: 600; color: var(--text-2); margin-bottom: 8px; }
.td-step { display: flex; align-items: center; gap: 9px; padding: 5px 0; font-size: 13px; color: var(--text-3); }
.td-step-box { width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid var(--border); display: inline-flex; align-items: center; justify-content: center; font-size: 11px; color: #fff; flex-shrink: 0; }
.td-step.done .td-step-box { background: #6b8e4e; border-color: #6b8e4e; }
.td-step.done .td-step-label { color: var(--text); }
.ch-header { height: 50px; flex-shrink: 0; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; padding: 0 16px; background: var(--bg-panel); }
.ch-fav { width: 28px; height: 28px; background: transparent; border: none; color: var(--text-3); border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; }
.ch-fav:hover { background: var(--bg-hover); color: var(--text); }
.ch-fav.active { color: var(--warn); }
.title { font-family: var(--font-heading); font-size: var(--fs-200); line-height: var(--lh-200); font-weight: var(--fw-bold); display: flex; align-items: center; gap: 6px; color: var(--text); flex-shrink: 0; }
.title .hash { color: var(--text-3); font-weight: 400; }
.title-btn { display: inline-flex; align-items: center; gap: 4px; background: transparent; border: 0; cursor: pointer; padding: 3px 6px; margin-left: -6px; border-radius: 7px; }
.title-btn:hover { background: var(--bg-hover); }
.title-btn .chev { color: var(--text-3); }
.ch-av { width: 24px; height: 24px; border-radius: 7px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; color: #fff; font-size: 12px; font-weight: 700; line-height: 1; }
.ch-topic { font-size: 13px; color: var(--text-3); border-left: 1px solid var(--border); padding-left: 12px; margin-left: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 1; }
.ch-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.ch-members-btn { display: inline-flex; align-items: center; background: transparent; border: none; cursor: pointer; padding: 3px 6px; border-radius: 6px; transition: background .12s ease; }
.ch-members-btn:hover { background: var(--bg-hover); }
.ava-stack { display: flex; align-items: center; }
.ava-stack .a { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; border: 2px solid var(--bg-panel); margin-left: -6px; }
.ava-stack .a:first-child { margin-left: 0; }
.ava-stack .a.bot { background: var(--text); border-radius: 5px; }
.ch-members-count { font-size: 13px; color: var(--text-3); font-family: var(--mono); margin: 0 0 0 6px; }
.ch-ic-btn { width: 30px; height: 30px; background: transparent; border: none; color: var(--text-3); border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; transition: background .12s ease, color .12s ease; }
/* 私信「删除会话」按钮:悬停转警示红,提示这是移除性操作 */
.ch-ic-btn.dm-del:hover { color: #c0392b; background: rgba(192, 57, 43, 0.08); }
.ch-ic-btn:hover { background: var(--bg-hover); color: var(--text); }
.ch-ic-btn.active { background: var(--accent-soft); color: var(--accent); }

/* 消息流（Discord 风：分组 / 悬停高亮 / 工具条 / 反应 / 回复）*/
.stream { flex: 1; overflow-y: auto; padding: 8px var(--content-pad-x) 20px; }
/* 消息区滚动条**常驻可见**(负责人建议):全局滚动条是"滚动中才显形"(reset.css),
   静止时全透明——想快速拖拽长聊天记录时根本抓不到。仅此容器覆盖为常驻。
   ⚠️ 必须先把标准属性还原为 auto:reset.css 的 `*{scrollbar-width:thin}` 在
   Chrome 121+ 会让 ::-webkit-scrollbar 定制整个失效(标准属性优先),且 overlay
   模式下标准属性做不到常驻;还原后 webkit 伪元素接管=强制经典滚动条,占位+常驻。 */
.stream { scrollbar-width: auto; scrollbar-color: auto; }
.stream::-webkit-scrollbar { width: 10px; }
.stream::-webkit-scrollbar-track { background: transparent; }
.stream::-webkit-scrollbar-thumb {
  background-color: rgba(0, 0, 0, 0.22);
  border-radius: 5px;
  border: 2px solid transparent;
  background-clip: padding-box;
}
.stream::-webkit-scrollbar-thumb:hover { background-color: rgba(0, 0, 0, 0.38); }
.msg { display: flex; flex-direction: column; padding: 4px 10px; margin: 0 -10px; border-radius: 4px; position: relative; }
.msg:not(.grouped) { margin-top: 18px; }
/* 有回复的消息：上方再多留点空，给连接线腾出"空行" */
.msg:not(.grouped):has(.msg-reply) { margin-top: 22px; }
.msg:hover { background: var(--bg-soft); }
.msg.unread { background: var(--accent-soft); box-shadow: inset 3px 0 0 var(--accent); }
.msg-main { display: flex; gap: 12px; }
/* 左槽：固定头像宽度；分组内放悬停才显的时间 */
.msg-gutter { width: 36px; flex-shrink: 0; display: flex; justify-content: center; }
.msg .ava { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 14px; color: #fff; background: var(--text-3); position: relative; }
.msg-gutter { width: 40px; }
.msg.me .ava { background: var(--accent); color: #1a1300; }
.msg.bot .ava { background: var(--text); }
.msg.bot .ava::after { content: ""; position: absolute; bottom: -1px; right: -1px; width: 10px; height: 10px; border-radius: 50%; background: var(--accent); border: 2px solid var(--bg); }
.gutter-time { font-size: 10px; color: var(--text-dim); font-family: var(--mono); line-height: 22px; opacity: 0; }
.msg.grouped:hover .gutter-time { opacity: 1; }
.msg .msg-body { flex: 1; min-width: 0; }
.msg .head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 2px; }
.msg .name { font-weight: var(--fw-bold); font-size: var(--fs-100); color: var(--text); }
.app-tag { font-size: 9px; font-weight: 700; letter-spacing: .5px; color: #fff; background: var(--accent); border-radius: 3px; padding: 1px 4px; line-height: 1.2; }
.msg .time { font-size: var(--fs-75); color: var(--text-3); }
/* 日期分隔线 */
.day-sep { display: flex; align-items: center; gap: 12px; margin: 14px 6px 6px; }
.day-sep::before, .day-sep::after { content: ""; flex: 1; height: 1px; background: var(--border); }
.day-sep span { font-size: 11px; font-weight: 600; color: var(--text-3); font-family: var(--mono); }
.msg .text { color: var(--text); font-size: var(--fs-100); line-height: var(--lh-200); word-break: break-word; }
.edited { font-size: 11px; color: var(--text-dim); margin-left: 6px; }
/* 图片附件缩略图：限最大尺寸，圆角，点击开原图 */
.msg-img { display: inline-block; margin-top: 4px; border-radius: 10px; overflow: hidden; border: 1px solid var(--border); max-width: 360px; line-height: 0; }
.msg-img img { display: block; max-width: 100%; max-height: 320px; height: auto; object-fit: cover; cursor: zoom-in; }
/* 文件附件下载卡片 */
.msg-file { display: inline-flex; align-items: center; gap: 10px; margin-top: 4px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-panel); text-decoration: none; max-width: 320px; }
.msg-file:hover { background: var(--bg-hover); }
.msg-file-ic { color: var(--accent); flex-shrink: 0; display: inline-flex; }
.msg-file-meta { display: flex; flex-direction: column; min-width: 0; }
.msg-file-name { color: var(--text); font-size: var(--fs-100); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msg-file-size { color: var(--text-dim); font-size: 11px; }
/* 工具条上传中的小转圈 */
.tb-spin { width: 13px; height: 13px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: tb-spin .7s linear infinite; }
@keyframes tb-spin { to { transform: rotate(360deg); } }
/* @提及高亮 */
.text :deep(.mention), .ai-bubble :deep(.mention) { background: var(--accent-soft); color: var(--warn); border-radius: 4px; padding: 0 3px; font-weight: 600; }
/* 回复预览（整行浮在头像上方 · 弯角连接线 + ↩ + 名字上色 + 正文淡色）*/
.msg-reply { position: relative; display: flex; align-items: center; gap: 5px; font-size: 13px; line-height: 1.2; padding-left: 52px; margin-bottom: 7px; min-width: 0; color: var(--text-3); }
/* 连接线：从回复行中部下探到下方头像，顶部弧向右接到回复文字 */
.msg-reply::before { content: ""; position: absolute; left: 20px; top: 4px; bottom: -2px; width: 27px; border-left: 2px solid var(--border); border-top: 2px solid var(--border); border-top-left-radius: 8px; }
.reply-av { width: 16px; height: 16px; border-radius: 50%; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; color: #fff; font-size: 9px; font-weight: 700; line-height: 1; background: var(--text-3); }
.reply-av.bot { background: var(--text); }
.reply-name { font-weight: 600; flex-shrink: 0; }
.reply-name:hover { text-decoration: underline; cursor: pointer; }
.reply-app { font-size: 8px; font-weight: 700; letter-spacing: .4px; color: #fff; background: var(--accent); border-radius: 3px; padding: 0 3px; flex-shrink: 0; }
.reply-body { color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
/* 反应条 */
.reactions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; }
.rxn { display: inline-flex; align-items: center; gap: 4px; height: 24px; padding: 0 8px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg-panel); cursor: pointer; font-size: 13px; color: var(--text-2); }
.rxn b { font-size: 12px; }
.rxn:hover { border-color: var(--accent); }
.rxn.mine { background: var(--accent-soft); border-color: var(--accent); color: var(--warn); }
.rxn.add { padding: 0 7px; color: var(--text-3); }
/* 悬停工具条 */
.msg-tools { position: absolute; top: -12px; right: 12px; display: none; gap: 2px; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.1); padding: 2px; }
.msg:hover .msg-tools { display: flex; }
.msg-tools button { width: 28px; height: 26px; border: 0; background: transparent; border-radius: 6px; cursor: pointer; font-size: 14px; display: inline-flex; align-items: center; justify-content: center; color: var(--text-2); }
.msg-tools button:hover { background: var(--bg-hover); }
/* emoji 选择器 */
.emoji-pop { position: fixed; z-index: 120; width: 248px; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 12px 36px rgba(0,0,0,.16); padding: 8px; }
.emoji-grid { display: grid; grid-template-columns: repeat(8, 1fr); gap: 2px; max-height: 200px; overflow-y: auto; }
.emoji-cell { width: 28px; height: 28px; border: 0; background: transparent; border-radius: 6px; cursor: pointer; font-size: 17px; display: inline-flex; align-items: center; justify-content: center; }
.emoji-cell:hover { background: var(--bg-hover); }
/* 回复横幅 */
.dm-undeliverable { background: #fbeaea; border: 1px solid #e6b8b8; color: #a33; border-radius: 10px; padding: 8px 12px; font-size: 12px; line-height: 1.5; margin-bottom: 8px; }
.reply-bar { display: flex; align-items: center; gap: 8px; background: var(--bg-soft); border: 1px solid var(--border); border-bottom: 0; border-radius: 10px 10px 0 0; padding: 6px 12px; font-size: 12px; color: var(--text-3); }
.reply-bar-txt { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.reply-bar-txt b { color: var(--accent); }
.reply-bar-x { width: 22px; height: 22px; border: 0; background: transparent; border-radius: 6px; cursor: pointer; color: var(--text-3); font-size: 16px; line-height: 1; }
.reply-bar-x:hover { background: var(--bg-hover); color: var(--text); }
/* 消息里渲染出的 Markdown 元素 */
.text :deep(a), .ai-bubble :deep(a) { color: var(--info); text-decoration: underline; }
.text :deep(code.md-code), .ai-bubble :deep(code.md-code) { background: var(--bg-code); padding: 1px 5px; border-radius: 4px; font-family: var(--mono); font-size: 12.5px; }
.text :deep(pre.md-pre), .ai-bubble :deep(pre.md-pre) { background: var(--bg-code); padding: 10px 12px; border-radius: 8px; font-family: var(--mono); font-size: 12.5px; overflow-x: auto; margin: 6px 0; white-space: pre-wrap; word-break: break-word; }
/* L8：composer 工具条的 标题/引用/无序列表 现在能正常渲染 */
.text :deep(.md-h), .ai-bubble :deep(.md-h) { font-weight: 700; margin: 3px 0; }
.text :deep(.md-h1), .ai-bubble :deep(.md-h1) { font-size: 1.25em; }
.text :deep(.md-h2), .ai-bubble :deep(.md-h2) { font-size: 1.15em; }
.text :deep(.md-h3), .ai-bubble :deep(.md-h3) { font-size: 1.05em; }
.text :deep(blockquote.md-quote), .ai-bubble :deep(blockquote.md-quote) { border-left: 3px solid var(--border); padding: 2px 0 2px 10px; margin: 3px 0; color: var(--text-dim); }
.text :deep(.md-li), .ai-bubble :deep(.md-li) { padding-left: 4px; }
.text :deep(strong), .ai-bubble :deep(strong) { font-weight: 700; }
.text :deep(del), .ai-bubble :deep(del) { opacity: .7; }
.rich { margin-top: 8px; border: 1px solid var(--border); background: var(--bg-panel); border-radius: 6px; padding: 14px 16px; }
.rich.info { border-left: 3px solid var(--info); }
.rich.team { border-left: 3px solid var(--accent); display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }
.rich.team .team-h { font-size: 13.5px; font-weight: 600; color: var(--text); line-height: 1.45; }
.rich.team .team-enter { border: none; background: var(--accent); color: #fff; padding: 6px 14px; border-radius: 8px; cursor: pointer; font-size: var(--fs-75, 12px); font-weight: 600; }
.rich .r-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.rich .r-head .t { font-weight: 600; font-size: 14px; }
.rich p { font-size: 13px; color: var(--text-3); margin: 4px 0 0; }
.rich .kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 14px; font-size: 13px; margin-top: 8px; }
.rich .kv .k { color: var(--text-3); }
.rich .kv .v { color: var(--text); font-weight: 500; text-align: right; }
.rich .kv .v.ai { color: var(--info); }
.rich .kv .v.human { color: var(--warn); }

/* Composer */
.composer { position: relative; flex-shrink: 0; padding: 8px var(--content-pad-x) 14px; background: var(--bg); }
.composer-box { border: 1px solid var(--border); border-radius: 12px; background: var(--bg-panel); overflow: hidden; transition: border-color .12s ease, box-shadow .12s ease; }
/* ── @ 补全面板(停靠在整个 composer 上方;composer-box 有 overflow:hidden 不能挂里面) ── */
.mention-pop {
  position: absolute; bottom: calc(100% + 6px); left: 14px; z-index: 60;
  min-width: 260px; max-width: 360px; max-height: 264px; overflow-y: auto;
  background: var(--bg-panel); border: 1px solid var(--border); border-radius: 10px;
  box-shadow: 0 10px 32px rgba(0, 0, 0, 0.16); padding: 4px;
}
.mention-item {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 6px 8px; border: none; background: transparent; border-radius: 7px;
  cursor: pointer; text-align: left;
}
.mention-item.active { background: var(--bg-hover); }
.mention-ava {
  width: 22px; height: 22px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-soft); color: var(--text-2); font-size: 10px; font-weight: 700;
}
.mention-ava.agent { background: var(--accent); color: #fff; }
.mention-name { font-size: 13px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mention-sub { margin-left: auto; font-size: 11px; color: var(--text-3); flex-shrink: 0; }
.composer-box:focus-within { border-color: var(--ws-active); box-shadow: 0 0 0 3px var(--ws-active-soft); }
.composer textarea { width: 100%; border: none; background: transparent; outline: none; resize: none; font-family: var(--font-body); font-size: 14px; color: var(--text); min-height: 38px; line-height: 1.55; padding: 10px 14px 4px; display: block; }
.composer textarea::placeholder { color: var(--text-dim); }
.composer-toolbar { display: flex; align-items: center; padding: 4px 6px; gap: 2px; }
.tb-left, .tb-right { display: flex; align-items: center; gap: 1px; }
.tb-right { margin-left: auto; }
.tb-btn { background: transparent; border: none; color: var(--text-3); width: 28px; height: 28px; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; font-size: 13px; }
.tb-btn:hover { background: var(--bg-hover); color: var(--text); }
.tb-heading { font-weight: 700; font-family: var(--font-heading); font-size: 14px; }
.tb-sep { width: 1px; height: 16px; background: var(--border); margin: 0 4px; }
.tb-btn.tb-ai { width: auto; padding: 0 8px; gap: 4px; color: var(--accent); font-weight: var(--fw-bold); font-size: 12px; }
.tb-btn.tb-ai:hover { background: var(--accent-soft); color: var(--accent); }
.send { background: var(--accent); color: #fff; border: none; width: 28px; height: 28px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; margin-left: 4px; transition: background .12s ease, opacity .12s ease; }
.send:hover { background: var(--warn); }
.send:disabled { background: var(--border); color: var(--text-dim); cursor: not-allowed; opacity: .7; }

/* ──── 右侧中枢 AI 面板（浮卡）──── */
.ai-panel { width: var(--right-w-ai, 360px); flex-shrink: 0; background: var(--bg-panel); display: flex; flex-direction: column; border-radius: 12px; margin: 8px 0; overflow: hidden; }
.ai-head { height: 50px; flex-shrink: 0; padding: 0 14px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid var(--border-soft); }
.ai-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 4px rgba(22,163,74,.16); flex-shrink: 0; }
.ai-title { font-family: var(--font-heading); font-size: var(--fs-200); line-height: var(--lh-200); font-weight: var(--fw-bold); color: var(--text); }
/* 输入框上方的作用域提示条(可关闭,关闭后记住):全局助理≠本频道 AI */
.ai-scope-tip { display: flex; align-items: center; gap: 6px; margin: 0 12px 6px; padding: 6px 10px; border-radius: 8px; background: var(--bg-soft); border: 1px solid var(--border); font-size: 11px; color: var(--text-3); line-height: 1.4; }
.ai-scope-tip-x { margin-left: auto; flex-shrink: 0; border: none; background: transparent; color: var(--text-3); font-size: 14px; cursor: pointer; padding: 0 2px; border-radius: 4px; }
.ai-scope-tip-x:hover { color: var(--text); background: var(--bg-hover); }
.ai-head-actions { margin-left: auto; display: flex; align-items: center; gap: 2px; }
.ai-ic-btn { width: 30px; height: 30px; background: transparent; border: none; color: var(--text-3); border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
.ai-ic-btn:hover { background: var(--bg-hover); color: var(--text); }
.ai-body { flex: 1; overflow-y: auto; padding: 12px 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.ai-msg { display: flex; }
.ai-msg.mine { justify-content: flex-end; }
.ai-bubble { max-width: 86%; background: #fff; border: 1px solid var(--border-soft); padding: 9px 12px; border-radius: 12px; font-size: 14px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; color: var(--text); }
.ai-msg.mine .ai-bubble { background: #fde7c2; border: 0; }
/* ③ "正在输入…"气泡：三个点循环跳动 */
.ai-bubble.typing { display: inline-flex; gap: 4px; align-items: center; padding: 11px 14px; }
.ai-bubble.typing .td { width: 6px; height: 6px; border-radius: 50%; background: var(--text-3); opacity: 0.5; animation: ai-typing 1.2s infinite ease-in-out; }
.ai-bubble.typing .td:nth-child(2) { animation-delay: 0.2s; }
.ai-bubble.typing .td:nth-child(3) { animation-delay: 0.4s; }
@keyframes ai-typing { 0%, 60%, 100% { transform: translateY(0); opacity: 0.4; } 30% { transform: translateY(-4px); opacity: 0.9; } }
.ai-composer { flex-shrink: 0; padding: 10px 14px 14px; }
.ai-input-box { border: 1px solid var(--border); border-radius: 12px; background: var(--bg); padding: 8px 8px 4px 12px; transition: border-color .12s ease, box-shadow .12s ease; }
.ai-input-box:focus-within { border-color: var(--ws-active); box-shadow: 0 0 0 3px var(--ws-active-soft); }
.ai-input-box input { width: 100%; border: none; outline: none; background: transparent; font-family: var(--font-body); font-size: 14px; color: var(--text); padding: 2px 4px; }
.ai-input-box input::placeholder { color: var(--text-dim); }
.ai-toolbar { display: flex; align-items: center; margin-top: 4px; padding-top: 4px; }
.ai-tb-left { display: flex; align-items: center; gap: 1px; }
.ai-tb-btn { width: 28px; height: 28px; background: transparent; border: none; color: var(--text-3); border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
.ai-tb-btn:hover { background: var(--bg-hover); color: var(--text); }
.ai-send-ic { margin-left: auto; background: var(--accent); color: #fff; border: none; width: 28px; height: 28px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; transition: background .12s ease, opacity .12s ease; }
.ai-send-ic:hover { background: var(--warn); }
.ai-send-ic:disabled { background: var(--border); color: var(--text-dim); cursor: not-allowed; opacity: .7; }

/* ════════ 中枢 AI · 放大态（Cowork 式全屏弹窗）════════ */
/* 半透明遮罩：盖住整页，点空白处还原 */
.ai-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.38); z-index: 79; animation: ai-bd-in .16s ease; }
@keyframes ai-bd-in { from { opacity: 0; } to { opacity: 1; } }

/* 放大态：脱离 dock、近全屏居中 */
.ai-panel.maximized {
  position: fixed; top: 2.5vh; bottom: 2.5vh; left: 2.5vw; right: 2.5vw;
  width: auto; height: auto; margin: 0; z-index: 80;
  border-radius: 14px;
  box-shadow: 0 24px 64px rgba(0,0,0,.22), 0 4px 12px rgba(0,0,0,.10), 0 0 0 1px var(--border);
}

/* 主体容器：默认单列（中栏吃满）；放大态横向三栏 */
.ai-main { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.ai-center { flex: 1; min-height: 0; min-width: 0; display: flex; flex-direction: column; }
.ai-panel.maximized .ai-main { flex-direction: row; }
.ai-panel.maximized .ai-center { border-left: 1px solid var(--border); border-right: 1px solid var(--border); }

/* —— 左导航栏（Chat/Cowork/Code → ＋新任务 → 项目/产物/定时/派发 → 最近 → 用户）—— */
.ai-cw-left { width: 248px; flex-shrink: 0; display: flex; flex-direction: column; padding: 12px 10px; background: var(--bg-soft); overflow: hidden; }
.ai-cw-tabs { display: flex; gap: 2px; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 10px; padding: 3px; margin-bottom: 12px; }
.ai-cw-tab { flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 5px; padding: 6px 4px; border: none; background: transparent; color: var(--text-3); font-family: var(--font-body); font-size: var(--fs-75); font-weight: var(--fw-bold); border-radius: 7px; cursor: pointer; transition: background .12s ease, color .12s ease; }
.ai-cw-tab:hover { color: var(--text); }
.ai-cw-tab.active { background: var(--bg-panel); color: var(--text); box-shadow: 0 1px 2px rgba(0,0,0,.06); }
.ai-cw-tab svg { flex-shrink: 0; }
.ai-cw-newtask { display: inline-flex; align-items: center; gap: 7px; width: 100%; padding: 9px 12px; background: var(--accent); color: #fff; border: none; border-radius: 9px; font-family: var(--font-body); font-size: var(--fs-100); font-weight: var(--fw-bold); cursor: pointer; margin-bottom: 10px; transition: filter .12s ease; }
.ai-cw-newtask:hover { filter: brightness(1.05); }
.ai-cw-nav { display: flex; flex-direction: column; gap: 1px; margin-bottom: 8px; }
.ai-cw-navitem { display: inline-flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border: none; background: transparent; color: var(--text-2); font-family: var(--font-body); font-size: var(--fs-100); border-radius: 8px; cursor: pointer; text-align: left; transition: background .12s ease, color .12s ease; }
.ai-cw-navitem:hover { background: var(--bg-hover); color: var(--text); }
.ai-cw-navitem svg { flex-shrink: 0; color: var(--text-3); }
.ai-cw-beta { margin-left: auto; font-size: 9px; font-weight: var(--fw-bold); color: var(--accent); background: var(--accent-soft); padding: 1px 6px; border-radius: 6px; letter-spacing: .5px; }
.ai-cw-recents { flex: 1; min-height: 0; display: flex; flex-direction: column; border-top: 1px solid var(--border-soft); padding-top: 10px; }
.ai-cw-recents-h { display: flex; align-items: center; justify-content: space-between; font-size: var(--fs-75); color: var(--text-3); font-family: var(--font-mono); text-transform: uppercase; letter-spacing: 1.5px; padding: 0 6px 6px; }
.ai-cw-recents-h svg { cursor: pointer; }
.ai-cw-list { list-style: none; margin: 0; padding: 0; flex: 1; min-height: 0; overflow-y: auto; }
.ai-cw-list li { padding: 8px 10px; border-radius: 6px; font-size: var(--fs-100); color: var(--text-2); cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ai-cw-list li:hover { background: var(--bg-hover); color: var(--text); }
.ai-cw-list li.act { background: var(--bg-panel); color: var(--text); font-weight: var(--fw-bold); box-shadow: inset 3px 0 0 var(--accent); }
/* 会话行：标题占满 + 悬停才露删除按钮（复用 .ai-cw-list li 的基础样式，这里改成 flex）*/
.ai-cw-list li.ai-recent-li { display: flex; align-items: center; gap: 6px; }
.ai-recent-t { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ai-recent-del { flex-shrink: 0; opacity: 0; border: none; background: transparent; color: var(--text-3); cursor: pointer; padding: 2px; border-radius: 4px; display: inline-flex; transition: opacity .12s ease, color .12s ease, background .12s ease; }
.ai-cw-list li.ai-recent-li:hover .ai-recent-del { opacity: 1; }
.ai-recent-del:hover { background: var(--bg-hover); color: var(--danger, #d9534f); }
.ai-recents-empty { color: var(--text-3); font-size: var(--fs-75); padding: 8px 10px; cursor: default; }
.ai-recents-empty:hover { background: transparent; color: var(--text-3); }
.ai-cw-user { display: flex; align-items: center; gap: 9px; margin-top: 8px; padding: 8px 10px; border-top: 1px solid var(--border-soft); border-radius: 8px; cursor: pointer; }
.ai-cw-user:hover { background: var(--bg-hover); }
.ai-cw-user-ava { width: 26px; height: 26px; flex-shrink: 0; border-radius: 50%; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: var(--fs-75); font-weight: var(--fw-bold); }
.ai-cw-user-nm { font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ai-cw-user-plan { font-size: 10px; color: var(--text-3); border: 1px solid var(--border); border-radius: 6px; padding: 0 5px; flex-shrink: 0; }
.ai-cw-user > svg { margin-left: auto; color: var(--text-3); flex-shrink: 0; }

/* —— 右栏：进度 + 项目文件 —— */
.ai-cw-right { width: 300px; flex-shrink: 0; display: flex; flex-direction: column; padding: 14px 12px; background: var(--bg-panel); overflow-y: auto; }
.ai-cw-sec { margin-bottom: 18px; }
.ai-cw-sec-h { font-size: var(--fs-75); color: var(--text-3); font-family: var(--font-mono); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; padding: 0 4px; }
.ai-cw-sec-h.with-meta { display: flex; justify-content: space-between; }
.ai-cw-meta { color: var(--accent); font-weight: var(--fw-bold); }
.ai-cw-progress, .ai-cw-files { list-style: none; margin: 0; padding: 0; }
.ai-cw-empty { font-size: var(--fs-75, 12px); color: var(--text-3); line-height: 1.6; padding: 6px 4px; }
.ai-cw-progress li { display: flex; align-items: center; gap: 8px; padding: 5px 4px; font-size: var(--fs-100); color: var(--text-2); position: relative; padding-left: 26px; }
.ai-cw-progress li::before { content: ""; position: absolute; left: 4px; top: 50%; transform: translateY(-50%); width: 14px; height: 14px; border-radius: 50%; border: 1.5px solid var(--text-dim); }
.ai-cw-progress li.done { color: var(--text-3); text-decoration: line-through; }
.ai-cw-progress li.done::before { background: var(--ok); border-color: var(--ok); }
.ai-cw-progress li.done::after { content: ""; position: absolute; left: 7.5px; top: 50%; width: 7px; height: 4px; border-left: 2px solid #fff; border-bottom: 2px solid #fff; transform: translateY(-65%) rotate(-45deg); }
.ai-cw-progress li.in { color: var(--accent); font-weight: var(--fw-bold); }
.ai-cw-progress li.in::before { border-color: var(--accent); background: var(--accent-soft); }
.ai-cw-proj-h { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding: 0 4px; }
.ai-cw-proj-nm { font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); }
.ai-cw-proj-h svg { color: var(--text-3); }
.ai-cw-manage {
  border: 1px solid var(--border); background: transparent; color: var(--text-2);
  padding: 2px 10px; border-radius: 999px; cursor: pointer; font-size: var(--fs-75);
  transition: background 0.12s ease, color 0.12s ease;
}
.ai-cw-manage:hover { background: var(--bg-soft); color: var(--text); }
.ai-cw-files li { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; font-size: var(--fs-100); color: var(--text-2); cursor: pointer; }
.ai-cw-files li:hover { background: var(--bg-hover); color: var(--text); }
.ai-cw-files li .ic { width: 16px; text-align: center; flex-shrink: 0; }

/* ──── 右侧插件竖栏（40 宽，pr-icon 32 圆形）──── */
.plugin-rail { width: var(--plugin-rail-w); background: var(--bg-soft); display: flex; flex-direction: column; align-items: center; padding: 10px 0; gap: 8px; flex-shrink: 0; }
.pr-list { display: flex; flex-direction: column; align-items: center; gap: 8px; flex: 1; overflow-y: auto; width: 100%; }
.pr-icon { width: 32px; height: 32px; border-radius: 50%; background: var(--chip); border: none; display: flex; align-items: center; justify-content: center; font-weight: var(--fw-bold); color: var(--text); cursor: pointer; position: relative; font-size: 11px; line-height: 1; flex-shrink: 0; user-select: none; transition: transform .12s ease, background .12s ease, color .12s ease, box-shadow .12s ease; }
.pr-icon:hover { background: var(--chip-hover); }
.pr-icon.active { background: var(--ws-active); color: #fff; }
.pr-icon.active::after { content: ""; position: absolute; left: -9px; top: 4px; bottom: 4px; width: 2px; border-radius: 2px; background: var(--text); }
.pr-icon.plus { background: transparent; border: 2px dashed var(--border); color: var(--text-3); font-size: 16px; }
.pr-icon.plus:hover { background: var(--bg-hover); border-color: var(--text-3); color: var(--text); }
.pr-icon.assets, .pr-icon.gear { color: var(--text-3); font-size: 16px; background: transparent; }
.pr-icon.assets:hover { background: var(--accent-soft); color: var(--accent); }
.pr-icon.gear:hover { background: var(--bg-hover); color: var(--text); }
.pr-divider { width: 18px; height: 1px; background: var(--border); margin: 4px 0; }

/* ──── 新建工作区弹窗 ──── */
.nw-overlay { position: fixed; inset: 0; z-index: 120; background: rgba(20,18,15,.35); display: flex; align-items: center; justify-content: center; animation: toast-in .12s ease; }
.nw-modal { width: 440px; max-width: 92vw; max-height: 88vh; overflow-y: auto; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 14px; padding: 22px; box-shadow: 0 24px 64px rgba(0,0,0,.22); }
.nw-title { font-family: var(--font-heading); font-size: 18px; font-weight: 700; color: var(--text); }
.nw-sub { font-size: 12px; color: var(--text-3); margin: 6px 0 14px; line-height: 1.5; }
.nw-field-label { font-size: 12px; color: var(--text-3); margin: 12px 0 6px; }
.nw-hint { font-size: 11px; color: var(--text-dim); margin-left: 4px; }
.nw-types { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.nw-type { height: 34px; border: 1px solid var(--border); border-radius: 9px; background: var(--bg); color: var(--text-2); font-size: 13px; cursor: pointer; }
.nw-type:hover { background: var(--bg-hover); }
.nw-type.on { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 700; }
.nw-input { width: 100%; height: 40px; padding: 0 13px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); font-size: 14px; color: var(--text); outline: none; }
.nw-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.nw-textarea { height: auto; padding: 10px 13px; resize: vertical; font-family: var(--font-body); line-height: 1.5; }
.nw-row2 { display: grid; grid-template-columns: 1fr 1.4fr; gap: 12px; }
.nw-col { min-width: 0; }
.nw-vis { display: flex; gap: 6px; }
.nw-vis-btn { flex: 1; height: 40px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); color: var(--text-2); font-size: 12px; cursor: pointer; }
.nw-vis-btn:hover { background: var(--bg-hover); }
.nw-vis-btn.on { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 700; }
.nw-preview { margin-top: 14px; background: var(--bg-soft); border: 1px solid var(--border-soft); border-radius: 10px; padding: 12px 14px; }
.nw-prev-h { font-size: 11px; color: var(--text-3); font-family: var(--mono); letter-spacing: .08em; margin-bottom: 8px; }
.nw-prev-ws { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.nw-prev-ic { width: 24px; height: 24px; border-radius: 7px; background: var(--action); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
.nw-prev-ch { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); padding: 3px 0 3px 6px; }
.nw-prev-tip { font-size: 10px; color: var(--text-3); background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; padding: 0 6px; }
.nw-inline { display: flex; gap: 8px; }
.nw-inline .nw-input { flex: 1; }
.nw-inline .nw-btn { flex-shrink: 0; }
.nw-divider { height: 1px; background: var(--border-soft); margin: 16px 0 4px; }
.nw-check { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 13px; color: var(--text-2); cursor: pointer; }
.nw-check input { width: 15px; height: 15px; accent-color: var(--accent); }
.nw-warn { color: var(--warn); }
/* 社区服务器：开放加入 + 邀请链接 */
.ws-join { margin-top: 16px; border-top: 1px solid var(--border); padding-top: 14px; }
.ws-join-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.ch-del-warn { margin: 4px 0 10px; padding: 10px 12px; border: 1px solid #e6c34d; background: #fdf8e8; border-radius: 8px; font-size: 12.5px; line-height: 1.7; color: #6b5a1e; }
.ws-join-warn { margin-top: 10px; padding: 12px 14px; border: 1px solid #e3b6b0; background: #fdf3f1; border-radius: 10px; }
.ws-join-warn-title { font-weight: 700; font-size: 13px; margin-bottom: 6px; }
.ws-join-warn-list { margin: 0 0 10px; padding-left: 18px; font-size: 12.5px; line-height: 1.8; color: var(--text-2, #55504a); }
.ws-join-warn-actions { display: flex; gap: 8px; }
.ws-join-title { font-size: 13px; font-weight: 600; color: var(--text); }
.ws-join-sub { font-size: 12px; color: var(--text-3); margin-top: 2px; max-width: 340px; }
.ws-toggle { flex-shrink: 0; width: 42px; height: 24px; border-radius: 999px; border: none; background: var(--border); cursor: pointer; position: relative; transition: background .15s; }
.ws-toggle.on { background: #3a7a3a; }
.ws-toggle:disabled { opacity: .6; cursor: default; }
.ws-toggle-dot { position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%; background: #fff; transition: left .15s; }
.ws-toggle.on .ws-toggle-dot { left: 21px; }
.ws-join-link { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
.ws-join-link .nw-input { flex: 1; min-width: 0; font-size: 12px; font-family: ui-monospace, Menlo, monospace; }
.ws-join-link .nw-btn { flex-shrink: 0; white-space: nowrap; }
.ws-members-btn { width: 100%; margin-top: 12px; }
/* 成员与角色管理列表 */
.mmg-list { max-height: 44vh; overflow-y: auto; margin: 6px 0 4px; }
.mmg-row { display: flex; align-items: center; gap: 10px; padding: 8px 2px; border-bottom: 1px solid var(--border); }
.mmg-ava { flex-shrink: 0; width: 32px; height: 32px; border-radius: 50%; overflow: hidden; background: var(--accent); color: #fff; font-size: 13px; display: flex; align-items: center; justify-content: center; }
.mmg-ava img { width: 100%; height: 100%; object-fit: cover; }
.mmg-ava.bot { background: #4a7a8c; }
.mmg-info { flex: 1; min-width: 0; }
.mmg-name { font-size: 14px; color: var(--text); font-weight: 500; }
.mmg-you { font-size: 11px; color: var(--text-3); background: var(--accent-soft); border-radius: 4px; padding: 0 4px; margin-left: 6px; }
.mmg-role { font-size: 12px; color: var(--text-3); margin-top: 1px; }
.mmg-role.owner { color: #b58932; }
.mmg-role.admin { color: #3a7a3a; }
.mmg-ops { display: flex; gap: 6px; flex-shrink: 0; }
.nw-btn.sm { padding: 4px 10px; font-size: 12px; }
.mmg-empty { text-align: center; color: var(--text-3); padding: 20px; font-size: 13px; }
.mmg-section { font-size: 12px; color: var(--text-3); margin: 14px 0 4px; padding-top: 10px; border-top: 1px dashed var(--border); }
.mmg-ava.banned { background: #b94a4a; opacity: .75; }
.nw-note { margin-top: 14px; background: var(--accent-soft); border: 1px solid #f4e0bd; border-radius: 10px; padding: 10px 12px; font-size: 12px; line-height: 1.6; color: var(--text-2); }
.nw-mem-list { max-height: 200px; overflow-y: auto; border: 1px solid var(--border); border-radius: 10px; }
.nw-mem { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--border-soft); }
.nw-mem:last-child { border-bottom: 0; }
.nw-mem-av { width: 24px; height: 24px; border-radius: 7px; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.nw-mem-av.bot { background: var(--text); }
.nw-mem-name { flex: 1; font-size: 14px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nw-mem-tag { font-size: 10px; font-family: var(--mono); color: var(--accent); background: var(--accent-soft); border-radius: 8px; padding: 1px 7px; }
.nw-mem-tag.pending { background: #f4e9d0; color: #8a6d1a; }
.nw-mem-empty { font-size: 13px; color: var(--text-3); padding: 14px; text-align: center; }
.nw-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
/* 二级弹窗的「返回上一级」按钮：靠左，与右侧的 刷新/完成 分开 */
.mmg-back { margin-right: auto; }
.nw-btn { height: 36px; padding: 0 16px; border: 1px solid var(--border); border-radius: 9px; background: var(--bg-panel); color: var(--text-2); font-size: 14px; cursor: pointer; }
.nw-btn:hover { background: var(--bg-hover); color: var(--text); }
.nw-btn.primary { background: var(--accent); border-color: var(--accent); color: #1a1300; font-weight: 700; }
.nw-btn.primary:hover { filter: brightness(1.05); background: var(--accent); }
.nw-btn.primary:disabled { background: var(--border); border-color: var(--border); color: var(--text-dim); cursor: not-allowed; }
.nw-btn.danger { background: var(--danger); border-color: var(--danger); color: #fff; font-weight: 700; }
.nw-btn.danger:hover { filter: brightness(1.05); }
.nw-btn.danger-outline { background: transparent; border-color: var(--danger); color: var(--danger); }
.nw-btn.danger-outline:hover { background: #fdecec; }
.nw-foot-split { justify-content: space-between; }
.nw-foot-left, .nw-foot-right { display: flex; gap: 10px; }
.nw-avatar-row { display: flex; align-items: center; gap: 10px; }
.nw-avatar-prev { width: 44px; height: 44px; border-radius: 11px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; color: #fff; font-size: 15px; font-weight: 700; overflow: hidden; }
.nw-avatar-prev img { width: 100%; height: 100%; object-fit: cover; }

/* ──── toast ──── */
/* z-index 400:必须盖过各弹窗 overlay(协作人 210 等),否则弹窗里操作的报错被盖住看不见 */
.toast-host { position: fixed; right: 18px; bottom: 18px; z-index: 400; display: flex; flex-direction: column; gap: 10px; }
.toast { min-width: 220px; max-width: 320px; padding: 12px 14px; background: var(--bg-panel); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,.12); animation: toast-in .18s ease; }
.toast.warn { border-left-color: #c0392b; }
.toast.success { border-left-color: #2f7d4f; }
.toast-title { font-size: 14px; font-weight: 700; color: var(--text); }
.toast-msg { font-size: 12px; color: var(--text-3); margin-top: 3px; }
@keyframes toast-in { from { opacity: 0; transform: translateX(12px); } to { opacity: 1; transform: none; } }
</style>
