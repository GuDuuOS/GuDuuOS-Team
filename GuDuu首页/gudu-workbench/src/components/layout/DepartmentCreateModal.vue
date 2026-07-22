<template>
  <div v-if="visible" class="cam-overlay" @click.self="close">
    <div class="cam-modal dept-modal" role="dialog" aria-modal="true">
      <div class="cam-head">
        <span class="cam-title">新建部门</span>
        <span class="cam-sub">部门级 AI 隔离 · 数据密级与配额限制</span>
        <button class="cam-close" title="关闭" @click="close">×</button>
      </div>

      <div class="cam-body">
        <!-- 容量限制提示 -->
        <div class="dept-cap" :class="{ full: atCapacity }">
          <span>已建部门 <b>{{ deptCount }}</b> / 上限 {{ maxDepartments }}</span>
          <span v-if="atCapacity" class="dept-cap-warn">已达上限，无法再新建部门</span>
        </div>

        <!-- 基本信息 -->
        <div class="dept-sec">基本信息</div>
        <div class="cam-field">
          <label class="cam-field-label">部门全称</label>
          <input v-model="draft.title" class="cam-input" placeholder="如 数字化运营部" maxlength="20" />
        </div>
        <div class="cam-field">
          <label class="cam-field-label">部门简称（左侧导轨显示）</label>
          <div class="dept-label-row">
            <input v-model="draft.label" class="cam-input" placeholder="如 数智（最多 4 字）" maxlength="4" />
            <span class="dept-prev" :title="'导轨图标预览'">{{ previewLabel || '？' }}</span>
          </div>
          <div class="cam-help">留空将自动取全称前两个字。</div>
        </div>
        <div class="cam-field">
          <label class="cam-field-label">默认频道可见性</label>
          <select v-model="draft.limits.visibility" class="cam-select">
            <option value="公开">公开（部门内可见）</option>
            <option value="受邀">受邀（仅受邀成员）</option>
          </select>
        </div>
        <div class="cam-field">
          <label class="cam-field-label">成员上限</label>
          <input v-model.number="draft.limits.memberCap" type="number" min="1" class="cam-input" />
        </div>

        <!-- AI 限制 -->
        <div class="dept-sec">
          AI 限制
          <button class="cam-switch" :class="{ on: draft.limits.ai.enabled }" @click="draft.limits.ai.enabled = !draft.limits.ai.enabled">
            <span class="cam-switch-dot" />
          </button>
        </div>
        <div class="cam-help cam-help-top">
          关闭后，本部门不挂载任何 AI；开启后按下列额度与密级隔离运行，互不串数据。
        </div>

        <template v-if="draft.limits.ai.enabled">
          <div class="cam-field">
            <label class="cam-field-label">模型</label>
            <select v-model="draft.limits.ai.model" class="cam-select">
              <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
          <div class="cam-field">
            <label class="cam-field-label">月度 Token 预算（万）</label>
            <input v-model.number="draft.limits.ai.tokenBudget" type="number" min="0" class="cam-input" />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">速率限制（次 / 分）</label>
            <input v-model.number="draft.limits.ai.rateLimit" type="number" min="0" class="cam-input" />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">AI 可访问最高数据密级</label>
            <select v-model="draft.limits.ai.maxLevel" class="cam-select">
              <option value="公开">公开</option>
              <option value="内部">内部</option>
              <option value="机密">机密</option>
            </select>
            <div class="cam-help">高于此密级的系统数据，本部门 AI 一律不可读取。</div>
          </div>
          <div class="cam-field">
            <label class="cam-field-label">上下文 / 记忆范围</label>
            <select v-model="draft.limits.ai.memoryScope" class="cam-select">
              <option value="仅本部门">仅本部门（隔离）</option>
              <option value="全公司">全公司（共享）</option>
            </select>
          </div>
          <div class="cam-field cam-field-row">
            <label class="cam-field-label">允许 AI 执行控制类动作</label>
            <button class="cam-switch" :class="{ on: draft.limits.ai.allowControl }" @click="draft.limits.ai.allowControl = !draft.limits.ai.allowControl">
              <span class="cam-switch-dot" />
            </button>
          </div>
          <div v-if="draft.limits.ai.allowControl" class="cam-help dept-danger">
            ⚠ 高风险：开启后该部门 AI 可下发控制 / 调度类指令，建议仍保留人工确认。
          </div>
          <div class="cam-field cam-field-row">
            <label class="cam-field-label">审计日志</label>
            <button class="cam-switch" :class="{ on: draft.limits.ai.audit }" @click="draft.limits.ai.audit = !draft.limits.ai.audit">
              <span class="cam-switch-dot" />
            </button>
          </div>
        </template>
      </div>

      <div class="dept-foot">
        <button class="dept-btn ghost" @click="close">取消</button>
        <button class="dept-btn primary" :disabled="!canCreate" @click="onCreate">创建部门</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDepartmentCreate } from '@/composables/useDepartmentCreate'

const {
  visible, draft, atCapacity, deptCount, maxDepartments, canCreate, modelOptions,
  close, create
} = useDepartmentCreate()

const router = useRouter()

const previewLabel = computed(() => {
  const src = (draft.label || draft.title).trim()
  return [...src].slice(0, 4).join('')
})

async function onCreate() {
  const id = create()
  if (id) await router.push({ name: 'dashboard' })
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value) close()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<style scoped>
.dept-modal { height: auto; max-height: calc(100vh - 64px); }

.dept-cap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: var(--fs-75);
  color: var(--text-3);
  background: var(--bg-soft);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 16px;
}
.dept-cap b { color: var(--text); font-family: var(--font-heading); }
.dept-cap.full { background: #fee2e2; color: var(--danger); }
.dept-cap-warn { color: var(--danger); font-weight: var(--fw-bold); }

.dept-sec {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-heading);
  font-weight: var(--fw-bold);
  font-size: var(--fs-100);
  color: var(--text);
  margin: 18px 0 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.dept-sec:first-of-type { margin-top: 4px; }
.dept-sec .cam-switch { margin-left: auto; }

.dept-label-row { display: flex; align-items: center; gap: 10px; }
.dept-prev {
  flex-shrink: 0;
  width: 40px; height: 40px;
  border-radius: 10px;
  background: var(--accent);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-family: var(--font-heading);
  font-weight: var(--fw-bold);
  font-size: 13px;
  letter-spacing: -0.5px;
}

.dept-danger { color: var(--danger); }

.dept-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 18px;
  border-top: 1px solid var(--border);
}
.dept-btn {
  height: 36px;
  padding: 0 18px;
  border-radius: 8px;
  font-size: var(--fs-100);
  font-weight: var(--fw-bold);
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--bg-panel);
  color: var(--text);
  transition: background 0.12s ease, filter 0.12s ease, opacity 0.12s ease;
}
.dept-btn.ghost:hover { background: var(--bg-hover); }
.dept-btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.dept-btn.primary:hover { filter: brightness(1.05); }
.dept-btn.primary:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
