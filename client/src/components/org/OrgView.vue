<!--
  组织/人事页（数据智能演示的"舞台"）。
  自包含：挂载时自己调 getHrEmployees() 拉花名册，渲染 公司概览 + 部门筛选 + 搜索
  + 员工卡片网格 + 点开看详情。遵循 <DocReader /> 那样的"页面级组件"模式，LiveView
  只放一行 <OrgView />。数据仅平台管理员可读（薪资/绩效敏感），拿不到时优雅占位。
-->
<template>
  <div class="org-root">
    <!-- 顶部：公司名 + 概览统计条 -->
    <div class="org-head">
      <div class="org-title">
        <span class="org-emoji">🏢</span>
        <div>
          <div class="org-company">{{ data?.company || '组织 / 人事' }}</div>
          <div class="org-caption">// 员工花名册 · 数据智能演示</div>
        </div>
      </div>
      <button class="org-refresh" title="刷新" @click="load">↻ 刷新</button>
    </div>

    <!-- 加载 / 无权限 / 空 三态 -->
    <div v-if="loading" class="org-hint">正在加载花名册…</div>
    <div v-else-if="!data" class="org-hint">
      读不到人事数据（仅平台管理员可查看，或数据库暂不可用）。
    </div>
    <div v-else-if="!data.employees.length" class="org-hint">
      还没有员工数据（需要先播种/导入花名册）。
    </div>

    <template v-else>
      <!-- 概览 KPI 条 -->
      <div class="org-stats">
        <div class="org-stat"><b>{{ data.summary['在职人数'] ?? 0 }}</b><span>在职</span></div>
        <div class="org-stat"><b>{{ data.summary['试用期人数'] ?? 0 }}</b><span>试用期</span></div>
        <div class="org-stat"><b>{{ data.summary['已离职人数'] ?? 0 }}</b><span>已离职</span></div>
        <div class="org-stat"><b>{{ data.summary['部门数'] ?? 0 }}</b><span>部门</span></div>
        <div class="org-stat"><b>{{ money(data.summary['人均月薪']) }}</b><span>人均月薪</span></div>
        <div class="org-stat"><b>{{ money(data.summary['月薪总额']) }}</b><span>月薪总额</span></div>
      </div>

      <!-- 部门筛选 + 搜索 -->
      <div class="org-controls">
        <div class="org-chips">
          <button class="org-chip" :class="{ active: !dept }" @click="dept = ''">
            全部 <i>{{ data.employees.length }}</i>
          </button>
          <button
            v-for="d in data.departments" :key="d.名称"
            class="org-chip" :class="{ active: dept === d.名称 }"
            @click="dept = d.名称"
          >{{ d.名称 }} <i>{{ d.人数 }}</i></button>
        </div>
        <input v-model="kw" class="org-search" placeholder="搜姓名 / 职位…" />
      </div>

      <!-- 员工卡片网格 -->
      <div class="org-grid">
        <button
          v-for="e in filtered" :key="e.emp_no"
          class="org-card" @click="picked = e"
        >
          <div class="org-av" :class="statusClass(e.status)">{{ e.name.slice(0, 1) }}</div>
          <div class="org-card-name">{{ e.name }}</div>
          <div class="org-card-title">{{ e.title }}</div>
          <div class="org-card-tags">
            <span class="org-tag dept">{{ e.department }}</span>
            <span class="org-tag lvl">{{ e.level }}</span>
            <span v-if="e.perf_rating" class="org-tag perf" :class="'p'+e.perf_rating">{{ e.perf_rating }}</span>
            <span v-if="e.status !== 'active'" class="org-tag st" :class="e.status">{{ statusLabel(e.status) }}</span>
          </div>
        </button>
      </div>
      <p v-if="!filtered.length" class="org-hint">没有匹配的员工。</p>
    </template>

    <!-- 详情抽屉 -->
    <div v-if="picked" class="org-drawer-mask" @click.self="picked = null">
      <div class="org-drawer">
        <div class="org-drawer-head">
          <div class="org-av lg" :class="statusClass(picked.status)">{{ picked.name.slice(0, 1) }}</div>
          <div>
            <div class="org-dname">{{ picked.name }}</div>
            <div class="org-dsub">{{ picked.department }} · {{ picked.title }}（{{ picked.level }}）</div>
          </div>
          <button class="org-x" @click="picked = null">✕</button>
        </div>
        <div class="org-kv"><span>工号</span><b>{{ picked.emp_no }}</b></div>
        <div class="org-kv"><span>在职状态</span><b>{{ statusLabel(picked.status) }}</b></div>
        <div class="org-kv"><span>汇报对象</span><b>{{ picked.manager || '—' }}</b></div>
        <div class="org-kv"><span>入职日期</span><b>{{ picked.hire_date }}</b></div>
        <div class="org-kv" v-if="picked.resign_date"><span>离职日期</span><b>{{ picked.resign_date }}</b></div>
        <div class="org-kv"><span>工作城市</span><b>{{ picked.city }}</b></div>
        <div class="org-kv"><span>月薪</span><b>{{ money(picked.salary) }}</b></div>
        <div class="org-kv"><span>绩效评级</span><b>{{ picked.perf_rating || '—' }}</b></div>
        <div class="org-kv"><span>年假</span><b>{{ picked.annual_leave_used }} / {{ picked.annual_leave_total }} 天</b></div>
        <div class="org-kv"><span>本月请假</span><b>{{ picked.leave_days_month }} 天</b></div>
        <div class="org-kv"><span>本月加班</span><b>{{ picked.overtime_hours_month }} 小时</b></div>
        <div class="org-kv"><span>学历</span><b>{{ picked.education }}</b></div>
        <div class="org-kv"><span>生日</span><b>{{ picked.birth_date }}</b></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getHrEmployees, type Employee, type HrData } from '@/matrix/client'

