<template>
  <div v-if="settingsVisible" class="cam-overlay" @click.self="closeSettings">
    <div class="cam-modal" role="dialog" aria-modal="true">
      <div class="cam-head">
        <span class="cam-title">个人设置</span>
        <span class="cam-sub">{{ user.name }} · {{ handle }}</span>
        <button class="cam-close" title="关闭" @click="closeSettings">×</button>
      </div>

      <div class="cam-tabs">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="cam-tab"
          :class="{ active: settingsTab === t.key }"
          @click="settingsTab = t.key"
        >{{ t.label }}</button>
      </div>

      <div class="cam-body">
        <!-- 资料 -->
        <template v-if="settingsTab === 'profile'">
          <div class="cam-row">
            <div class="cam-ava" :data-avatar="user.avatar" :style="user.color ? `background:${user.color}` : undefined">{{ user.avatar }}</div>
            <div class="cam-row-main">
              <div class="cam-row-label">{{ user.name }} <span class="us-role">{{ user.role }}</span></div>
              <div class="cam-row-desc">{{ handle }}</div>
            </div>
          </div>
          <div class="cam-field">
            <label class="cam-field-label">显示名称</label>
            <input v-model="user.name" class="cam-input" />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">账号</label>
            <input :value="handle" class="cam-input" disabled />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">在线状态</label>
            <select v-model="status" class="cam-select">
              <option v-for="s in statusOptions" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
        </template>

        <!-- 我的权限 -->
        <template v-else-if="settingsTab === 'perms'">
          <div class="cam-help cam-help-top">控制你在系统中可执行的操作与授权范围。</div>
          <div v-for="p in permissions" :key="p.label" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">{{ p.label }}</div>
              <div v-if="p.desc" class="cam-row-desc">{{ p.desc }}</div>
            </div>
            <button class="cam-switch" :class="{ on: p.enabled }" @click="p.enabled = !p.enabled">
              <span class="cam-switch-dot" />
            </button>
          </div>
        </template>

        <!-- 可调用数据 -->
        <template v-else>
          <div class="cam-help cam-help-top">设置哪些个人数据可被他人或 AI 调用。</div>
          <div v-for="d in shareableData" :key="d.label" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">{{ d.label }}</div>
              <div class="cam-row-desc">{{ d.value }}</div>
            </div>
            <button class="cam-switch" :class="{ on: d.shared }" @click="d.shared = !d.shared">
              <span class="cam-switch-dot" />
            </button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useUserProfile, type UserSettingsTab } from '@/composables/useUserProfile'

const { user, handle, status, permissions, shareableData, settingsVisible, settingsTab, closeSettings } = useUserProfile()

const tabs: { key: UserSettingsTab; label: string }[] = [
  { key: 'profile', label: '资料' },
  { key: 'perms', label: '我的权限' },
  { key: 'share', label: '可调用数据' }
]
const statusOptions = ['在线', '忙碌', '离开', '隐身']

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && settingsVisible.value) closeSettings()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<style scoped>
.us-role {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--accent);
  background: var(--accent-soft);
  padding: 1px 6px;
  border-radius: 9px;
  margin-left: 6px;
}
.cam-row .cam-switch { margin-left: auto; }
</style>
