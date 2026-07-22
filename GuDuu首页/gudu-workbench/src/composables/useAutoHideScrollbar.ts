/**
 * 全局自动隐藏滚动条：
 *   - 默认：body 没有 .is-scrolling 类，CSS 让滚动条 thumb 完全透明
 *   - 用户滚动时：加上 .is-scrolling，CSS 让 thumb 显形
 *   - 停止滚动 1.2s 后：移除 .is-scrolling，thumb 消失
 *
 * 监听 capture 阶段，覆盖所有嵌套滚动容器（频道流、画布、右栏列表 …）。
 */
export function setupAutoHideScrollbar() {
  let timer: number | null = null
  const HIDE_DELAY = 1200

  const onScroll = () => {
    document.body.classList.add('is-scrolling')
    if (timer !== null) window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      document.body.classList.remove('is-scrolling')
      timer = null
    }, HIDE_DELAY)
  }

  // capture 阶段 + passive 表示不阻塞滚动，性能更好
  window.addEventListener('scroll', onScroll, { capture: true, passive: true })
  // wheel 事件也算"滚动意图"，确保滚轮一动就立刻显形
  window.addEventListener('wheel', onScroll, { capture: true, passive: true })
}
