<template>
  <div class="chart-card">
    <div class="ct">{{ title }}</div>
    <div class="cw">
      <canvas ref="canvas" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useChart } from '@/composables/useChart'
import { chartFactories } from '@/data/charts'

const props = defineProps<{
  title: string
  chartId: string
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
const factory = chartFactories[props.chartId]
if (!factory) {
  console.warn(`[ChartCard] unknown chartId: ${props.chartId}`)
}
useChart(canvas, (ctx) => factory(ctx))
</script>
