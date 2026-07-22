<template>
  <div class="ch-header">
    <!-- 左侧：★ 收藏 + 频道身份 -->
    <button class="ch-fav" :class="{ active: fav }" :title="fav ? '取消收藏' : '收藏'" @click="fav = !fav">
      <svg width="16" height="16" viewBox="0 0 24 24" :fill="fav ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
      </svg>
    </button>
    <ChannelTitleMenu :title="title">
      <template v-if="hash !== false"><span class="hash">#</span></template>
      <slot name="title">{{ title }}</slot>
    </ChannelTitleMenu>
    <div v-if="topic" class="topic">{{ topic }}</div>

    <!-- 右侧：成员堆叠 + icon 按钮 -->
    <div class="ch-actions">
      <button class="ch-members-btn" title="管理成员 · 技能 · 知识库 · 规则" @click="openAdmin(title)">
        <div class="ava-stack">
          <div
            v-for="(av, i) in stack"
            :key="i"
            class="a"
            :class="{ bot: av.bot }"
            :data-avatar="av.label"
            :style="av.color ? `background:${av.color}` : undefined"
          >
            {{ av.label }}
          </div>
        </div>
        <span class="ch-members-count">{{ memberCount }}</span>
      </button>

      <button
        class="ch-ic-btn"
        :class="{ active: focused }"
        :title="focused ? '退出专注' : '专注模式'"
        @click="toggleFocus"
      >
        <!-- focused 态：四角合并图标，跟 AI 浮窗按钮对齐 -->
        <svg v-if="focused" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 7V3h4M21 7V3h-4M3 17v4h4M21 17v4h-4" />
        </svg>
        <!-- 默认：windowed grid（跟 AI 浮窗按钮同款）-->
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect width="18" height="18" x="3" y="3" rx="2" />
          <path d="M12 3v18M3 12h18" />
        </svg>
      </button>
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
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import ChannelTitleMenu from '@/components/channel/ChannelTitleMenu.vue'
import { useRightPanel } from '@/composables/useRightPanel'
import { useFocusMode } from '@/composables/useFocusMode'
import { useChannelAdmin } from '@/composables/useChannelAdmin'

interface StackAvatar {
  label: string
  bot?: boolean
  color?: string
}

const props = defineProps<{
  title: string
  topic?: string
  stack: StackAvatar[]
  memberCount: number
  hash?: boolean
}>()

const fav = ref(false)
const { visible: rightPanelVisible, toggle } = useRightPanel()
const { open: openAdmin, setCurrent } = useChannelAdmin()

/** 当前频道即"当前群"：管理弹窗 / 右栏 / 大脑都据此读取该群配置 */
watch(() => props.title, (t) => setCurrent(t), { immediate: true })
const { focused, toggle: toggleFocus } = useFocusMode()
</script>
