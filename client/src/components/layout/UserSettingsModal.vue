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
            <div class="cam-ava" :style="user.color ? `background:${user.color}` : undefined">{{ user.avatar }}</div>
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
            <select :value="status" class="cam-select" @change="onStatusChange">
              <option v-for="s in statusOptions" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
        </template>

        <!-- AI 偏好（About me / Outputs）：每个用户自己设置，主 AI 对话时注入 -->
        <template v-else-if="settingsTab === 'ai'">
          <div class="cam-help cam-help-top">
            告诉主 AI「你是谁、希望它怎么回答」。只影响你自己的对话，随时可改或关闭。
          </div>
          <div class="cam-field">
            <label class="cam-field-label">关于我</label>
            <textarea
              v-model="aiProfile.about" class="cam-input cam-textarea" rows="3"
              maxlength="2000"
              placeholder="例：我是一名做美食短视频的创作者，主攻小红书和抖音。"
            />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">希望 AI 怎么回答</label>
            <textarea
              v-model="aiProfile.style" class="cam-input cam-textarea" rows="3"
              maxlength="2000"
              placeholder="例：回答简短直接、用中文、多给可执行的步骤，少废话。"
            />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">补充（可选）</label>
            <textarea
              v-model="aiProfile.extra" class="cam-input cam-textarea" rows="2"
              maxlength="2000"
              placeholder="其它想让 AI 记住的偏好。"
            />
          </div>
          <div class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">启用个人偏好</div>
              <div class="cam-row-desc">关掉后 AI 不再参考以上内容（不会删除）</div>
            </div>
            <button class="cam-switch" :class="{ on: aiProfile.enabled }" @click="aiProfile.enabled = !aiProfile.enabled">
              <span class="cam-switch-dot" />
            </button>
          </div>
          <div class="ai-actions">
            <span v-if="aiSavedTip" class="ai-saved">已保存 ✓</span>
            <span v-if="aiErr" class="ai-err">{{ aiErr }}</span>
            <button class="ai-save" :disabled="aiLoading || aiSaving" @click="onSaveAi">
              {{ aiSaving ? '保存中…' : '保存' }}
            </button>
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
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useUserProfile, type UserSettingsTab } from '@/composables/useUserProfile'

const {
  user, handle, status, setStatus, permissions, shareableData, settingsVisible, settingsTab, closeSettings,
  aiProfile, aiLoading, aiSaving, aiSavedTip, saveAiProfile,
} = useUserProfile()

const aiErr = ref('')
async function onSaveAi() {
  aiErr.value = ''
  try {
    await saveAiProfile()
  } catch (e: any) {
    aiErr.value = e?.message || '保存失败'
  }
}

const tabs: { key: UserSettingsTab; label: string }[] = [
  { key: 'profile', label: '资料' },
  { key: 'ai', label: 'AI 偏好' },
  { key: 'perms', label: '我的权限' },
  { key: 'share', label: '可调用数据' }
]
const statusOptions = ['在线', '忙碌', '离开', '隐身']
function onStatusChange(e: Event) {
  setStatus((e.target as HTMLSelectElement).value as any)
}

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
.cam-textarea {
  resize: vertical;
  min-height: 60px;
  line-height: 1.5;
  font-family: inherit;
}
.ai-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}
.ai-actions .ai-save {
  margin-left: auto;
  padding: 7px 18px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}
.ai-actions .ai-save:disabled { opacity: .55; cursor: default; }
.ai-saved { font-size: 12px; color: var(--accent); }
.ai-err { font-size: 12px; color: #e5484d; }
</style>
