<template>
  <div class="toast-stack">
    <TransitionGroup name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="{ clickable: t.channelId }" @click="go(t)">
        <span class="toast-ic">{{ t.icon }}</span>
        <div class="toast-body">
          <div class="toast-title">{{ t.title }}</div>
          <div class="toast-text">{{ t.body }}</div>
          <div v-if="t.channelId" class="toast-hint">点击前往频道 →</div>
        </div>
        <button class="toast-close" title="关闭" @click.stop="dismissToast(t.id)">×</button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { toasts, dismissToast, type DemoToast } from '@/composables/useDemoHeartbeat'

const router = useRouter()

function go(t: DemoToast) {
  dismissToast(t.id)
  if (t.channelId) router.push({ name: 'ops', params: { id: t.channelId } })
}

// 心跳由初始化向导在「完成 / 跳过」时启动（useSetupWizard），避免搭建过程中产生干扰事件
</script>

<style scoped>
.toast-stack {
  position: fixed;
  top: 56px;
  right: 16px;
  z-index: 400;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 300px;
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.16), 0 2px 6px rgba(0, 0, 0, 0.08);
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.toast:hover {
  transform: translateY(-1px);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.2), 0 2px 8px rgba(0, 0, 0, 0.1);
}
.toast-ic { font-size: 20px; line-height: 1.2; flex-shrink: 0; }
.toast-body { min-width: 0; flex: 1; }
.toast-title {
  font-size: var(--fs-100);
  font-weight: var(--fw-bold);
  color: var(--text);
  line-height: 1.3;
}
.toast-text {
  font-size: var(--fs-75);
  color: var(--text-2);
  margin-top: 2px;
  line-height: 1.4;
}
.toast-hint {
  font-size: 11px;
  color: var(--accent);
  margin-top: 4px;
}
.toast-close {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  color: var(--text-3);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  border-radius: 6px;
}
.toast-close:hover { background: var(--bg-hover); color: var(--text); }

/* 进出场动画 */
.toast-enter-active { transition: all 0.25s ease; }
.toast-leave-active { transition: all 0.2s ease; }
.toast-enter-from { opacity: 0; transform: translateX(24px); }
.toast-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
