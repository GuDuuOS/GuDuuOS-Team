import { ref } from 'vue'

/** 顶部搜索 / 命令面板（⌘K）的可见状态 */
const visible = ref(false)

export function useCommandPalette() {
  return {
    visible,
    open: () => { visible.value = true },
    close: () => { visible.value = false }
  }
}
