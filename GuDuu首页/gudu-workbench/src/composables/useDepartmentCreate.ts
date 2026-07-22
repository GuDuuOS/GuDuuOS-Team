import { computed, reactive, ref } from 'vue'
import {
  workspaces,
  workspaceDataMap,
  type DeptLimits
} from '@/data/channels'
import { MODEL_OPTIONS } from '@/composables/useChannelAdmin'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'

/** 部门数量上限——演示「部门也有限制」的一种 */
export const MAX_DEPARTMENTS = 16

export interface DeptDraft {
  label: string
  title: string
  limits: DeptLimits
}

function freshDraft(): DeptDraft {
  return {
    label: '',
    title: '',
    limits: {
      memberCap: 50,
      visibility: '公开',
      ai: {
        enabled: true,
        model: MODEL_OPTIONS[0],
        tokenBudget: 300,
        rateLimit: 60,
        maxLevel: '内部',
        memoryScope: '仅本部门',
        allowControl: false,
        audit: true
      }
    }
  }
}

const visible = ref(false)
const draft = reactive<DeptDraft>(freshDraft())

function reset() {
  const f = freshDraft()
  draft.label = f.label
  draft.title = f.title
  draft.limits = f.limits
}

const atCapacity = computed(() => workspaces.length >= MAX_DEPARTMENTS)

/** 简称：最多取 4 个字符，作为左侧导轨图标文字 */
function normalizeLabel(s: string) {
  return [...s.trim()].slice(0, 4).join('')
}

function genId() {
  let i = workspaces.length + 1
  let id = `dept-${i}`
  const exists = (x: string) => workspaces.some((w) => w.id === x)
  while (exists(id)) id = `dept-${++i}`
  return id
}

export function useDepartmentCreate() {
  const { setActive } = useActiveWorkspace()

  const canCreate = computed(
    () => !atCapacity.value && !!draft.title.trim() && !!normalizeLabel(draft.label || draft.title)
  )

  return {
    visible,
    draft,
    atCapacity,
    deptCount: computed(() => workspaces.length),
    maxDepartments: MAX_DEPARTMENTS,
    canCreate,
    modelOptions: MODEL_OPTIONS,

    open() {
      reset()
      visible.value = true
    },
    close() {
      visible.value = false
    },

    /** 创建部门：写入 workspaces + 空的频道数据，激活并返回 id（失败返回 null）*/
    create(): string | null {
      if (!canCreate.value) return null
      const id = genId()
      const title = draft.title.trim()
      const label = normalizeLabel(draft.label || title)

      workspaces.push({
        id,
        label,
        title,
        // 深拷贝一份限制，避免与下次草稿共享引用
        limits: JSON.parse(JSON.stringify(draft.limits)) as DeptLimits
      })
      workspaceDataMap[id] = { name: title, channels: [], dms: [] }

      setActive(id)
      visible.value = false
      return id
    }
  }
}
