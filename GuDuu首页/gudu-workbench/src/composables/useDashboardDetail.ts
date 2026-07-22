import type { ChartConfiguration } from 'chart.js'
import type { KpiCardData, UnitStatus } from '@/data/kpi'
import type { DashboardData, ChartSpec } from '@/data/dashboards'
import { useCardAction, type CardActionPayload } from '@/composables/useCardAction'

/* ---------- 小工具 ---------- */

const ACCENT = '#c96442'

function fmt(n: number) {
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function hexA(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

type Dir = 'up' | 'down' | 'flat'
function dirOf(delta: string): Dir {
  if (delta.includes('▲')) return 'up'
  if (delta.includes('▼')) return 'down'
  return 'flat'
}

/** 围绕目标值合成最近 7 个点的历史序列 */
function synthSeries(target: number, dir: Dir): number[] {
  const span = Math.max(Math.abs(target) * 0.08, 1)
  const pts: number[] = []
  for (let i = 6; i >= 0; i--) {
    let base: number
    if (dir === 'up') base = target - (span * i) / 6
    else if (dir === 'down') base = target + (span * i) / 6
    else base = target + Math.sin(i) * span * 0.12
    const noise = Math.sin(i * 1.7) * span * 0.05
    const v = base + noise
    pts.push(Math.round(v * 100) / 100)
  }
  pts[pts.length - 1] = target // 末点对齐当前值
  return pts
}

const LABELS_7 = ['T-6', 'T-5', 'T-4', 'T-3', 'T-2', 'T-1', '现在']

/** 单序列面积折线图配置工厂 */
function lineConfig(label: string, data: number[], color = ACCENT) {
  return (ctx: CanvasRenderingContext2D): ChartConfiguration => {
    const g = ctx.createLinearGradient(0, 0, 0, 200)
    g.addColorStop(0, hexA(color, 0.18))
    g.addColorStop(1, hexA(color, 0))
    return {
      type: 'line',
      data: {
        labels: LABELS_7,
        datasets: [
          {
            label,
            data,
            borderColor: color,
            backgroundColor: g,
            fill: true,
            tension: 0.4,
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: color
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { grid: { color: 'rgba(0,0,0,0.04)' } }, x: { grid: { display: false } } }
      }
    }
  }
}

/* ---------- 明细构建 ---------- */

function buildKpi(kpi: KpiCardData, dash: DashboardData): CardActionPayload {
  const dir = dirOf(kpi.delta)
  const series = synthSeries(kpi.target, dir)
  const peak = Math.max(...series)
  const low = Math.min(...series)
  const avg = series.reduce((a, b) => a + b, 0) / series.length
  return {
    kind: 'trend',
    tag: 'KPI 明细',
    title: kpi.label,
    subtitle: dash.brand,
    variant: 'info',
    chartConfig: lineConfig(kpi.label, series),
    chartNote: `当前 ${fmt(kpi.target)} ${kpi.unit} · ${kpi.delta}`,
    sections: [
      {
        title: '数据明细',
        table: {
          headers: ['维度', '数值'],
          rows: [
            ['当前值', `${fmt(kpi.target)} ${kpi.unit}`],
            ['变化', kpi.delta.replace(/^[▲▼]\s*/, '')],
            ['近 7 期峰值', `${fmt(peak)} ${kpi.unit}`],
            ['近 7 期最低', `${fmt(low)} ${kpi.unit}`],
            ['近 7 期均值', `${fmt(Math.round(avg * 100) / 100)} ${kpi.unit}`],
            ['数据来源', 'CRM / BI 实时汇总 · 自动核对']
          ]
        }
      }
    ],
    footer: '// 演示数据 · 点击数据块查看明细'
  }
}

/** 从「负荷 96%」「库容 64%」这类状态里抓出百分数 */
function pctOf(status: string): number | null {
  const m = status.match(/(\d+(?:\.\d+)?)\s*%/)
  return m ? Number(m[1]) : null
}

function buildUnit(unit: UnitStatus, dash: DashboardData): CardActionPayload {
  const pct = pctOf(unit.status)
  const rows: string[][] = [
    ['当前状态', unit.status],
    ['运行判定', unit.warn ? '异常 / 预警 ⚠' : '正常']
  ]
  if (pct !== null) {
    rows.push(['负荷 / 占用', `${pct}%`])
    rows.push(['安全区间', unit.warn ? '已逼近上限' : '60–95%（正常）'])
  }
  rows.push(['连续运行', `${120 + (unit.name.length * 17) % 240} 天`])
  rows.push(['最近检查', '今日 08:30 · 合格'])
  rows.push(['当前负责人', '值班负责人'])

  const sections: CardActionPayload['sections'] = [
    { title: '运行参数', table: { headers: ['项', '值'], rows } }
  ]
  if (unit.warn) {
    sections.unshift({
      title: '状态提示',
      body: '⚠ 该模块 / 指标处于异常或预警状态，已自动通知相关团队关注并跟踪处置。'
    })
  }

  return {
    kind: 'doc',
    tag: unit.warn ? '模块预警' : '模块详情',
    title: unit.name,
    subtitle: `${dash.brand} · ${dash.unitsTitle}`,
    variant: unit.warn ? 'warn' : 'ok',
    sections,
    footer: '// 演示数据 · 来自数据平台 / 在线监测'
  }
}

/** 从「1,247」「98%」「75 万元」里抓出数字 */
function parseNum(v: string): number | null {
  const m = v.replace(/,/g, '').match(/-?\d+(?:\.\d+)?/)
  return m ? Number(m[0]) : null
}

function buildMemberDatum(
  d: { label: string; value: string },
  member: { name: string; role: string },
  dash: DashboardData
): CardActionPayload {
  const num = parseNum(d.value)
  const table = {
    title: '数据明细',
    table: {
      headers: ['维度', '值'],
      rows: [
        ['数据项', d.label],
        ['当前值', d.value],
        ['提供 / 负责', `${member.name}（${member.role}）`],
        ['可见范围', `${dash.brand} 可调取`],
        ['数据来源', 'CRM / BI / 业务系统 实时同步']
      ]
    }
  }
  const base = {
    tag: '成员数据',
    title: d.label,
    subtitle: `${member.name} · ${member.role}`,
    variant: 'info' as const,
    footer: '// 演示数据 · 成员可调取项'
  }
  if (num !== null) {
    return {
      ...base,
      kind: 'trend',
      chartConfig: lineConfig(d.label, synthSeries(num, 'flat')),
      chartNote: `当前 ${d.value} · 由 ${member.name} 提供`,
      sections: [table]
    }
  }
  return {
    ...base,
    kind: 'doc',
    sections: [
      { title: '状态说明', body: `当前为「${d.value}」，由 ${member.name} 提供，对本部门大脑可见可调取。` },
      table
    ]
  }
}

function buildChart(spec: ChartSpec, dash: DashboardData): CardActionPayload {
  return {
    kind: 'trend',
    tag: '图表',
    title: spec.title,
    subtitle: dash.brand,
    variant: 'info',
    chartConfig: spec.build,
    chartNote: '放大查看 · 数据由 GuDuu 实时汇总'
  }
}

export function useDashboardDetail() {
  const { open } = useCardAction()
  return {
    openKpi: (kpi: KpiCardData, dash: DashboardData) => open(buildKpi(kpi, dash)),
    openUnit: (unit: UnitStatus, dash: DashboardData) => open(buildUnit(unit, dash)),
    openChart: (spec: ChartSpec, dash: DashboardData) => open(buildChart(spec, dash)),
    openMemberDatum: (
      d: { label: string; value: string },
      member: { name: string; role: string },
      dash: DashboardData
    ) => open(buildMemberDatum(d, member, dash))
  }
}
