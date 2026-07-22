<template>
  <div ref="root" class="ch-title-menu">
    <button class="ch-title-trigger" :class="{ open }" @click="open = !open">
      <slot />
      <svg class="chev" :class="{ open }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    <div v-if="open" class="ctm-pop" @click.stop>
      <button class="ctm-item" @click="act('newwin')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" /><path d="M4 16V6a2 2 0 0 1 2-2h10" /></svg>
        <span>在新窗口打开</span>
      </button>

      <div class="ctm-sep" />

      <button class="ctm-item" @click="act('detail')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" /></svg>
        <span>频道详情</span>
      </button>
      <button class="ctm-item" @click="act('mute')">
        <svg v-if="!muted" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.268 21a2 2 0 0 0 3.464 0" /><path d="m2 2 20 20" /><path d="M6.3 6.3A8 8 0 0 0 4 12c0 1.2-.4 2.7-1 4h13" /><path d="M9 3.5A8 8 0 0 1 18 8c0 1.7.3 3.2.8 4.5" /></svg>
        <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>
        <span>{{ muted ? '取消静音' : '静音频道' }}</span>
      </button>
      <button class="ctm-item" @click="act('notify')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>
        <span>通知偏好</span>
      </button>
      <button class="ctm-item" @click="act('settings')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></svg>
        <span>频道设定</span>
      </button>

      <div class="ctm-sep" />

      <button class="ctm-item" @click="act('members')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></svg>
        <span>成员</span>
      </button>

      <div class="ctm-sep" />

      <button class="ctm-item" @click="act('move')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" /></svg>
        <span>移动至…</span>
        <svg class="ctm-chev-r" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
      </button>

      <div class="ctm-sep" />

      <button class="ctm-item danger" @click="act('leave')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5" /><path d="M21 12H9" /></svg>
        <span>离开频道</span>
      </button>
      <button class="ctm-item danger" @click="act('archive')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="5" x="2" y="3" rx="1" /><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" /><path d="M10 12h4" /></svg>
        <span>归档频道</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRightPanel } from '@/composables/useRightPanel'
import { useChannelAdmin } from '@/composables/useChannelAdmin'

const props = defineProps<{ title?: string }>()

const open = ref(false)
const muted = ref(false)
const root = ref<HTMLElement | null>(null)
const { show: showRightPanel } = useRightPanel()
const { open: openAdmin } = useChannelAdmin()

type MenuAction = 'newwin' | 'detail' | 'mute' | 'notify' | 'settings' | 'members' | 'move' | 'leave' | 'archive'

function act(key: MenuAction) {
  switch (key) {
    case 'newwin':
      window.open(location.href, '_blank')
      break
    case 'detail':
      showRightPanel()
      break
    case 'settings':
    case 'members':
      // 频道设定 / 成员 → 打开「频道管理」（成员·技能·知识库·数据权限等）
      openAdmin(props.title)
      break
    case 'mute':
      muted.value = !muted.value
      return // 保持菜单打开，便于看到状态切换
  }
  open.value = false
}

function onDocClick(e: MouseEvent) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
.ch-title-menu {
  position: relative;
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.ch-title-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 3px 6px;
  margin-left: -6px;
  border-radius: 6px;
  font-family: var(--font-heading);
  font-size: var(--fs-200);
  line-height: var(--lh-200);
  font-weight: var(--fw-bold);
  color: var(--text);
  transition: background 0.12s ease;
}
.ch-title-trigger:hover,
.ch-title-trigger.open {
  background: var(--bg-hover);
}
.ch-title-trigger .chev {
  color: var(--text-3);
  transition: transform 0.15s ease;
}
.ch-title-trigger .chev.open {
  transform: rotate(180deg);
}

.ctm-pop {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 50;
  min-width: 232px;
  padding: 6px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12), 0 1px 3px rgba(0, 0, 0, 0.08);
  animation: ctm-in 0.12s ease;
}
@keyframes ctm-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

.ctm-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  font-family: var(--font-body);
  font-size: var(--fs-100);
  font-weight: var(--fw-regular);
  color: var(--text-2);
  transition: background 0.1s ease, color 0.1s ease;
}
.ctm-item svg { flex-shrink: 0; color: var(--text-3); }
.ctm-item span { flex: 1; }
.ctm-item:hover { background: var(--bg-soft); color: var(--text); }
.ctm-item:hover svg { color: var(--text-2); }

.ctm-item .ctm-chev-r { color: var(--text-3); }

.ctm-item.danger { color: var(--danger); }
.ctm-item.danger svg { color: var(--danger); }
.ctm-item.danger:hover { background: #fee2e2; color: var(--danger); }
.ctm-item.danger:hover svg { color: var(--danger); }

.ctm-sep {
  height: 1px;
  background: var(--border-soft);
  margin: 6px 4px;
}
</style>
