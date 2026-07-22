<template>
  <div class="channel-view">
    <ChannelHeader
      title="待办事宜"
      :topic="`共 ${todoSummary.total} 项 · 待办 ${todoSummary.pending} / 进行中 ${todoSummary.inProgress} / 已完成 ${todoSummary.done}`"
      :stack="headerStack"
      :member-count="14"
      :hash="false"
    />

    <div class="todo-canvas">
      <!-- 汇总卡 -->
      <div class="todo-summary">
        <div class="ts-card">
          <div class="ts-lbl">待办</div>
          <div class="ts-val">{{ todoSummary.pending }}</div>
        </div>
        <div class="ts-card">
          <div class="ts-lbl">进行中</div>
          <div class="ts-val accent">{{ todoSummary.inProgress }}</div>
        </div>
        <div class="ts-card">
          <div class="ts-lbl">已完成</div>
          <div class="ts-val ok">{{ todoSummary.done }}</div>
        </div>
        <div class="ts-card">
          <div class="ts-lbl">逾期</div>
          <div class="ts-val danger">{{ todoSummary.overdue }}</div>
        </div>
      </div>

      <!-- 分组 -->
      <div v-for="g in todoGroups" :key="g.id" class="todo-group">
        <div class="todo-group-head">
          <h3>{{ g.title }}</h3>
          <span v-if="g.meta" class="todo-group-meta">{{ g.meta }}</span>
        </div>

        <div class="todo-list">
          <div
            v-for="t in g.items"
            :key="t.id"
            class="todo-row"
            :class="{ done: t.status === 'done' }"
          >
            <!-- 状态圆圈：点击循环 待办 → 进行中 → 已完成 -->
            <button class="todo-check" :class="t.status" :title="`${statusLabel(t.status)} · 点击切换`" @click="cycleStatus(t)">
              <svg v-if="t.status === 'done'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              <span v-else-if="t.status === 'in_progress'" class="todo-half" />
            </button>

            <!-- 主体 -->
            <div class="todo-main">
              <div class="todo-title">{{ t.title }}</div>
              <div class="todo-meta">
                <span class="todo-tag" :class="`pri-${t.priority}`">{{ priLabel(t.priority) }}</span>
                <span v-if="t.refNo" class="todo-ref">{{ t.refNo }}</span>
                <span v-if="t.sourceLabel" class="todo-src">来源：{{ t.sourceLabel }}</span>
              </div>
            </div>

            <!-- 负责人 / 截止 -->
            <div class="todo-side">
              <div v-if="t.assignee" class="todo-assignee">{{ t.assignee }}</div>
              <div v-if="t.due" class="todo-due">⏱ {{ t.due }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ChannelHeader from '@/components/channel/ChannelHeader.vue'
import { getTodos, initialStatusCounts } from '@/data/todos'
import type { TodoItem, TodoPriority, TodoStatus } from '@/data/todos'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'

const { activeId } = useActiveWorkspace()
const todos = computed(() => getTodos(activeId.value))
const todoGroups = computed(() => todos.value.groups)

/** 汇总随勾选实时联动：在预设基数上叠加状态变化增量；逾期沿用数据预设 */
const todoSummary = computed(() => {
  const items = todos.value.groups.flatMap((g) => g.items)
  const count = (s: TodoStatus) => items.filter((t) => t.status === s).length
  const base = todos.value.summary
  return {
    total: base.total,
    pending: base.pending + count('pending') - initCount(todos.value.groups, 'pending'),
    inProgress: base.inProgress + count('in_progress') - initCount(todos.value.groups, 'in_progress'),
    done: base.done + count('done') - initCount(todos.value.groups, 'done'),
    overdue: base.overdue
  }
})

/** 初始状态计数基准：数据模块加载时已快照（/todo 命令等后续写入都会被计为增量）*/
function initCount(_groups: { items: TodoItem[] }[], s: TodoStatus): number {
  return initialStatusCounts[activeId.value]?.[s] ?? 0
}

/** 点击状态圈：待办 → 进行中 → 已完成 → 待办 */
function cycleStatus(t: TodoItem) {
  t.status = t.status === 'pending' ? 'in_progress' : t.status === 'in_progress' ? 'done' : 'pending'
}

const headerStack = [
  { label: '王', color: '#7a5a3a' },
  { label: '陈', color: '#5a7a8a' },
  { label: '李', color: '#7a8a5a' }
]

function statusLabel(s: TodoStatus) {
  return s === 'done' ? '已完成' : s === 'in_progress' ? '进行中' : '待办'
}
function priLabel(p: TodoPriority) {
  return p === 'high' ? '高' : p === 'mid' ? '中' : '低'
}
</script>

<style scoped>
.channel-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.todo-canvas {
  flex: 1;
  overflow-y: auto;
  padding: 20px var(--content-pad-x) 40px;
}

/* === 汇总卡 === */
.todo-summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}
.ts-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--bg-panel);
}
.ts-lbl {
  font-size: var(--fs-75);
  color: var(--text-3);
  font-family: var(--font-mono);
  letter-spacing: 1px;
  text-transform: uppercase;
}
.ts-val {
  font-family: var(--font-heading);
  font-size: var(--fs-700);
  line-height: 1;
  margin-top: 6px;
  color: var(--text);
}
.ts-val.accent { color: var(--ws-active); }
.ts-val.ok { color: var(--ok); }
.ts-val.danger { color: var(--danger); }

