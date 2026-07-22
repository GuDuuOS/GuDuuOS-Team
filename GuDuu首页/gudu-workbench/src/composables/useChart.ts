import { onBeforeUnmount, onMounted, type Ref } from 'vue'
import {
  Chart,
  LineController, BarController, DoughnutController,
  CategoryScale, LinearScale,
  PointElement, LineElement, BarElement, ArcElement,
  Tooltip, Legend, Filler,
  type ChartConfiguration
} from 'chart.js'

let registered = false
function ensureRegistered() {
  if (registered) return
  Chart.register(
    LineController, BarController, DoughnutController,
    CategoryScale, LinearScale,
    PointElement, LineElement, BarElement, ArcElement,
    Tooltip, Legend, Filler
  )
  Chart.defaults.color = '#4b5563'
  Chart.defaults.font.family = '-apple-system,"PingFang SC",sans-serif'
  Chart.defaults.borderColor = 'rgba(0,0,0,0.06)'
  registered = true
}

/** 在 canvas ref 上挂一个 Chart 实例，组件卸载时自动 destroy。返回实例 getter 供 live 刷新等使用。 */
export function useChart(
  canvasRef: Ref<HTMLCanvasElement | null>,
  buildConfig: (ctx: CanvasRenderingContext2D) => ChartConfiguration
) {
  let chart: Chart | null = null

  onMounted(() => {
    ensureRegistered()
    const el = canvasRef.value
    if (!el) return
    const ctx = el.getContext('2d')
    if (!ctx) return
    chart = new Chart(ctx, buildConfig(ctx))
  })

  onBeforeUnmount(() => {
    chart?.destroy()
    chart = null
  })

  return { getChart: () => chart }
}
