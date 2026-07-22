import { ref } from 'vue'

/** AI Agent 商城弹窗的可见状态 */
const visible = ref(false)

export function useMarketplace() {
  return {
    visible,
    open: () => { visible.value = true },
    close: () => { visible.value = false }
  }
}
