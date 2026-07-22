<template>
  <aside class="channels">
    <!-- workspace 名 + 添加 -->
    <div class="cs-ws-head">
      <button class="cs-ws-name" :title="workspaceName">
        <span class="name">{{ workspaceName }}</span>
        <svg class="chev" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      <button class="cs-add" title="添加">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h14M12 5v14" />
        </svg>
      </button>
    </div>

    <!-- 过滤 -->
    <div class="cs-filter">
      <button class="cs-filter-funnel" title="筛选">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 6h18l-7 9v6l-4-2v-4z" />
        </svg>
      </button>
      <input class="cs-filter-input" v-model="filterText" placeholder="查找频道" />
    </div>

    <!-- 列表 -->
    <div class="cs-list">
      <!-- 顶部固定项 -->
      <div class="cs-pinned">
        <div
          v-for="p in pinned"
          :key="p.id"
          class="cs-item pinned-item"
          @click="goTo(p.routeName)"
        >
          <span class="cs-ic">
            <svg v-if="p.icon === 'topic'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z" />
              <path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1" />
            </svg>
            <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 2 11 13" />
              <path d="M22 2 15 22l-4-9-9-4Z" />
            </svg>
          </span>
          <span class="cs-label">{{ p.label }}</span>
          <span v-if="p.badge" class="cs-edit-ic">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
            </svg>
          </span>
          <span v-if="p.badge" class="cs-badge">{{ p.badge }}</span>
        </div>
      </div>

      <!-- 频道 group -->
      <div class="cs-group">
        <button class="cs-group-head" @click="channelsOpen = !channelsOpen">
          <svg class="caret" :class="{ open: channelsOpen }" width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
            <path d="M9 6 15 12 9 18z" />
          </svg>
          <span>频道</span>
        </button>
        <template v-if="channelsOpen">
          <div
            v-for="ch in filteredChannels"
            :key="ch.id"
            class="cs-item ch-row"
            :class="{ active: isActive(ch.routeName, ch.id), 'has-unread': !!localUnread[ch.id], emphasized: ch.emphasized }"
            @click="goToChannel(ch)"
          >
            <span class="cs-ic">
              <!-- 私密 锁 -->
              <svg v-if="ch.visibility === 'private'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect width="18" height="11" x="3" y="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <!-- 公开 地球 -->
              <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="M2 12h20" />
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10" />
              </svg>
            </span>
            <span class="cs-label">{{ ch.label }}</span>
            <span v-if="ch.warn" class="cs-warn">⚠</span>
            <span v-if="localUnread[ch.id]" class="cs-badge">{{ localUnread[ch.id] }}</span>
            <span v-else class="cs-edit-ic show-on-hover">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </span>
          </div>
          <div class="cs-item cs-add-row" @click="$emit('add-channel')">
            <span class="cs-ic-box">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 12h14M12 5v14" />
              </svg>
            </span>
            <span class="cs-label">添加频道</span>
          </div>
        </template>
      </div>

      <!-- 私信 group -->
      <div class="cs-group">
        <button class="cs-group-head" @click="dmsOpen = !dmsOpen">
          <svg class="caret" :class="{ open: dmsOpen }" width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
            <path d="M9 6 15 12 9 18z" />
          </svg>
          <span>私信</span>
        </button>
        <template v-if="dmsOpen">
          <div
            v-for="d in filteredDms"
            :key="d.id"
            class="cs-item dm-row"
            :class="{ active: isActive(d.routeName, d.id) }"
            @click="goToDm(d)"
          >
            <span class="cs-dm-av" :class="{ bot: d.bot }" :data-avatar="d.avatar" :style="d.avatarColor ? `background:${d.avatarColor}` : undefined">
              {{ d.avatar }}
              <span v-if="d.online" class="dot-online" />
            </span>
            <span class="cs-label">{{ d.label }}</span>
            <span v-if="d.unread" class="cs-badge">{{ d.unread }}</span>
          </div>
          <div class="cs-item cs-add-row" @click="$emit('invite')">
            <span class="cs-ic-box">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 12h14M12 5v14" />
              </svg>
            </span>
            <span class="cs-label">邀请成员</span>
          </div>
        </template>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { pinnedItems, workspaceDataMap } from '@/data/channels'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'
import type { ChannelItem, DmItem } from '@/types/channel'

const { activeId: activeWorkspaceId } = useActiveWorkspace()

/** 当前工作区数据响应式追踪 */
const wsData = computed(() => workspaceDataMap[activeWorkspaceId.value] ?? workspaceDataMap['hq'])
const workspaceName = computed(() => wsData.value.name)
const channels      = computed(() => wsData.value.channels)
const dms           = computed(() => wsData.value.dms)

defineEmits<{
  (e: 'add-channel'): void
  (e: 'invite'): void
}>()

const route = useRoute()
const router = useRouter()

const pinned = pinnedItems
const channelsOpen = ref(true)
const dmsOpen = ref(true)
const filterText = ref('')

const localUnread = reactive<Record<string, number>>({})

const filteredChannels = computed(() =>
  channels.value.filter((c) => !filterText.value || c.label.includes(filterText.value))
)

const filteredDms = computed(() =>
  dms.value.filter((d) => !filterText.value || d.label.includes(filterText.value))
)

/** 当前路由是否激活某项；同 routeName 下用 channel id 进一步区分 */
const activeChannelId = ref<string | null>(null)

/** 路由匹配（含 routeParams）*/
const matchByRoute = (it: ChannelItem) => {
  if (it.routeName !== route.name) return false
  if (!it.routeParams) return true
  return Object.entries(it.routeParams).every(
    ([k, v]) => String(route.params[k] ?? '') === v
  )
}

/** 切换 workspace 时重置 active + 重新填充 unread */
watch(
  activeWorkspaceId,
  () => {
    // 重置未读数
    Object.keys(localUnread).forEach((k) => delete localUnread[k])
    channels.value.forEach((c) => { if (c.unread) localUnread[c.id] = c.unread })
    // 重置 active 高亮
    const ch = channels.value.find(matchByRoute)
    const d  = dms.value.find((x) => x.routeName === route.name)
    activeChannelId.value = ch?.id ?? d?.id ?? null
  },
  { immediate: true }
)

/** 运行时未读变化（如主 AI 向频道投递留痕消息）实时同步到角标 */
watch(
  () => channels.value.map((c) => c.unread ?? 0),
  () => {
    channels.value.forEach((c) => {
      if (c.unread) localUnread[c.id] = c.unread
      else delete localUnread[c.id]
    })
  }
)

function isActive(routeName: string, id?: string) {
  if (!id) return route.name === routeName
  return activeChannelId.value === id && route.name === routeName
}

function goTo(routeName: string) {
  activeChannelId.value = null
  if (route.name !== routeName) router.push({ name: routeName })
}
function goToChannel(ch: ChannelItem) {
  ch.unread = 0
  delete localUnread[ch.id]
  activeChannelId.value = ch.id
  router.push({ name: ch.routeName, params: ch.routeParams })
}
function goToDm(d: DmItem) {
  activeChannelId.value = d.id
  if (route.name !== d.routeName) router.push({ name: d.routeName })
}
</script>
