<template>
  <div class="rich" :class="data.variant">
    <div class="r-head">
      <span class="tag">{{ data.tag }}</span>
      <span class="t">{{ data.title }}</span>
      <span v-if="data.meta" class="r-meta">{{ data.meta }}</span>
    </div>

    <p v-if="data.paragraph" v-html="data.paragraph" />

    <div v-if="data.kv && data.kv.length" class="kv">
      <template v-for="(kv, i) in data.kv" :key="i">
        <div class="k">{{ kv.k }}</div>
        <div class="v">{{ kv.v }}</div>
      </template>
    </div>

    <CCTVFrame v-if="data.cctv" :data="data.cctv" />

    <!-- 终态：已处理（批准/驳回后按钮收起，防重复操作）-->
    <div v-if="data.handled" class="rich-handled">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
      已处理 · {{ data.handled }}
    </div>
    <div v-else-if="data.actions && data.actions.length" class="actions">
      <button
        v-for="(a, i) in data.actions"
        :key="i"
        class="btn"
        :class="{ primary: a.primary }"
        @click="onAction(a.label)"
      >
        {{ a.label }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { RichCardData, Sender } from '@/types/message'
import CCTVFrame from './CCTVFrame.vue'
import { useCardAction } from '@/composables/useCardAction'

const props = defineProps<{ data: RichCardData; sender?: Sender }>()
const { runAction } = useCardAction()

function onAction(label: string) {
  runAction(label, {
    tag: props.data.tag,
    title: props.data.title,
    meta: props.data.meta,
    variant: props.data.variant,
    kv: props.data.kv,
    sender: props.sender,
    raw: props.data
  })
}
</script>

<style scoped>
.rich-handled {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(107, 142, 78, 0.12);
  color: var(--ok);
  font-size: var(--fs-75);
  font-weight: var(--fw-bold);
}
</style>
