<template>
  <div class="plugin-rail">
    <div class="pr-list">
      <div
        v-for="p in plugins"
        :key="p.id"
        class="pr-icon"
        :class="{ active: activeId === p.id, 'has-image': !!p.image, 'has-color': !p.image && !!p.color }"
        :style="!p.image && p.color ? { background: p.color, color: '#fff' } : undefined"
        :title="p.title"
        @click="toggle(p.id)"
      >
        <img v-if="p.image" :src="p.image" :alt="p.title" class="pr-img" />
        <span v-else>{{ p.label }}</span>
      </div>

      <!-- 新增插件：紧跟在机器人下方 → 打开插件商城 -->
      <div class="pr-icon plus" title="添加插件" @click="openPluginStore">+</div>
    </div>

    <div class="pr-divider" />

    <div class="pr-icon gear" title="资产管理" @click="openAssetManagement">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <ellipse cx="12" cy="5" rx="8" ry="3" />
        <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
        <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
      </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { usePlugins } from '@/composables/usePlugins'
import { useAiPanel } from '@/composables/useAiPanel'
import { usePluginStore } from '@/composables/usePluginStore'

const { plugins } = usePlugins()
const { visible: aiVisible, toggle: toggleAi, show: showAi } = useAiPanel()
const { open: openPluginStore } = usePluginStore()
const router = useRouter()

/** 当前激活的插件 id：AI 打开时为 'ai'，否则为 null */
const activeId = computed(() => (aiVisible.value ? 'ai' : null))

function toggle(id: string) {
  // 内置 AI：切换助手面板；其它已获取的插件：打开助手面板（代表使用该插件）
  if (id === 'ai') toggleAi()
  else showAi()
}

function openAssetManagement() {
  router.push({ name: 'data-canvas', query: { section: 'modeling' } })
}
</script>
