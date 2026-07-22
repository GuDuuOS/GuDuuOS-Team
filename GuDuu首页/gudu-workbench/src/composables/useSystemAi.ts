import { reactive, ref } from 'vue'
import type { ChannelInfoItem } from '@/data/channels'
import {
  MODEL_OPTIONS,
  type Confidential,
  type AccessLevel,
  type DataScope,
  type ChannelPersona,
  type ChannelModel,
  type ChannelMemory
} from '@/composables/useChannelAdmin'

export { MODEL_OPTIONS }
export type { Confidential, AccessLevel }

/** 系统 AI 设置弹窗的可见状态 */
const visible = ref(false)

/**
 * 主 AI（GuDuu 总控）的全局配置——区别于按频道的隔离配置。
 * 总控 AI 统筹各部门「子智能体」、对接全公司系统、拥有更高额度与全局记忆。
 */
const state = reactive({
  persona: {
    aiName: 'GuDuu 总控分身',
    tone: '统筹 · 稳健 · 可追溯',
    prompt: '你是蓝湾渔业的总控管理分身，依托 A2A 协议统筹调度捕捞、养殖、加工、销售、仓储物流、质检、运维预警各岗位分身，汇聚全链路数据；货源冲突自动协商，无法达成一致或涉及停产、紧急调货、出海审批等高风险动作时，必须上报负责人人工裁定。'
  } as ChannelPersona,

  skills: [
    { label: '全链路数据汇总', tag: '/brief', desc: '汇聚各环节分身结果，生成全局驾驶舱视图' },
    { label: '订单复盘报告', tag: '/report', desc: '货源 / 加工 / 损耗 / 物流时效一体化复盘' },
    { label: '货源智能调度', tag: '/dispatch', desc: '库存 → 养殖 → 捕捞 优先级联动匹配' },
    { label: '批次溯源检索', tag: '/trace', desc: '跨海域 / 塘口 / 车间 / 冷链的统一追溯' },
    { label: '风险联动预警', tag: '/alert', desc: '天气海况 / 病害 / 设备多源预警聚合路由' }
  ] as ChannelInfoItem[],

  knowledge: [
    { label: '渔业制度与作业规范', desc: '出海 / 养殖 / 加工 SOP · 860 篇' },
    { label: '水产品质量标准', desc: 'GB / 行业标准 · 实时同步' },
    { label: '历史产销行情数据', desc: '近 5 年 · 价格 / 产量 / 损耗' },
    { label: '海域与渔船档案', desc: '6 艘渔船 · 12 处塘口 / 网箱' }
  ] as ChannelInfoItem[],

  /** 总控分身统筹的岗位分身 */
  subAgents: [
    { label: '捕捞分身', desc: '捕捞船队 · 在线' },
    { label: '养殖分身', desc: '养殖基地 · 在线' },
    { label: '加工分身', desc: '加工中心 · 在线' },
    { label: '销售分身', desc: '销售公司 · 在线' },
    { label: '仓储物流分身', desc: '冷库 / 冷链 · 在线' },
    { label: '质检分身', desc: '质检实验室 · 在线' },
    { label: '运维预警分身', desc: '天气 / 海况 / 设备 · 在线' }
  ] as ChannelInfoItem[],

  /** 全公司系统接入（总控可达更多系统，财务仍受密级约束）*/
  dataSources: [
    { label: '渔船定位 / AIS', level: '内部', access: '读写' },
    { label: '水质传感物联网', level: '内部', access: '只读' },
    { label: 'MES 加工执行', level: '内部', access: '读写' },
    { label: '冷链温控平台', level: '内部', access: '读写' },
    { label: '溯源存证平台', level: '内部', access: '读写' },
    { label: '电商订单平台', level: '内部', access: '读写' },
    { label: '气象 / 海况接口', level: '公开', access: '只读' },
    { label: 'ERP 经营核算', level: '机密', access: '只读' }
  ] as DataScope[],

  model: { model: 'GuDuu-Pro', tokenBudget: 5000, rateLimit: 600 } as ChannelModel,

  memory: { longTerm: true, scope: '全公司', retentionDays: 365, audit: true } as ChannelMemory
})

export function useSystemAi() {
  return {
    visible,
    state,
    open: () => { visible.value = true },
    close: () => { visible.value = false },

    addItem(kind: 'skills' | 'knowledge' | 'subAgents', label: string, desc: string, tag?: string) {
      const l = label.trim()
      if (!l) return
      const item: ChannelInfoItem = { label: l }
      if (desc.trim()) item.desc = desc.trim()
      if (tag && tag.trim()) item.tag = tag.trim()
      state[kind].push(item)
    },
    removeItem(kind: 'skills' | 'knowledge' | 'subAgents', i: number) { state[kind].splice(i, 1) },

    addSource(label: string, level: Confidential, access: AccessLevel) {
      const l = label.trim()
      if (!l) return
      state.dataSources.push({ label: l, level, access })
    },
    removeSource(i: number) { state.dataSources.splice(i, 1) }
  }
}
