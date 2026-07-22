import { reactive, ref } from 'vue'
import { currentUser } from '@/data/channels'

/** 我的权限（可开关）*/
export interface UserPermission { label: string; desc?: string; enabled: boolean }
/** 可被他人 / AI 调用的我的数据 */
export interface ShareableDatum { label: string; value: string; shared: boolean }

const handle = '@lin_mgr'

/** 个人设置弹窗 */
export type UserSettingsTab = 'profile' | 'perms' | 'share'
const settingsVisible = ref(false)
const settingsTab = ref<UserSettingsTab>('profile')
const status = ref<'在线' | '忙碌' | '离开' | '隐身'>('在线')

const permissions = reactive<UserPermission[]>([
  { label: '审批单 / 重要事项许可', desc: '高风险事项终审', enabled: true },
  { label: '下发任务 / 流程指令',   desc: '排期调整、流程触发', enabled: true },
  { label: '跨部门数据查看',        desc: '产品 / 运营 / 财务汇总', enabled: true },
  { label: '授权 AI 代我起草与汇总', desc: '日报、文档初稿', enabled: true },
  { label: 'AI 高风险动作需我确认',  desc: '控制类动作人工把关', enabled: true }
])

const shareableData = reactive<ShareableDatum[]>([
  { label: '我的待办与审批状态', value: '6 项待批', shared: true },
  { label: '我负责业务的实时 KPI', value: '业务 / 成本', shared: true },
  { label: '我的日程 / 在岗状态', value: '在岗', shared: false },
  { label: '我的审批意见记录', value: '近 30 天', shared: false }
])

export function useUserProfile() {
  return {
    user: currentUser,
    handle,
    status,
    permissions,
    shareableData,
    settingsVisible,
    settingsTab,
    openSettings: (tab: UserSettingsTab = 'profile') => { settingsTab.value = tab; settingsVisible.value = true },
    closeSettings: () => { settingsVisible.value = false }
  }
}
