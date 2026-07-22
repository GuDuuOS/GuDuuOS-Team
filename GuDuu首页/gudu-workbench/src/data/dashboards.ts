import type { ChartConfiguration } from 'chart.js'
import type { KpiCardData, UnitStatus } from './kpi'

/* ============ 紧凑图表 builder ============ */

const PALETTE = ['#c96442', '#6b8e4e', '#4a7a8c', '#b58932', '#8a8270']

function hexA(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

function areaFill(ctx: CanvasRenderingContext2D, hex: string) {
  const g = ctx.createLinearGradient(0, 0, 0, 200)
  g.addColorStop(0, hexA(hex, 0.18))
  g.addColorStop(1, hexA(hex, 0))
  return g
}

const axisOpts = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { position: 'top' as const, align: 'end' as const, labels: { boxWidth: 10, padding: 12, font: { size: 11 } } }
  },
  scales: {
    y: { grid: { color: 'rgba(0,0,0,0.04)' } },
    x: { grid: { display: false } }
  }
}

interface LineSeries { label: string; data: number[]; color?: string; fill?: boolean; dash?: number[] }

/** 多序列折线/面积图 */
function lineChart(labels: string[], series: LineSeries[]) {
  return (ctx: CanvasRenderingContext2D): ChartConfiguration => ({
    type: 'line',
    data: {
      labels,
      datasets: series.map((s, i) => {
        const color = s.color ?? PALETTE[i % PALETTE.length]
        const filled = s.fill !== false && !s.dash
        return {
          label: s.label,
          data: s.data,
          borderColor: color,
          backgroundColor: filled ? areaFill(ctx, color) : undefined,
          fill: filled,
          tension: 0.4,
          borderWidth: 2,
          pointRadius: 0,
          borderDash: s.dash
        }
      })
    },
    options: axisOpts
  })
}

/** 单序列柱状图 */
function barChart(labels: string[], data: number[], color = PALETTE[1], label = '') {
  return (): ChartConfiguration => ({
    type: 'bar',
    data: { labels, datasets: [{ label, data, backgroundColor: color, borderRadius: 3, barThickness: 28 }] },
    options: { ...axisOpts, plugins: { legend: { display: false } } }
  })
}

/** 环形图 */
function doughnut(labels: string[], data: number[]) {
  return (): ChartConfiguration => ({
    type: 'doughnut',
    data: { labels, datasets: [{ data, backgroundColor: PALETTE.concat('#b94a4a').slice(0, data.length), borderWidth: 0 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'right', labels: { boxWidth: 8, padding: 8, font: { size: 11 } } } },
      cutout: '62%'
    } as ChartConfiguration['options']
  })
}

/* ============ 数据模型 ============ */

export interface ChartSpec {
  title: string
  live?: boolean
  height?: number
  build: (ctx: CanvasRenderingContext2D) => ChartConfiguration
}

export interface DashboardData {
  /** 频道头标题 */
  title: string
  topic: string
  /** 画布大标题 */
  brand: string
  /** 状态网格标题 */
  unitsTitle: string
  kpis: KpiCardData[]
  units: UnitStatus[]
  prod: ChartSpec
  save: ChartSpec
  pie: ChartSpec
}

