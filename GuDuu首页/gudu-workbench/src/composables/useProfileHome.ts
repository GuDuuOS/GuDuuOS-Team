import { ref } from 'vue'

/** 个人主页（创作者主页）全屏页的可见状态 */
const visible = ref(false)

export function useProfileHome() {
  return {
    visible,
    open: () => { visible.value = true },
    close: () => { visible.value = false }
  }
}
