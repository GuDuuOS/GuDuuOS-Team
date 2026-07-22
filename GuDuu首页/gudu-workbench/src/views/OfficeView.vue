<template>
  <div class="channel-view">
    <ChannelHeader
      title="质检-溯源与报告"
      topic="批次质检 / 全链路溯源 / 报告生成 · 溯源记录已上链 12,840 条"
      :stack="stack"
      :member-count="8"
    />
    <MessageStream :days="days" />
    <Composer channel-label="# 质检-溯源与报告" placeholder="@质检分身 出报告 / 查溯源 / 验批次..." :commands="slashCommands" />
  </div>
</template>

<script setup lang="ts">
import ChannelHeader from '@/components/channel/ChannelHeader.vue'
import MessageStream from '@/components/channel/MessageStream.vue'
import Composer from '@/components/channel/Composer.vue'
import { officeMessages } from '@/data/messages/office'
import { slashCommands } from '@/data/messages/duu'

const days = officeMessages

const stack = [
  { label: '质', bot: true },
  { label: '林', color: '#7a5a3a' }
]
</script>

<style scoped>
.channel-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
</style>
