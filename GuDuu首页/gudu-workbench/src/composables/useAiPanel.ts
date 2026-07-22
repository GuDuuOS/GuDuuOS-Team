import { ref } from 'vue'

/** AI 助手侧栏的可见状态 */
const visible = ref(false)
/** dock 模式下：是否展开（720px 浮层） */
const expanded = ref(false)
/** 浮窗模式：完全脱离 dock，居中漂在页面上、可拖拽 */
const floating = ref(false)

export function useAiPanel() {
  return {
    visible,
    expanded,
    floating,
    show:           () => { visible.value = true },
    hide:           () => { visible.value = false; expanded.value = false; floating.value = false },
    toggle:         () => {
      visible.value = !visible.value
      if (!visible.value) { expanded.value = false; floating.value = false }
    },
    toggleExpanded: () => {
      expanded.value = !expanded.value
      if (expanded.value) floating.value = false
    },
    toggleFloating: () => {
      floating.value = !floating.value
      if (floating.value) expanded.value = false
    }
  }
}
