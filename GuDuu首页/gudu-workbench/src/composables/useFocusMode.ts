import { ref } from 'vue'

/** 频道专注模式：隐藏左右侧栏，主区独占视口 */
const focused = ref(false)

export function useFocusMode() {
  return {
    focused,
    enter:  () => { focused.value = true },
    exit:   () => { focused.value = false },
    toggle: () => { focused.value = !focused.value }
  }
}
