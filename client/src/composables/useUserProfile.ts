import { computed, reactive, ref, watch } from 'vue'
import {
  getMyProfile, saveMyProfile, myProfileInfo,
  getMyPresence, setMyPresence, type MyAiProfile,
  getMyPrefToggles, setMyPrefToggles,
} from '@/matrix/client'

/** 我的权限（可开关）*/
export interface UserPermission { label: string; desc?: string; enabled: boolean }
/** 可被他人 / AI 调用的我的数据 */
export interface ShareableDatum { label: string; value: string; shared: boolean }

// 身份（名/句柄/头像字）= 当前登录者本人，不再写死演示人物。打开设置时 refreshIdentity() 刷新。
const handle = ref('')
const user = reactive<{ name: string; avatar: string; color?: string; role: string }>({
  name: '我', avatar: '我', color: undefined, role: '',
})
let presenceLoadedFor = ''  // 已从 account data 载入过状态的账号 id（防重复载入把用户本次的选择冲掉）
function refreshIdentity() {
  const info = myProfileInfo()
  user.name = info.name || '我'
  user.avatar = (info.name || info.userId || '我').replace(/^@/, '')[0] || '我'
  user.role = ''
  handle.value = info.userId
  // 仅在**首次/切账号**时从 account data 回填状态——refreshIdentity 会被反复调用，若每次都读，
  // 会在 setAccountData 的 sync 回声到达前把用户刚选的「离开」冲回旧值（闪一下又变绿）。
  if (info.userId && info.userId !== presenceLoadedFor) {
    presenceLoadedFor = info.userId
    status.value = getMyPresence() as typeof status.value
    loadPrefToggles()  // 权限/可调用数据开关也按账号回填(刷新留存,负责人报的持久化缺失)
  }
}

/** 从 account data 回填「我的权限/可调用数据」开关(按 label 匹配;没存过的保持默认)。 */
let suppressPrefSave = false
function loadPrefToggles() {
  const saved = getMyPrefToggles()
  suppressPrefSave = true
  for (const p of permissions) {
    if (p.label in saved.perms) p.enabled = saved.perms[p.label]
  }
  for (const d of shareableData) {
    if (d.label in saved.share) d.shared = saved.share[d.label]
  }
  // 下一轮微任务再放开(watch 是异步 flush,同步置回会漏掉本次回填触发的那批)
  setTimeout(() => { suppressPrefSave = false }, 0)
}

/** 个人设置弹窗 */
export type UserSettingsTab = 'profile' | 'ai' | 'perms' | 'share'

// —— AI 偏好画像（About me / Outputs）：真实存取 cosmac DB（经 bot 端点）——
// 模块级单例：弹窗打开时 load 一次、保存时回写。
const aiProfile = reactive<MyAiProfile>({ about: '', style: '', extra: '', enabled: true })
const aiLoading = ref(false)
const aiSaving = ref(false)
const aiSavedTip = ref(false) // 保存成功后短暂显示「已保存」
const settingsVisible = ref(false)
const settingsTab = ref<UserSettingsTab>('profile')
const status = ref<'在线' | '忙碌' | '离开' | '隐身'>('在线')
// 四态 → 指示灯颜色（驱动右上角头像的状态点 + 菜单里的状态文字）
const STATUS_COLOR: Record<string, string> = {
  在线: '#61c554', 忙碌: '#e5544b', 离开: '#f4be4f', 隐身: '#9aa4b0',
}
const statusMeta = computed(() => ({
  label: status.value,
  color: STATUS_COLOR[status.value] || STATUS_COLOR['在线'],
}))
/** 改在线状态：更新本地 + 写 account data + 尽力推 Matrix presence（真正生效、刷新留存）。 */
function setStatus(s: '在线' | '忙碌' | '离开' | '隐身') {
  status.value = s
  void setMyPresence(s)
}

// 通用的权限/授权偏好开关（不绑定任何具体行业；后端持久化以后再接真值）。
const permissions = reactive<UserPermission[]>([
  { label: '内容对外发布终审', desc: '对外内容由我把关', enabled: true },
  { label: '定时 / 批量发布',   desc: '多渠道排期发布', enabled: true },
  { label: '数据看板查看',      desc: '运营数据汇总', enabled: true },
  { label: '授权 AI 代我起草初稿', desc: '文案、方案、周报初稿', enabled: true },
  { label: 'AI 对外动作需我确认',  desc: '发布 / 对外操作人工把关', enabled: true }
])

const shareableData = reactive<ShareableDatum[]>([
  { label: '我的待办状态', value: '任务进度', shared: true },
  { label: '我的数据看板指标', value: '看板指标', shared: true },
  { label: '我的日程 / 在线状态', value: '在线', shared: false },
  { label: '我的偏好记录', value: '近期', shared: false }
])

// 开关变动 → 防抖写 account data(负责人报:取消勾选刷新后又恢复——此前只有内存态)。
// 回填期 suppress,防止把刚读到的值又写一遍。
let prefSaveTimer: ReturnType<typeof setTimeout> | null = null
watch([permissions, shareableData], () => {
  if (suppressPrefSave) return
  if (prefSaveTimer) clearTimeout(prefSaveTimer)
  prefSaveTimer = setTimeout(() => {
    const perms: Record<string, boolean> = {}
    for (const p of permissions) perms[p.label] = p.enabled
    const share: Record<string, boolean> = {}
    for (const d of shareableData) share[d.label] = d.shared
    void setMyPrefToggles(perms, share)
  }, 500)
}, { deep: true })

/** 拉取本人 AI 偏好画像填进表单（失败静默，保持空白默认）。 */
async function loadAiProfile() {
  aiLoading.value = true
  try {
    const p = await getMyProfile()
    aiProfile.about = p.about
    aiProfile.style = p.style
    aiProfile.extra = p.extra
    aiProfile.enabled = p.enabled
  } finally {
    aiLoading.value = false
  }
}

/** 保存 AI 偏好画像；成功短暂提示「已保存」。失败抛出（由 UI catch 提示）。 */
async function saveAiProfile() {
  aiSaving.value = true
  try {
    const p = await saveMyProfile({ ...aiProfile })
    aiProfile.about = p.about
    aiProfile.style = p.style
    aiProfile.extra = p.extra
    aiProfile.enabled = p.enabled
    aiSavedTip.value = true
    setTimeout(() => { aiSavedTip.value = false }, 1800)
  } finally {
    aiSaving.value = false
  }
}

export function useUserProfile() {
  refreshIdentity()   // 每次取用时按当前登录者刷新（切账号后拿到的就是新号）
  return {
    user,
    handle,
    status,
    statusMeta,
    setStatus,
    permissions,
    shareableData,
    settingsVisible,
    settingsTab,
    // AI 偏好画像（真实存取）
    aiProfile,
    aiLoading,
    aiSaving,
    aiSavedTip,
    loadAiProfile,
    saveAiProfile,
    // M12：登录/恢复会话完成后由 LiveView 调它，从 account data 回填在线状态——否则 setup 时
    // session 还没就绪(userId 为空)、presence 不回填，刷新后状态点变回"在线"直到打开设置才纠正。
    refreshIdentity,
    openSettings: (tab: UserSettingsTab = 'profile') => {
      refreshIdentity()   // 打开设置时按当前账号刷新身份
      settingsTab.value = tab
      settingsVisible.value = true
      // 打开即拉一次最新画像（无论从哪个 tab 进，进 AI tab 时已有数据）
      loadAiProfile()
    },
    closeSettings: () => { settingsVisible.value = false }
  }
}
