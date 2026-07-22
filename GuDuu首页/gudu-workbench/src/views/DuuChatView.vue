<template>
  <div class="channel-view">
    <div class="ch-header">
      <button class="ch-fav" :class="{ active: fav }" @click="fav = !fav" :title="fav ? '取消收藏' : '收藏'">
        <svg width="16" height="16" viewBox="0 0 24 24" :fill="fav ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
        </svg>
      </button>
      <ChannelTitleMenu title="GuDuu">
        <div
          class="a bot"
          data-avatar="G"
          style="width:22px;height:22px;border-radius:5px;background:var(--text);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;margin-right:4px"
        >
          G
        </div>
        GuDuu
        <span class="bot-badge">机器人</span>
      </ChannelTitleMenu>
      <div class="topic">你的 AI 同事 · 可以问我任何事</div>
      <div class="ch-actions">
        <button
          class="ch-ic-btn"
          :class="{ active: rightPanelVisible }"
          :title="rightPanelVisible ? '关闭关于此频道' : '打开关于此频道'"
          @click="toggle"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4M12 8h.01" />
          </svg>
        </button>
      </div>
    </div>

    <MessageStream :days="days" />
    <Composer
      channel-label="→ 与 GuDuu 私聊"
      placeholder="试试输入 / 调出命令，或自然语言提问..."
      :commands="slashCommands"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import MessageStream from '@/components/channel/MessageStream.vue'
import Composer from '@/components/channel/Composer.vue'
import ChannelTitleMenu from '@/components/channel/ChannelTitleMenu.vue'
import { duuMessages, slashCommands } from '@/data/messages/duu'
import { useRightPanel } from '@/composables/useRightPanel'
import { useChannelAdmin } from '@/composables/useChannelAdmin'

const days = duuMessages
const fav = ref(false)
const { visible: rightPanelVisible, toggle } = useRightPanel()
useChannelAdmin().setCurrent('GuDuu')
</script>

<style scoped>
.channel-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
</style>
