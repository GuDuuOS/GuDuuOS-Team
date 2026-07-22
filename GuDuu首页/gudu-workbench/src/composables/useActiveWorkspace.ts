import { ref } from 'vue'

/** 当前激活的工作区（部门）id */
const activeId = ref<string>('hq')

export function useActiveWorkspace() {
  return {
    activeId,
    setActive: (id: string) => { activeId.value = id }
  }
}