const WEEK = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export const dashboardMap: Record<string, DashboardData> = {
  /* ===== 总控中心 ===== */
  hq: {
    title: '总控-全链路驾驶舱',
    topic: '蓝湾渔业全局态势 · 订单 / 货源 / 产能 / 物流 / 预警 一张表看全局',
    brand: '蓝湾渔业 · 全链路智能驾驶舱',
    unitsTitle: '业务环节状态',
    kpis: [
      { label: '今日订单', target: 4000, unit: '斤', delta: '▲ 加急 1 单 · 次日 8:00 达' },
      { label: '可调配货源', target: 4500, unit: '斤', delta: '▲ 冷库+养殖+捕捞 已锁定' },
      { label: '全链路损耗率', target: 12, unit: '‰', delta: '▼ 低于基线 6 个千分点' },
      { label: 'AI 今日协同', target: 86, unit: '次', delta: '▲ 节省 6.5 工时' }
    ],
    units: [
      { name: '养殖基地', status: '出塘就绪' },
      { name: '捕捞船队', status: '已返航' },
      { name: '加工车间', status: '负荷 67%' },
      { name: '质检实验室', status: '抽检中' },
      { name: '冷库',     status: '库容 82%', warn: true },
      { name: '冷链车队', status: '调度中' },
      { name: '电商渠道', status: '运行正常' },
      { name: '海况监测', status: '强对流预警', warn: true }
    ],
    prod: {
      title: '实时产销态势（斤）', live: true,
      build: lineChart(['06', '08', '10', '12', '14', '16', '18', '20', '22'], [
        { label: '入库量', data: [300, 800, 2400, 3100, 3600, 4100, 4400, 4500, 4500] },
        { label: '出货量', data: [0, 200, 600, 1400, 2200, 2900, 3400, 3900, 3952], color: PALETTE[2] }
      ])
    },
    save: { title: '本月降损增效', build: barChart(['W1', 'W2', 'W3', 'W4'], [6.8, 7.2, 7.5, 8.1], PALETTE[1], '降损节省 (万元)') },
    pie: { title: '今日货源结构', height: 180, build: doughnut(['冷库库存', '养殖出塘', '捕捞渔获', '外采补充'], [2000, 1500, 1000, 0]) }
  },

  /* ===== 捕捞船队 ===== */
  fish: {
    title: '捕捞-船队态势',
    topic: '捕捞船队 · 渔船调度 / 渔获上报 / 出海安全',
    brand: '捕捞船队 · 智能调度台',
    unitsTitle: '渔船状态',
    kpis: [
      { label: '今日渔获', target: 3000, unit: '斤', delta: '▲ +12% vs 昨日' },
      { label: '在航渔船', target: 0, unit: '艘', delta: '⚠ 强对流预警 · 全部回港' },
      { label: '海况等级', target: 4, unit: '级', delta: '⚠ 明日 8-9 级大风' },
      { label: '安全作业', target: 218, unit: '天', delta: '▲ 持续保持' }
    ],
    units: [
      { name: '闽蓝 001', status: '回港避风' },
      { name: '闽蓝 003', status: '回港避风' },
      { name: '闽蓝 006', status: '卸货中' },
      { name: '闽蓝 009', status: '设备检修', warn: true },
      { name: '闽蓝 012', status: '已返航' },
      { name: '闽蓝 015', status: '回港避风' }
    ],
    prod: {
      title: '近 7 日渔获趋势（斤）', live: true,
      build: lineChart(WEEK, [
        { label: '渔获量', data: [2680, 2850, 2400, 3100, 2950, 2700, 3000] },
        { label: '计划', data: [2800, 2800, 2800, 3000, 3000, 3000, 3000], color: PALETTE[3], dash: [5, 4] }
      ])
    },
    save: { title: '各渔船今日渔获（斤）', build: barChart(['闽蓝001', '闽蓝003', '闽蓝006', '闽蓝012', '闽蓝015'], [620, 540, 480, 1000, 360], PALETTE[2]) },
    pie: { title: '渔获品类分布', height: 180, build: doughnut(['大黄鱼', '带鱼', '鲳鱼', '梭子蟹', '其他'], [38, 24, 16, 12, 10]) }
  },

  /* ===== 养殖基地 ===== */
  farm: {
    title: '养殖-基地态势',
    topic: '养殖基地 · 苗种管护 / 水质病害监测 / 出塘报备',
    brand: '养殖基地 · 智能管护台',
    unitsTitle: '塘口 / 网箱状态',
    kpis: [
      { label: '成品存塘', target: 5000, unit: '斤', delta: '▼ 今日紧急出塘 1500 斤' },
      { label: '今日出塘', target: 1500, unit: '斤', delta: '▲ 加急订单调拨' },
      { label: '水质达标率', target: 98, unit: '%', delta: '▲ 传感器 36 点位在线' },
      { label: '病害预警', target: 1, unit: '处', delta: '⚠ 4 号塘待复核' }
    ],
    units: [
      { name: '1 号塘', status: '出塘作业' },
      { name: '2 号塘', status: '正常' },
      { name: '3 号塘', status: '正常' },
      { name: '4 号塘', status: '病害复核', warn: true },
      { name: '近海网箱 A', status: '正常' },
      { name: '近海网箱 B', status: '投喂中' }
    ],
    prod: {
      title: '近 7 日水质趋势', live: true,
      build: lineChart(WEEK, [
        { label: '溶氧 (mg/L)', data: [6.8, 6.6, 6.9, 7.1, 6.7, 6.5, 6.8] },
        { label: '水温 (℃)', data: [24.2, 24.6, 25.1, 25.4, 25.8, 26.0, 25.6], color: PALETTE[2] }
      ])
    },
    save: { title: '各塘口成品存量（斤）', build: barChart(['1号塘', '2号塘', '3号塘', '4号塘', '网箱A', '网箱B'], [800, 1200, 950, 600, 750, 700], PALETTE[1]) },
    pie: { title: '在养品种结构', height: 180, build: doughnut(['大黄鱼', '石斑鱼', '鲈鱼', '对虾', '其他'], [42, 21, 17, 12, 8]) }
  },

  /* ===== 加工中心 ===== */
  proc: {
    title: '加工-车间态势',
    topic: '加工中心 · 车间排产 / 生鲜分拣 / 预制菜加工',
    brand: '加工中心 · 智能排产台',
    unitsTitle: '产线状态',
    kpis: [
      { label: '单日产能', target: 6000, unit: '斤', delta: '— 双线满配' },
      { label: '今日排产', target: 4000, unit: '斤', delta: '▲ 加急单优先' },
      { label: '产线合格率', target: 99, unit: '%', delta: '▲ +0.3 pct' },
      { label: '加工损耗率', target: 12, unit: '‰', delta: '▼ 低于基线 6 个千分点' }
    ],
    units: [
      { name: '生鲜分拣线', status: '运行中' },
      { name: '速冻线',   status: '待机' },
      { name: '预制菜线', status: '排产中' },
      { name: '包装线',   status: '运行中' },
      { name: '冷库缓存区', status: '占用 82%', warn: true },
      { name: '留样室',   status: '正常' }
    ],
    prod: {
      title: '今日加工进度（斤）', live: true,
      build: lineChart(['10:00', '10:10', '10:20', '10:30', '10:40', '10:50', '11:00', '11:10'], [
        { label: '完成量', data: [0, 600, 1300, 2100, 2800, 3400, 3800, 3952] },
        { label: '计划', data: [0, 570, 1140, 1710, 2280, 2850, 3420, 4000], color: PALETTE[3], dash: [5, 4] }
      ])
    },
    save: { title: '各产线今日完成（斤）', build: barChart(['分拣线', '包装线', '预制菜线', '速冻线'], [3952, 3952, 860, 0], PALETTE[0]) },
    pie: { title: '产品结构分布', height: 180, build: doughnut(['鲜品', '冻品', '预制菜', '干制品', '其他'], [46, 22, 18, 9, 5]) }
  },

  /* ===== 销售公司 ===== */
  sale: {
    title: '销售-经营态势',
    topic: '销售公司 · 订单 / 行情 / 渠道 / 客户',
    brand: '销售公司 · 智能营销台',
    unitsTitle: '渠道状态',
    kpis: [
      { label: '本月订单', target: 1284, unit: '单', delta: '▲ +7.5% 环比' },
      { label: '今日新增', target: 36, unit: '单', delta: '⚠ 加急 2 单' },
      { label: '订单履约率', target: 99, unit: '%', delta: '▲ +1.2 pct' },
      { label: '行情指数', target: 92, unit: '点', delta: '▼ 批发价走低 · 建议去库存' }
    ],
    units: [
      { name: '电商平台', status: '正常' },
      { name: '商超渠道', status: '活跃' },
      { name: '批发市场', status: '价格走低', warn: true },
      { name: '餐饮直供', status: '正常' },
      { name: '社区团购', status: '推广中' },
      { name: '出口贸易', status: '报关中' }
    ],
    prod: {
      title: '近 7 日销量趋势（斤）', live: true,
      build: lineChart(WEEK, [
        { label: '销量', data: [3620, 3710, 3580, 3840, 3920, 3760, 4000] },
        { label: '目标', data: [3700, 3700, 3700, 3800, 3800, 3800, 3800], color: PALETTE[3], dash: [5, 4] }
      ])
    },
    save: { title: '各渠道今日销量（斤）', build: barChart(['电商', '商超', '批发', '餐饮', '团购'], [1420, 980, 760, 540, 300], PALETTE[0]) },
    pie: { title: '订单来源分布', height: 180, build: doughnut(['电商平台', '商超', '批发', '餐饮直供', '其他'], [38, 24, 18, 14, 6]) }
  }
}

export const fallbackDashboardId = 'hq'

export function getDashboard(id: string): DashboardData {
  return dashboardMap[id] ?? dashboardMap[fallbackDashboardId]
}
