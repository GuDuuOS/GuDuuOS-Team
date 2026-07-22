<template>
  <div ref="root" class="um-wrap">
    <button class="user-chip" :class="{ open }" :title="user.name" aria-label="用户菜单" @click="open = !open">
      <span class="avatar" :data-avatar="user.avatar">{{ user.avatar }}</span>
      <span class="online-dot" />
    </button>

    <div v-if="open" class="um-pop" @click.stop>
      <!-- 个人信息头 -->
      <div class="um-head">
        <span class="um-ava" :data-avatar="user.avatar" :style="user.color ? `background:${user.color}` : undefined">{{ user.avatar }}</span>
        <div class="um-id">
          <div class="um-name">{{ user.name }} <span class="um-role">{{ user.role }}</span></div>
          <div class="um-handle">{{ handle }} · <span class="um-online">在线</span></div>
        </div>
      </div>

      <div class="um-sep" />

      <!-- 传统项 -->
      <button class="um-item" @click="go('profile')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
        <span>个人资料</span>
      </button>
      <button class="um-item" @click="go('perms')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
        <span>我的权限</span>
      </button>
      <button class="um-item" @click="go('share')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></svg>
        <span>数据调用授权</span>
      </button>
      <button class="um-item" @click="close">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>
        <span>通知偏好</span>
      </button>

      <div class="um-sep" />

      <button class="um-item danger" @click="close">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5" /><path d="M21 12H9" /></svg>
        <span>退出登录</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useUserProfile, type UserSettingsTab } from '@/composables/useUserProfile'

const { user, handle, openSettings } = useUserProfile()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
function close() { open.value = false }
/** 打开个人设置到指定标签，并关闭下拉 */
function go(tab: UserSettingsTab) { openSettings(tab); open.value = false }

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
.um-wrap { position: relative; display: inline-flex; }

.um-pop {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 60;
  width: 320px;
  max-height: calc(100vh - 70px);
  overflow-y: auto;
  padding: 8px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.14), 0 1px 3px rgba(0, 0, 0, 0.08);
  animation: um-in 0.12s ease;
}
@keyframes um-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }

.um-head { display: flex; align-items: center; gap: 10px; padding: 8px 8px 10px; }
.um-ava {
  width: 38px; height: 38px;
  border-radius: 9px;
  background: var(--accent);
  color: #fff;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 15px; font-weight: 600;
  flex-shrink: 0;
}
.um-id { min-width: 0; }
.um-name { font-size: var(--fs-200); font-weight: var(--fw-bold); color: var(--text); display: flex; align-items: center; gap: 6px; }
.um-role {
  font-family: var(--mono); font-size: 10px;
  color: var(--accent); background: var(--accent-soft);
  padding: 1px 6px; border-radius: 9px;
}
.um-handle { font-size: var(--fs-75); color: var(--text-3); margin-top: 2px; }
.um-online { color: var(--ok); }

.um-sep { height: 1px; background: var(--border-soft); margin: 6px 4px; }

.um-sec-h {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--mono);
  letter-spacing: 0.5px;
  padding: 2px 8px 6px;
}

.um-toggle-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: background 0.1s ease;
}
.um-toggle-row:hover { background: var(--bg-soft); }
.um-tr-main { flex: 1; min-width: 0; }
.um-tr-label { font-size: var(--fs-100); color: var(--text); }
.um-tr-desc { font-size: var(--fs-75); color: var(--text-3); margin-top: 1px; }

.um-switch {
  width: 36px; height: 20px;
  border-radius: 999px;
  background: var(--border);
  position: relative;
  flex-shrink: 0;
  transition: background 0.15s ease;
}
.um-switch.on { background: var(--accent); }
.um-switch-dot {
  position: absolute; top: 2px; left: 2px;
  width: 16px; height: 16px;
  border-radius: 50%; background: #fff;
  transition: transform 0.15s ease;
}
.um-switch.on .um-switch-dot { transform: translateX(16px); }

.um-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  font-size: var(--fs-100);
  color: var(--text-2);
  transition: background 0.1s ease, color 0.1s ease;
}
.um-item svg { color: var(--text-3); flex-shrink: 0; }
.um-item:hover { background: var(--bg-soft); color: var(--text); }
.um-item:hover svg { color: var(--text-2); }
.um-item.danger { color: var(--danger); }
.um-item.danger svg { color: var(--danger); }
.um-item.danger:hover { background: #fee2e2; }
</style>