const loading = ref(true)
const data = ref<HrData | null>(null)
const dept = ref('')        // 当前部门筛选（空=全部）
const kw = ref('')          // 姓名/职位搜索
const picked = ref<Employee | null>(null)  // 详情抽屉当前员工

async function load() {
  loading.value = true
  data.value = await getHrEmployees()
  loading.value = false
}
onMounted(load)

/** 部门 + 关键词过滤后的员工列表。 */
const filtered = computed(() => {
  const list = data.value?.employees || []
  const k = kw.value.trim()
  return list.filter((e) => {
    if (dept.value && e.department !== dept.value) return false
    if (k && !(`${e.name}${e.title}`.includes(k))) return false
    return true
  })
})

/** 月薪/金额格式化：¥30,700。空/0 显示 —。 */
function money(v: any): string {
  const n = Number(v || 0)
  if (!n) return '—'
  return '¥' + n.toLocaleString('zh-CN')
}
function statusLabel(s: string): string {
  return s === 'probation' ? '试用期' : s === 'resigned' ? '已离职' : '在职'
}
function statusClass(s: string): string {
  return s === 'resigned' ? 'off' : s === 'probation' ? 'prob' : ''
}
</script>

<style scoped>
.org-root { padding: 20px 24px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.org-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.org-title { display: flex; align-items: center; gap: 12px; }
.org-emoji { font-size: 30px; }
.org-company { font-size: 20px; font-weight: 700; color: var(--text, #e8e8ea); }
.org-caption { font-size: 12px; color: var(--text-3, #8a8a94); margin-top: 2px; }
.org-refresh { border: 1px solid var(--border, #333); background: transparent; color: var(--text-2, #b8b8c0); padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 13px; }
.org-refresh:hover { border-color: var(--accent, #6366f1); color: var(--accent, #6366f1); }
.org-hint { padding: 40px 20px; text-align: center; color: var(--text-3, #8a8a94); font-size: 13px; }

/* 概览 KPI 条 */
.org-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.org-stat { flex: 1; min-width: 110px; padding: 12px 14px; border: 1px solid var(--border, #2c2c34); border-radius: 12px; background: var(--bg-panel, rgba(255,255,255,.03)); }
.org-stat b { display: block; font-size: 22px; font-weight: 700; color: var(--text, #e8e8ea); line-height: 1.2; }
.org-stat span { font-size: 12px; color: var(--text-3, #8a8a94); }

/* 筛选 + 搜索 */
.org-controls { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.org-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.org-chip { border: 1px solid var(--border, #2c2c34); background: transparent; color: var(--text-2, #b8b8c0); padding: 5px 11px; border-radius: 999px; cursor: pointer; font-size: 12.5px; }
.org-chip i { font-style: normal; opacity: .6; margin-left: 3px; }
.org-chip.active { background: var(--accent, #6366f1); color: #fff; border-color: var(--accent, #6366f1); }
.org-search { border: 1px solid var(--border, #2c2c34); background: var(--bg-panel, rgba(255,255,255,.03)); color: var(--text, #e8e8ea); padding: 7px 12px; border-radius: 9px; font-size: 13px; min-width: 160px; outline: none; }
.org-search:focus { border-color: var(--accent, #6366f1); }

/* 卡片网格 */
.org-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
.org-card { text-align: center; padding: 16px 12px; border: 1px solid var(--border, #2c2c34); border-radius: 14px; background: var(--bg-panel, rgba(255,255,255,.03)); cursor: pointer; transition: transform .1s ease, border-color .1s ease; }
.org-card:hover { transform: translateY(-2px); border-color: var(--accent, #6366f1); }
.org-av { width: 52px; height: 52px; margin: 0 auto 10px; border-radius: 50%; background: var(--accent, #6366f1); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 700; }
.org-av.prob { background: #d97706; }
.org-av.off { background: #6b7280; }
.org-av.lg { width: 60px; height: 60px; font-size: 26px; margin: 0; }
.org-card-name { font-size: 14px; font-weight: 600; color: var(--text, #e8e8ea); }
.org-card-title { font-size: 12px; color: var(--text-3, #8a8a94); margin: 2px 0 8px; }
.org-card-tags { display: flex; flex-wrap: wrap; gap: 4px; justify-content: center; }
.org-tag { font-size: 10.5px; padding: 2px 7px; border-radius: 6px; background: rgba(255,255,255,.06); color: var(--text-2, #b8b8c0); }
.org-tag.dept { background: rgba(99,102,241,.16); color: #a5b4fc; }
.org-tag.perf.pS { background: rgba(234,179,8,.18); color: #fbbf24; }
.org-tag.perf.pA { background: rgba(34,197,94,.16); color: #4ade80; }
.org-tag.perf.pC { background: rgba(239,68,68,.16); color: #f87171; }
.org-tag.st.probation { background: rgba(217,119,6,.18); color: #fbbf24; }
.org-tag.st.resigned { background: rgba(107,114,128,.2); color: #9ca3af; }

/* 详情抽屉 */
.org-drawer-mask { position: fixed; inset: 0; background: rgba(0,0,0,.45); display: flex; justify-content: flex-end; z-index: 50; }
.org-drawer { width: 360px; max-width: 90vw; height: 100%; background: var(--bg, #1a1a1f); border-left: 1px solid var(--border, #2c2c34); padding: 20px; overflow-y: auto; box-sizing: border-box; }
.org-drawer-head { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; position: relative; }
.org-dname { font-size: 18px; font-weight: 700; color: var(--text, #e8e8ea); }
.org-dsub { font-size: 12.5px; color: var(--text-3, #8a8a94); margin-top: 3px; }
.org-x { position: absolute; top: -4px; right: -4px; border: none; background: transparent; color: var(--text-3, #8a8a94); font-size: 16px; cursor: pointer; }
.org-kv { display: flex; justify-content: space-between; padding: 9px 0; border-bottom: 1px solid var(--border, #2c2c34); font-size: 13px; }
.org-kv span { color: var(--text-3, #8a8a94); }
.org-kv b { color: var(--text, #e8e8ea); font-weight: 600; }
</style>
