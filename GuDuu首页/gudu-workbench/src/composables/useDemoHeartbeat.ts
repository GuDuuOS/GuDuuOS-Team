import { reactive } from 'vue'
import type { Sender } from '@/types/message'
import { appendToOpsChannel } from '@/composables/useLiveFeed'

/** 右上角通知弹窗 */
export interface DemoToast {
  id: number
  icon: string
  title: string
  body: string
  /** 点击跳转的频道 id（可选；无则为纯提示）*/
  channelId?: string
}

export const toasts = reactive<DemoToast[]>([])

let toastSeq = 0
function pushToast(t: Omit<DemoToast, 'id'>) {
  const toast = { ...t, id: ++toastSeq }
  toasts.push(toast)
  setTimeout(() => dismissToast(toast.id), 10000)
}
export function dismissToast(id: number) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

/** 通用提示（顶栏按钮等使用，无跳转）*/
export function notify(icon: string, title: string, body: string) {
  pushToast({ icon, title, body })
}

/* ===== 心跳事件：演示期间分身持续产生动态，让系统"活着" ===== */

const fishBot:  Sender = { type: 'bot', name: '捕捞分身',     avatar: '捕' }
const farmBot:  Sender = { type: 'bot', name: '养殖分身',     avatar: '养' }
const procBot:  Sender = { type: 'bot', name: '加工分身',     avatar: '加' }
const saleBot:  Sender = { type: 'bot', name: '销售分身',     avatar: '销' }
const whBot:    Sender = { type: 'bot', name: '仓储物流分身', avatar: '仓' }
const qcBot:    Sender = { type: 'bot', name: '质检分身',     avatar: '质' }
const alertBot: Sender = { type: 'bot', name: '运维预警分身', avatar: '警' }

interface HeartbeatEvent {
  /** 距演示开始的毫秒数 */
  at: number
  channelId: string
  sender: Sender
  html: string
  toast: { icon: string; title: string; body: string }
}

const EVENTS: HeartbeatEvent[] = [
  {
    at: 25_000,
    channelId: 'risk-alert',
    sender: alertBot,
    html: '<b>海况例行播报</b>：当前近海风力 4 级、浪高 1.2 m；明日强对流预警维持，6 艘渔船在港状态正常。下次播报 6 小时后。',
    toast: { icon: '🌀', title: '运维预警分身 · 海况播报', body: '近海风力 4 级 · 明日强对流预警维持' }
  },
  {
    at: 60_000,
    channelId: 'proc-line',
    sender: procBot,
    html: '<b>排产确认</b>：预制菜线明日 860 斤排产已自动确认，物料齐套率 100%，08:00 开线。',
    toast: { icon: '🏭', title: '加工分身 · 排产确认', body: '预制菜线明日 860 斤 · 物料齐套 100%' }
  },
  {
    at: 100_000,
    channelId: 'sale-orders',
    sender: saleBot,
    html: '<b>新订单</b>：电商平台新增 12 单（合计 380 斤），已自动确认并纳入明日履约计划；库存联动核减完成。',
    toast: { icon: '🛒', title: '销售分身 · 新订单', body: '电商新增 12 单（380 斤）已自动确认' }
  },
  {
    at: 145_000,
    channelId: 'trace-sync',
    sender: qcBot,
    html: '<b>溯源上链</b>：今日第 29 条记录上链，<code>#WL-0612-09</code> 冷链温控数据流开始写入（每 30 秒采样）。',
    toast: { icon: '🔗', title: '质检分身 · 溯源上链', body: '#WL-0612-09 温控数据开始上链' }
  },
  {
    at: 190_000,
    channelId: 'farm-water',
    sender: farmBot,
    html: '<b>夜间巡航</b>：4 号塘溶氧 6.4 mg/L 稳定，增氧机转间歇模式；36 点位水质监测进入夜间自动巡航。',
    toast: { icon: '💧', title: '养殖分身 · 水质巡航', body: '4 号塘溶氧回稳 6.4 mg/L' }
  },
  {
    at: 240_000,
    channelId: 'order-flow',
    sender: whBot,
    html: '<b>发运就绪</b>：冷链车 闽A·D2371 预冷完成（厢温 2.8℃），加急单 <code>#SO-0612-01</code> 明日 05:30 发车就绪。',
    toast: { icon: '🚚', title: '仓储物流分身 · 发运就绪', body: '冷链车预冷完成 · 明日 05:30 发车' }
  },
  {
    at: 300_000,
    channelId: 'fish-dispatch',
    sender: fishBot,
    html: '<b>船队状态</b>：6 艘渔船缆绳加固复查完成；闽蓝 009 滤芯更换完毕，明日停航期安排试车。',
    toast: { icon: '⚓', title: '捕捞分身 · 船队状态', body: '避风加固复查完成 · 009 待试车' }
  }
]

let started = false

/** 启动演示心跳（应用挂载后调用一次）*/
export function startHeartbeat() {
  if (started) return
  started = true
  EVENTS.forEach((e) => {
    setTimeout(() => {
      appendToOpsChannel(e.channelId, e.sender, e.html)
      pushToast({ ...e.toast, channelId: e.channelId })
    }, e.at)
  })
}
