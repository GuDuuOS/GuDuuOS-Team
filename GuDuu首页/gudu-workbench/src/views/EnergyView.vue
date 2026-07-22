<template>
  <div class="channel-view">
    <ChannelHeader
      title="销售-行情与产销分析"
      topic="市场行情 · 产销建议 · 本月已降损增收 ¥ 284,000"
      :stack="stack"
      :member-count="12"
    />
    <MessageStream :days="days" />
    <Composer channel-label="# 销售-行情与产销分析" placeholder="@销售分身 帮我..." :commands="slashCommands" />
  </div>
</template>

<script setup lang="ts">
import ChannelHeader from '@/components/channel/ChannelHeader.vue'
import MessageStream from '@/components/channel/MessageStream.vue'
import Composer from '@/components/channel/Composer.vue'
import { energyMessages } from '@/data/messages/energy'
import { slashCommands } from '@/data/messages/duu'

const days = energyMessages

const stack = [
  { label: '销', bot: true },
  { label: '林', color: '#7a5a3a' },
  { label: '周', color: '#8a6a8a' }
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
