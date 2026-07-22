<template>
  <div class="panel">
    <div class="pt">
      <slot name="title">{{ title }}</slot>
      <span v-if="live" class="live">LIVE</span>
    </div>
    <div :style="`height:${height ?? 220}px;position:relative`">
      <canvas ref="canvas" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { ChartConfiguration } from 'chart.js'
import { useChart } from '@/composables/useChart'
import { chartFactories } from '@/data/charts'

const props = defineProps<{
  title?: string
  /** 内置图表 id（从 chartFactories 取）*/
  chartId?: string
  /** 直接传入的图表配置工厂；优先于 chartId */
  config?: (ctx: CanvasRenderingContext2D) => ChartConfiguration
  live?: boolean
  height?: number
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
const { getChart } = useChart(canvas, (ctx) =>
  props.config ? props.config(ctx) : chartFactories[props.chartId!](ctx)
)

/** live 模式：每 2.5s 让实测序列轻微随机游走（虚线基线/目标序列保持不动），数据"活着" */
let liveTimer: number | undefined
onMounted(() => {
  if (!props.live) return
  liveTimer = window.setInterval(() => {
    const chart = getChart()
    if (!chart || (chart.config as { type?: string }).type === 'doughnut') return
    chart.data.datasets.forEach((ds) => {
      if ((ds as { borderDash?: number[] }).borderDash) return
      const data = ds.data as number[]
      for (let i = 0; i < data.length; i++) {
        const v = data[i]
        if (typeof v !== 'number' || v === 0) continue
        data[i] = Math.round(v * (1 + (Math.random() - 0.5) * 0.025) * 100) / 100
      }
    })
    chart.update()
  }, 2500)
})
onBeforeUnmount(() => {
  if (liveTimer) clearInterval(liveTimer)
})
</script>
