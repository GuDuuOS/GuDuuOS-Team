<template>
  <div class="channel-view">
    <ChannelHeader
      :title="effectiveMeta.title"
      :topic="effectiveMeta.topic"
      :stack="effectiveMeta.stack"
      :member-count="effectiveMeta.memberCount"
    />
    <div v-if="scenario" class="replay-bar">
      <button class="replay-btn" :class="{ playing: replaying }" :disabled="replaying" @click="replay">
        <span v-if="!replaying">▶ 重播演示</span>
        <span v-else>● 播放中 {{ replayIdx }}/{{ replayTotal }}…</span>
      </button>
    </div>
    <MessageStream v-if="scenario" :days="scenario.days" />
    <div v-else class="ops-placeholder">
      <div class="ops-placeholder-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z" />
          <path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1" />
        </svg>
      </div>
      <h3>{{ effectiveMeta.title }}</h3>
      <p>{{ effectiveMeta.topic }}</p>
      <p class="ops-placeholder-hint">这个频道还没有消息记录。发条消息开个头，或邀请同事加入吧。</p>
    </div>
    <Composer
      :channel-label="`# ${effectiveMeta.title}`"
      :placeholder="`发送到 #${effectiveMeta.title}，或输入 / 调用 AI 命令...`"
      enable-emoji
      :commands="slashCommands"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ChannelHeader from '@/components/channel/ChannelHeader.vue'
import MessageStream from '@/components/channel/MessageStream.vue'
import Composer from '@/components/channel/Composer.vue'
import { opsScenarios } from '@/data/messages/ops'
import { slashCommands } from '@/data/messages/duu'
import { workspaceDataMap } from '@/data/channels'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'
import { scrollFeedToBottom } from '@/composables/useLiveFeed'

const route = useRoute()
const { activeId } = useActiveWorkspace()
const channelId = computed(() => String(route.params.id ?? ''))
const scenario  = computed(() => opsScenarios[channelId.value])

/* ===== 剧本重播：清空后按节奏逐条上屏（配合讲解）===== */
const replaying = ref(false)
const replayIdx = ref(0)
const replayTotal = ref(0)
let replayTimers: number[] = []
let pendingDay: { messages: unknown[] } | null = null
let pendingRest: unknown[] = []

/** 终止播放；restore 时把未播完的消息一次性补回，保证剧本不丢 */
function stopReplay(restore = true) {
  replayTimers.forEach(clearTimeout)
  replayTimers = []
  if (restore && pendingDay && pendingRest.length) pendingDay.messages.push(...pendingRest)
  pendingDay = null
  pendingRest = []
  replaying.value = false
}

function replay() {
  const sc = scenario.value
  if (!sc || replaying.value) return
  const day = sc.days[sc.days.length - 1]
  const all = [...day.messages]
  if (!all.length) return
  day.messages.splice(0)
  pendingDay = day
  pendingRest = [...all]
  replaying.value = true
  replayIdx.value = 0
  replayTotal.value = all.length
  all.forEach((m, i) => {
    replayTimers.push(
      window.setTimeout(() => {
        day.messages.push(m)
        pendingRest.shift()
        replayIdx.value = i + 1
        scrollFeedToBottom()
        if (i === all.length - 1) stopReplay(false)
      }, 500 + i * 1800)
    )
  })
}

/** 切频道时终止播放并补回剩余消息 */
watch(channelId, () => {
  if (replaying.value) stopReplay()
})
onBeforeUnmount(() => stopReplay())

/** 没有剧本时，从 workspaceDataMap 兜底凑出标题/topic */
const fallbackMeta = computed(() => {
  const ws = workspaceDataMap[activeId.value]
  const ch = ws?.channels.find((c) => c.id === channelId.value)
  return {
    title: ch?.label ?? channelId.value,
    topic: `${ws?.name ?? ''} · 频道占位`,
    memberCount: 8,
    stack: [
      { label: ws?.name?.[0] ?? '?', color: '#5a7a8a' }
    ]
  }
})

const effectiveMeta = computed(() => scenario.value?.meta ?? fallbackMeta.value)
</script>

<style scoped>
.channel-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.replay-bar {
  display: flex;
  justify-content: flex-end;
  padding: 6px var(--content-pad-x, 20px) 0;
}
.replay-btn {
  border: 1px solid var(--border);
  background: var(--bg-panel);
  color: var(--text-2);
  font-size: var(--fs-75);
  padding: 4px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}
.replay-btn:hover:not(:disabled) { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
.replay-btn.playing { color: var(--accent); border-color: var(--accent); cursor: default; }
.ops-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px;
  color: var(--text-3);
  gap: 8px;
}
.ops-placeholder-icon {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: var(--bg-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  margin-bottom: 8px;
}
.ops-placeholder h3 {
  font-family: var(--font-heading);
  font-size: var(--fs-300);
  font-weight: var(--fw-bold);
  color: var(--text);
  margin: 0;
}
.ops-placeholder p {
  font-size: var(--fs-100);
  max-width: 360px;
  margin: 0;
}
.ops-placeholder-hint {
  color: var(--text-dim);
  font-size: var(--fs-75);
  margin-top: 12px !important;
}
</style>
