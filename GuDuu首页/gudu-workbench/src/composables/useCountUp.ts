import { onMounted, ref, watch } from 'vue'

/** 把数字从 0 缓动到 target，返回 ref 字符串（toLocaleString）。 */
export function useCountUp(target: () => number, duration = 1400, delay = 300) {
  const value = ref('0')

  function animate() {
    const dur = duration
    const t = target()
    const t0 = performance.now()
    const step = (now: number) => {
      const p = Math.min((now - t0) / dur, 1)
      const e = 1 - Math.pow(1 - p, 3)
      value.value = Math.floor(t * e).toLocaleString()
      if (p < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }

  onMounted(() => {
    setTimeout(animate, delay)
  })

  watch(target, () => animate())

  return value
}
