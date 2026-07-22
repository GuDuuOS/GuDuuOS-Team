<template>
  <div class="channel-view">
    <ChannelHeader
      :title="dataReady ? dash.title : '全链路驾驶舱'"
      :topic="dataReady ? dash.topic : '等待初始化 · 完成搭建后自动点亮'"
      :stack="headerStack"
      :member-count="24"
    />

    <!-- 空态：搭建向导尚未导入数据 -->
    <div v-if="!dataReady" class="dash-empty">
      <div class="dash-empty-ic">
        <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 3v18h18" />
          <path d="M7 16l4-5 3 3 5-7" />
        </svg>
      </div>
      <h3>驾驶舱待初始化</h3>
      <p>跟随右侧 GuDuu 向导完成搭建，导入数据后这里将实时呈现<br/>订单 · 货源 · 产能 · 物流 · 预警 全链路态势。</p>
      <div class="dash-empty-skeleton">
        <span v-for="n in 4" :key="n" class="sk-card" />
      </div>
    </div>

    <div v-else class="canvas">
      <div class="ctitle">{{ dash.brand }}</div>
      <div class="csub">// REAL-TIME OPERATIONAL CANVAS · 由 GuDuu 自动维护</div>

      <div class="kpis">
        <KpiCard
          v-for="(k, i) in dash.kpis"
          :key="activeId + k.label"
          :data="k"
          :delay="200 + i * 80"
          class="clickable"
          @click="detail.openKpi(k, dash)"
        />
      </div>

      <div class="grid-2">
        <PanelChart class="clickable" :key="activeId + 'prod'" :title="dash.prod.title" :config="dash.prod.build" :live="dash.prod.live" @click="detail.openChart(dash.prod, dash)" />
        <PanelChart class="clickable" :key="activeId + 'save'" :title="dash.save.title" :config="dash.save.build" @click="detail.openChart(dash.save, dash)" />
      </div>

      <div class="grid-3">
        <div class="panel" style="grid-column: span 2">
          <div class="pt">{{ dash.unitsTitle }} <span class="md-hint">· 点击查看明细</span></div>
          <UnitGrid :units="dash.units" @select="detail.openUnit($event, dash)" />
        </div>
        <PanelChart class="clickable" :key="activeId + 'pie'" :title="dash.pie.title" :config="dash.pie.build" :height="dash.pie.height ?? 180" @click="detail.openChart(dash.pie, dash)" />
      </div>

      <!-- 成员可调取数据：由「频道管理 · 人员」勾选 -->
      <div v-if="memberData.length" class="panel md-panel">
        <div class="pt">成员可调取数据 <span class="md-hint">· 点击数据项查看明细 · 在「频道管理 · 人员」中勾选</span></div>
        <div class="md-grid">
          <div v-for="m in memberData" :key="m.name" class="md-card">
            <div class="md-head">
              <span class="md-ava" :class="{ bot: m.bot }" :data-avatar="m.avatar" :style="m.color ? `background:${m.color}` : undefined">{{ m.avatar }}</span>
              <span class="md-name">{{ m.name }}</span>
              <span class="md-role">{{ m.role }}</span>
            </div>
            <div class="md-items">
              <div
                v-for="d in m.picked"
                :key="d.label"
                class="md-item clickable"
                :title="`查看「${d.label}」明细`"
                @click="detail.openMemberDatum(d, m, dash)"
              >
                <span class="md-v">{{ d.value }}</span>
                <span class="md-l">{{ d.label }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import ChannelHeader from '@/components/channel/ChannelHeader.vue'
import KpiCard from '@/components/canvas/KpiCard.vue'
import UnitGrid from '@/components/canvas/UnitGrid.vue'
import PanelChart from '@/components/canvas/PanelChart.vue'
import { getDashboard } from '@/data/dashboards'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'
import { useChannelAdmin } from '@/composables/useChannelAdmin'
import { useDashboardDetail } from '@/composables/useDashboardDetail'
import { dataReady } from '@/composables/useSetupWizard'

const { activeId } = useActiveWorkspace()
const dash = computed(() => getDashboard(activeId.value))
const detail = useDashboardDetail()

/** 本群（即本驾驶舱）的成员可调取数据，随群独立 */
const { state: adminState, setCurrent } = useChannelAdmin()
watch(() => dash.value.title, (t) => setCurrent(t), { immediate: true })
const memberData = computed(() =>
  adminState.members
    .map((m) => ({ ...m, picked: m.data.filter((d) => d.selected) }))
    .filter((m) => m.picked.length > 0)
)

const headerStack = [
  { label: 'G', bot: true },
  { label: '警', bot: true },
  { label: '析', bot: true },
  { label: '林', color: '#7a5a3a' },
  { label: '赵', color: '#5a7a8a' }
]
</script>

<style scoped>
.channel-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* 驾驶舱空态 */
.dash-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px;
  color: var(--text-3);
  gap: 6px;
}
.dash-empty-ic {
  width: 84px;
  height: 84px;
  border-radius: 50%;
  background: var(--bg-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  margin-bottom: 10px;
}
.dash-empty h3 {
  font-family: var(--font-heading);
  font-size: var(--fs-300);
  font-weight: var(--fw-bold);
  color: var(--text-2);
  margin: 0;
}
.dash-empty p {
  font-size: var(--fs-100);
  line-height: 1.7;
  max-width: 420px;
  margin: 0;
}
.dash-empty-skeleton {
  display: flex;
  gap: 14px;
  margin-top: 26px;
}
.sk-card {
  width: 120px;
  height: 72px;
  border-radius: 10px;
  background: linear-gradient(100deg, var(--bg-soft) 30%, var(--bg-hover) 50%, var(--bg-soft) 70%);
  background-size: 200% 100%;
  animation: sk-shimmer 1.6s ease-in-out infinite;
}
.sk-card:nth-child(2) { animation-delay: 0.2s; }
.sk-card:nth-child(3) { animation-delay: 0.4s; }
.sk-card:nth-child(4) { animation-delay: 0.6s; }
@keyframes sk-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* 成员关注数据 */
.md-panel { margin-top: 14px; }
.md-hint { font-size: var(--fs-75); color: var(--text-3); font-weight: var(--fw-regular); }
.md-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.md-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--bg-panel);
}
.md-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.md-ava {
  width: 24px; height: 24px;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600;
  flex-shrink: 0;
}
.md-ava.bot {
  background: var(--bot-avatar);
  color: var(--bot-avatar-text);
}
.md-name { font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); }
.md-role {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-3);
}
.md-items { display: flex; flex-wrap: wrap; gap: 10px; }
.md-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 72px;
}
.md-item.clickable {
  cursor: pointer;
  padding: 6px 8px;
  margin: -6px -8px;
  border-radius: 8px;
  transition: background 0.12s ease, box-shadow 0.12s ease;
}
.md-item.clickable:hover {
  background: var(--bg-soft);
  box-shadow: inset 0 0 0 1px var(--border);
}
.md-v {
  font-family: var(--font-heading);
  font-size: var(--fs-300);
  line-height: 1.1;
  font-weight: var(--fw-bold);
  color: var(--text);
}
.md-l { font-size: var(--fs-75); color: var(--text-3); }
</style>
