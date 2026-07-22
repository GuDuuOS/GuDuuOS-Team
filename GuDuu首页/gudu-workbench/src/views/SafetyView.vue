<template>
  <div class="channel-view">
    <ChannelHeader
      title="预警-风险监测中心"
      topic="天气海况 · 渔船设备 · 水质病害 · 冷链温控 实时监测预警"
      :stack="stack"
      :member-count="18"
    />
    <MessageStream :days="days" />
    <Composer
      channel-label="# 预警-风险监测中心"
      placeholder="发消息到 #预警-风险监测中心，或输入 / 调用 AI 命令..."
      enable-emoji
      :commands="slashCommands"
    />
  </div>
</template>

<script setup lang="ts">
import ChannelHeader from '@/components/channel/ChannelHeader.vue'
import MessageStream from '@/components/channel/MessageStream.vue'
import Composer from '@/components/channel/Composer.vue'
import { safetyMessages } from '@/data/messages/safety'
import { slashCommands } from '@/data/messages/duu'

const days = safetyMessages

const stack = [
  { label: '警', bot: true },
  { label: '赵', color: '#5a7a8a' },
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
