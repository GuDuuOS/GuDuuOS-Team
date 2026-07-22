<template>
  <div class="msg" :class="msg.sender.type === 'bot' ? 'bot' : 'human'">
    <div class="ava" :data-avatar="msg.sender.avatar" :style="avaStyle">{{ msg.sender.avatar }}</div>
    <div class="body">
      <div class="head">
        <span class="name">{{ msg.sender.name }}</span>
        <span v-if="msg.sender.type === 'bot'" class="role bot">机器人</span>
        <span class="time">{{ msg.time }}</span>
      </div>

      <div v-if="msg.html" class="text" v-html="msg.html" />
      <RichCard    v-if="msg.rich"      :data="msg.rich" :sender="msg.sender" />
      <DocPreview  v-if="msg.doc"       :data="msg.doc"  :sender="msg.sender" />
      <ChartCard
        v-if="msg.chartCard"
        :chart-id="msg.chartCard.chartId"
        :title="msg.chartCard.title"
      />
      <p
        v-if="msg.trailingHtml"
        style="font-size: 12px; color: var(--text-3); margin-top: 8px"
        v-html="msg.trailingHtml"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MessageData } from '@/types/message'
import RichCard from './RichCard.vue'
import DocPreview from './DocPreview.vue'
import ChartCard from './ChartCard.vue'

const props = defineProps<{ msg: MessageData }>()

const avaStyle = computed(() =>
  props.msg.sender.type === 'human' && props.msg.sender.color
    ? `background:${props.msg.sender.color}`
    : undefined
)
</script>
