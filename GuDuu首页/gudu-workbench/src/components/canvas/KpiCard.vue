<template>
  <div class="kpi">
    <div class="lbl">{{ data.label }}</div>
    <div class="val">
      <span>{{ value }}</span>
      <span class="u">{{ data.unit }}</span>
    </div>
    <div class="delta">{{ data.delta }}</div>
  </div>
</template>

<script setup lang="ts">
import type { KpiCardData } from '@/data/kpi'
import { useCountUp } from '@/composables/useCountUp'

const props = defineProps<{ data: KpiCardData; delay?: number }>()
const value = useCountUp(() => props.data.target, 1400, props.delay ?? 300)
</script>
