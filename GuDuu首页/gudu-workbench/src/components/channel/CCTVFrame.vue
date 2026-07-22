<template>
  <div class="cctv">
    <div class="grid" />
    <div class="scan" />
    <div class="ts">{{ liveTs }}</div>
    <div class="cam">{{ data.camera }}</div>
    <div class="rec"><span class="rec-dot" />REC</div>

    <!-- 罐区 + 工人 + 阀门示意 SVG（与原 Demo 一致） -->
    <svg width="100%" height="100%" viewBox="0 0 400 200" style="position: absolute; inset: 0">
      <ellipse cx="80" cy="160" rx="50" ry="8" fill="#3a342a" stroke="#5c5648" />
      <rect x="30" y="60" width="100" height="100" fill="#3a342a" stroke="#5c5648" />
      <ellipse cx="80" cy="60" rx="50" ry="8" fill="#4a4232" stroke="#5c5648" />
      <text x="60" y="115" fill="#8a8270" font-size="10" font-family="monospace">T-07</text>
      <!-- 人 -->
      <circle cx="240" cy="100" r="8" fill="#c98c66" />
      <rect x="232" y="108" width="16" height="34" fill="#5a7a8a" />
      <rect x="232" y="142" width="6" height="22" fill="#2c2a24" />
      <rect x="242" y="142" width="6" height="22" fill="#2c2a24" />
      <!-- 阀门 -->
      <circle cx="340" cy="130" r="12" fill="none" stroke="#5c5648" stroke-width="2" />
      <line x1="328" y1="130" x2="352" y2="130" stroke="#5c5648" stroke-width="2" />
      <line x1="340" y1="118" x2="340" y2="142" stroke="#5c5648" stroke-width="2" />
    </svg>

    <div
      v-for="(b, i) in data.boxes ?? []"
      :key="i"
      class="box"
      :data-l="b.label"
      :style="{ left: b.left, top: b.top, width: b.width, height: b.height }"
    />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { CCTVFrameData } from '@/types/message'

const props = defineProps<{ data: CCTVFrameData }>()

/** 时间码从消息预设时刻起每秒走表，营造"实时录像"感 */
const liveTs = ref(props.data.timestamp)
let timer: number | undefined

function pad(n: number) { return String(n).padStart(2, '0') }

onMounted(() => {
  let base = new Date(props.data.timestamp.replace(' ', 'T'))
  if (isNaN(+base)) return
  timer = window.setInterval(() => {
    base = new Date(+base + 1000)
    liveTs.value =
      `${base.getFullYear()}-${pad(base.getMonth() + 1)}-${pad(base.getDate())} ` +
      `${pad(base.getHours())}:${pad(base.getMinutes())}:${pad(base.getSeconds())}`
  }, 1000)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.rec {
  position: absolute;
  bottom: 8px;
  right: 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #ff8866;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 1px;
}
.rec-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #ff5544;
  animation: rec-blink 1.1s steps(1) infinite;
}
@keyframes rec-blink {
  0%, 60% { opacity: 1; }
  61%, 100% { opacity: 0.15; }
}
</style>
