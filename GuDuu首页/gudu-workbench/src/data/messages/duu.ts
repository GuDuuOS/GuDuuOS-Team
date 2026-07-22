import { reactive } from 'vue'
import type { DayMessages } from '@/types/message'

export const duuMessages: DayMessages[] = reactive([
  {
    daySep: '今天 · 2026年6月12日',
    messages: [
      {
        id: 'd1',
        sender: { type: 'bot', name: 'GuDuu', avatar: 'G' },
        time: '09:00',
        html: '早安，林经理 👋 全链路 8 个分身在线，今日有 <b>1 笔加急订单</b>与 <b>1 条海况预警</b>待关注。<br/>试试输入 <code>/</code> 调出命令，或者直接问我任何事。'
      }
    ]
  }
])

export interface SlashCommand {
  cmd: string
  desc: string
}

export const slashCommands: SlashCommand[] = [
  { cmd: '/image',    desc: 'AI 生成配图（海报 / 示意图），如 /image 礼盒海报' },
  { cmd: '/summary',  desc: '自动总结本频道今日要点' },
  { cmd: '/todo',     desc: '快速创建待办，如 /todo 联系承运商对账' },
  { cmd: '/dispatch', desc: '货源智能调度（库存 → 养殖 → 捕捞 自动匹配）' },
  { cmd: '/trace',    desc: '批次溯源查询 · 海域 / 塘口 / 加工 / 冷链全链路' },
  { cmd: '/market',   desc: '行情分析与产销策略建议' },
  { cmd: '/qc',       desc: '生成批次质检报告' },
  { cmd: '/report',   desc: '生成产销报告（日报/周报/订单复盘）' }
]
