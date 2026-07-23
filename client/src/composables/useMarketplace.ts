import { ref } from 'vue'

/** AI Agent 商城弹窗的可见状态 */
const visible = ref(false)
// 「从哪来回哪去」(负责人报:工坊跳商城后回不去工坊):打开时可带一个返回回调,
// 商城头部据此显示「← 返回」;点返回=关商城+执行回调(如重开工坊)。普通打开无返回钮。
const backCb = ref<null | (() => void)>(null)

export function useMarketplace() {
  return {
    visible,
    hasBack: backCb,
    open: (opts?: { onBack?: () => void }) => {
      backCb.value = opts?.onBack || null
      visible.value = true
    },
    goBack: () => {
      visible.value = false
      const cb = backCb.value
      backCb.value = null
      cb?.()
    },
    close: () => { visible.value = false; backCb.value = null }
  }
}
