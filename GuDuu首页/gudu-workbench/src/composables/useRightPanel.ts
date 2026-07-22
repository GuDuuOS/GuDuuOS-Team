import { ref } from 'vue'

/** 右侧"关于此频道"面板的可见状态，模块级单例，跨组件共享。 */
const visible = ref(true)

export function useRightPanel() {
  return {
    visible,
    show:   () => { visible.value = true },
    hide:   () => { visible.value = false },
    toggle: () => { visible.value = !visible.value }
  }
}
