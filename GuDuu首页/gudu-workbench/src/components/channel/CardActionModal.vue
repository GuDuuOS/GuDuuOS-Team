<template>
  <div v-if="visible && payload" class="ca-overlay" @click.self="close">
    <div class="ca-modal" :class="payload.variant" role="dialog" aria-modal="true">
      <div class="ca-head">
        <span class="ca-tag">{{ payload.tag }}</span>
        <div class="ca-title-wrap">
          <span class="ca-title">{{ payload.title }}</span>
          <span v-if="payload.subtitle" class="ca-sub">{{ payload.subtitle }}</span>
        </div>
        <button class="ca-close" title="关闭" @click="close">×</button>
      </div>

      <div class="ca-body">
        <!-- 趋势 -->
        <template v-if="payload.kind === 'trend'">
          <PanelChart v-if="payload.chartConfig" :config="payload.chartConfig" :title="payload.title" :height="220" />
          <ChartCard v-else :chart-id="payload.chartId!" :title="payload.title" />
          <p v-if="payload.chartNote" class="ca-note">{{ payload.chartNote }}</p>
          <div v-if="payload.sections && payload.sections.length" class="ca-doc ca-doc-gap">
            <template v-for="(sec, i) in payload.sections" :key="i">
              <h4>{{ sec.title }}</h4>
              <p v-if="sec.body" v-html="sec.body" />
              <table v-if="sec.table" class="ca-tbl">
                <thead>
                  <tr><th v-for="(h, hi) in sec.table.headers" :key="hi">{{ h }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(row, ri) in sec.table.rows" :key="ri">
                    <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>
        </template>

        <!-- 文档 / 详情 -->
        <template v-else-if="payload.kind === 'doc'">
          <div class="ca-doc">
            <template v-for="(sec, i) in payload.sections" :key="i">
              <h4>{{ sec.title }}</h4>
              <p v-if="sec.body" v-html="sec.body" />
              <table v-if="sec.table" class="ca-tbl">
                <thead>
                  <tr><th v-for="(h, hi) in sec.table.headers" :key="hi">{{ h }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(row, ri) in sec.table.rows" :key="ri">
                    <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
            <div v-if="payload.footer" class="ca-foot">{{ payload.footer }}</div>
          </div>
        </template>

        <!-- 执行结果 -->
        <template v-else>
          <div class="ca-result">
            <div class="ca-check">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
            </div>
            <div class="ca-result-title">{{ payload.resultTitle }}</div>
          </div>
          <ul v-if="payload.steps" class="ca-steps">
            <li v-for="(s, i) in payload.steps" :key="i" :class="{ pending: !s.done }">
              <span class="ca-dot">{{ s.done ? '✓' : '…' }}</span>
              {{ s.text }}
            </li>
          </ul>
        </template>
      </div>

      <div class="ca-actions">
        <button class="btn primary" @click="close">{{ payload.kind === 'confirm' ? '知道了' : '关闭' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useCardAction } from '@/composables/useCardAction'
import ChartCard from './ChartCard.vue'
import PanelChart from '@/components/canvas/PanelChart.vue'

const { visible, payload, close } = useCardAction()

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value) close()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<style scoped>
.ca-overlay {
  position: fixed;
  inset: 0;
  z-index: 220;
  background: rgba(0, 0, 0, 0.34);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: ca-fade 0.14s ease;
}
@keyframes ca-fade { from { opacity: 0 } to { opacity: 1 } }

.ca-modal {
  width: min(560px, 94vw);
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-radius: 14px;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.24), 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  animation: ca-pop 0.16s ease;
}
@keyframes ca-pop { from { opacity: 0; transform: translateY(10px) scale(0.985) } to { opacity: 1; transform: none } }

.ca-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}
.ca-tag {
  flex-shrink: 0;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #fff;
  background: var(--info);
  padding: 3px 8px;
  border-radius: 5px;
}
.ca-modal.alert .ca-tag { background: var(--danger); }
.ca-modal.warn  .ca-tag { background: var(--warn); }
.ca-modal.ok    .ca-tag { background: var(--ok); }
.ca-title-wrap { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.ca-title {
  font-family: var(--serif, var(--font-heading));
  font-weight: 600;
  font-size: 15px;
  color: var(--text);
  line-height: 1.3;
}
.ca-sub { font-size: 12px; color: var(--text-3); font-family: var(--mono); }
.ca-close {
  margin-left: auto;
  width: 28px; height: 28px;
  border: none; background: transparent;
  font-size: 20px; line-height: 1;
  color: var(--text-3); cursor: pointer;
  border-radius: 6px;
  transition: background 0.12s ease, color 0.12s ease;
}
.ca-close:hover { background: var(--bg-hover); color: var(--text); }

.ca-body { padding: 16px 18px; overflow-y: auto; }
.ca-note { font-size: 12.5px; color: var(--text-2); margin-top: 10px; line-height: 1.5; }

/* doc */
.ca-doc-gap { margin-top: 16px; border-top: 1px solid var(--border); padding-top: 12px; }
.ca-doc h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin: 14px 0 6px;
}
.ca-doc h4:first-child { margin-top: 0; }
.ca-doc p { font-size: 13px; color: var(--text-2); line-height: 1.6; margin: 0 0 4px; }
.ca-tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
  margin: 4px 0 2px;
}
.ca-tbl th, .ca-tbl td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
}
.ca-tbl th { color: var(--text-3); font-weight: 600; background: var(--bg-soft); }
.ca-tbl td { color: var(--text); }
.ca-foot { margin-top: 12px; font-family: var(--mono); font-size: 11px; color: var(--text-3); }

/* confirm */
.ca-result { display: flex; align-items: center; gap: 12px; }
.ca-check {
  flex-shrink: 0;
  width: 40px; height: 40px;
  border-radius: 50%;
  background: var(--ok);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  animation: ca-pop 0.22s ease;
}
.ca-result-title { font-size: 15px; font-weight: 600; color: var(--text); }
.ca-steps { list-style: none; margin: 14px 0 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.ca-steps li { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text); }
.ca-steps li.pending { color: var(--text-3); }
.ca-dot {
  flex-shrink: 0;
  width: 18px; height: 18px;
  border-radius: 50%;
  background: var(--ok); color: #fff;
  font-size: 11px;
  display: flex; align-items: center; justify-content: center;
}
.ca-steps li.pending .ca-dot { background: var(--bg-hover); color: var(--text-3); }

.ca-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid var(--border);
}
.ca-actions .btn { cursor: pointer; }
</style>
