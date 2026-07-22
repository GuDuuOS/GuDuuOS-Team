import { onBeforeUnmount, onMounted, ref } from 'vue'

const pad = (n: number) => String(n).padStart(2, '0')

/** 顶栏走秒时钟，HH:MM:SS。 */
export function useClock() {
  const time = ref('--:--:--')
  let timer: number | null = null

  const tick = () => {
    const d = new Date()
    time.value = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  }

  onMounted(() => {
    tick()
    timer = window.setInterval(tick, 1000)
  })
  onBeforeUnmount(() => {
    if (timer !== null) window.clearInterval(timer)
  })

  return { time }
}
