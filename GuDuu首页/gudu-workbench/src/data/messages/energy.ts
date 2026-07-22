import { reactive } from 'vue'
import type { DayMessages } from '@/types/message'

const saleBot = {
  type: 'bot' as const,
  name: '销售分身',
  avatar: '销'
}

export const energyMessages: DayMessages[] = reactive([
  {
    daySep: '今天 · 2026年6月12日',
    messages: [
      {
        id: 'e1',
        sender: saleBot,
        time: '08:30',
        html: '早安。完成夜间行情扫描与产销比对，<b>今日 5 条产销建议</b>已生成。预计采纳后日均降损增收 <b>¥ 53,300</b>。'
      },
      {
        id: 'e2',
        sender: saleBot,
        time: '08:31',
        rich: {
          variant: 'ok',
          tag: 'SUGGESTION',
          title: '渠道配比优化 · 优先去库存',
          meta: '日增收 ¥ 18,600',
          paragraph: '批发价连续 5 日走低，电商渠道客单价坚挺。建议将批发渠道出货占比由 <code>32%</code> 调至 <code>24%</code>，电商直发占比提高至 <code>46%</code>，优先消化冷库临期批次。',
          kv: [
            { k: 'current_ratio', v: '电商 38% / 批发 32% / 商超 30%' },
            { k: 'target_ratio',  v: '电商 46% / 批发 24% / 商超 30%' },
            { k: 'gain',          v: '¥ 18,600/天' },
            { k: 'confidence',    v: '92%' }
          ],
          actions: [
            { label: '应用建议', primary: true },
            { label: '查看依据' },
            { label: '忽略' }
          ]
        }
      },
      {
        id: 'e3',
        sender: saleBot,
        time: '09:05',
        html: '已生成 7 日行情趋势图，<b>大黄鱼批发价持续低于历史平均</b>，建议本周以去库存为主。',
        chartCard: {
          chartId: 'chTrend',
          title: '大黄鱼批发价 7 日：实际 vs AI 预测 vs 历史平均'
        }
      },
      {
        id: 'e4',
        sender: saleBot,
        time: '09:34',
        html: '今日加急订单 <code>#SO-0612-01</code> 货源已锁定，分配如下（联动总控分身）：',
        chartCard: {
          chartId: 'chUnit',
          title: '今日货源分配：可供 vs 锁定'
        }
      }
    ]
  }
])