/* === 分组 === */
.todo-group { margin-bottom: 22px; }
.todo-group-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
  padding: 0 4px;
}
.todo-group-head h3 {
  font-family: var(--font-heading);
  font-size: var(--fs-200);
  line-height: var(--lh-200);
  font-weight: var(--fw-bold);
  color: var(--text);
  margin: 0;
}
.todo-group-meta {
  font-size: var(--fs-75);
  color: var(--text-3);
  font-family: var(--font-mono);
}

.todo-list {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-panel);
  overflow: hidden;
}
.todo-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-soft);
  transition: background 0.12s ease;
}
.todo-row:last-child { border-bottom: none; }
.todo-row:hover { background: var(--bg-soft); }
.todo-row.done .todo-title {
  text-decoration: line-through;
  color: var(--text-3);
}

/* status check */
.todo-check {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: transparent;
  border: 2px solid var(--text-dim);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #fff;
  flex-shrink: 0;
  position: relative;
}
.todo-check.in_progress {
  border-color: var(--ws-active);
}
.todo-check .todo-half {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ws-active);
}
.todo-check.done {
  background: var(--ok);
  border-color: var(--ok);
}

/* main column */
.todo-main {
  flex: 1;
  min-width: 0;
}
.todo-title {
  font-size: var(--fs-100);
  line-height: var(--lh-100);
  font-weight: var(--fw-bold);
  color: var(--text);
}
.todo-meta {
  display: flex;
  gap: 10px;
  margin-top: 4px;
  font-size: var(--fs-75);
  color: var(--text-3);
  align-items: center;
  flex-wrap: wrap;
}

.todo-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 9px;
  letter-spacing: 0.5px;
}
.todo-tag.pri-high { background: #fee2e2; color: var(--danger); }
.todo-tag.pri-mid  { background: #fef3c7; color: var(--warn); }
.todo-tag.pri-low  { background: var(--bg-code); color: var(--text-3); }

.todo-ref {
  font-family: var(--font-mono);
  color: var(--ws-active);
}
.todo-src { color: var(--text-3); }

/* side column */
.todo-side {
  text-align: right;
  font-size: var(--fs-75);
  color: var(--text-3);
  white-space: nowrap;
  flex-shrink: 0;
}
.todo-assignee {
  font-weight: var(--fw-bold);
  color: var(--text-2);
  font-size: var(--fs-100);
  line-height: 1.4;
}
.todo-due {
  font-family: var(--font-mono);
  margin-top: 2px;
}
</style>
