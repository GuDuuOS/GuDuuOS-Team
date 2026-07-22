import { reactive } from 'vue'
import type { DayMessages } from '@/types/message'

const alertBot = {
  type: 'bot' as const,
  name: '运维预警分身',
  avatar: '警'
}

const duuBot = {
  type: 'bot' as const,
  name: 'GuDuu',
  avatar: 'G'
}

export const safetyMessages: DayMessages[] = reactive([
  {
    daySep: '今天 · 2026年6月12日',
    messages: [
      {
        id: 's1',
        sender: alertBot,
        time: '09:28',
        html: '完成 <code>渔船定位 / 水质传感 / 冷库温控</code> 例行巡检，<b>全部正常</b>。'
      },
      {
        id: 's2',
        sender: alertBot,
        time: '09:35',
        html: '检测到 <code>3 号冷库 · 温感探头</code> 数据缺失，已派发工单 <code>#WO-0608</code> 给运维组陈工。',
        rich: {
          variant: 'info',
          tag: 'WORK ORDER',
          title: '冷库温感数据缺失',
          meta: '#WO-0608 · 常规',
          kv: [
            { k: 'device',   v: '3 号冷库 / 温感探头 T-12' },
            { k: 'assignee', v: '陈工 (运维组)' },
            { k: 'deadline', v: '今日 12:00' }
          ]
        }
      },
      {
        id: 's3',
        sender: alertBot,
        time: '15:21',
        html: '⚠ 冷链车 <code>闽A·D2371</code> 厢温持续爬升，已越过 <b>4.0℃ 上限阈值</b>。',
        rich: {
          variant: 'warn',
          tag: 'COLD CHAIN',
          title: '冷链车厢温越限',
          meta: '#WO-0612 · 中优先级',
          paragraph: '近 8 分钟厢温由 3.78℃ 升至 <b>4.06℃</b>，模型推断<b>制冷机组滤网堵塞</b>可能性最高。已通知司机靠服务区检查，并将该车次加入"重点关注"看板。',
          kv: [
            { k: 'current',  v: '4.06 ℃' },
            { k: 'limit',    v: '4.00 ℃' },
            { k: 'forecast', v: '未处置情况下 1h 内将影响鲜度等级' }
          ],
          actions: [
            { label: '查看温度趋势', primary: true },
            { label: '转给调度' },
            { label: '查处置预案' }
          ]
        }
      },
      {
        id: 's3b',
        sender: alertBot,
        time: '15:22',
        chartCard: { chartId: 'chP201', title: '冷链车 闽A·D2371 厢温：实测 vs 上限' }
      },
      {
        id: 's4',
        sender: { type: 'human', name: '赵船长', avatar: '赵', color: '#5a7a8a' },
        time: '15:30',
        html: '@运维预警分身 把今早码头卸货区的"异常行为"记录帧调出来给我。'
      },
      {
        id: 's5',
        sender: alertBot,
        time: '15:31',
        html: '今日共 <b>2 起</b>"异常行为"识别，<b>最新一起</b>来自 <code>码头卸货区·CAM03</code>：',
        rich: {
          variant: 'alert',
          tag: 'CRITICAL',
          title: '卸货作业未穿戴救生衣',
          meta: '#WO-0613 · 高优先级',
          paragraph: '识别置信度 <b>96%</b>，模型 <code>Vision v3</code>，推理延时 23ms。工单已派发给安全员张师傅，预计 5 分钟内到位处置。',
          cctv: {
            timestamp: '2026-06-12 07:42:11',
            camera: 'CAM-03 · 码头卸货区',
            boxes: [
              { label: 'no-lifevest · 96%', left: '56%', top: '43%', width: '9%', height: '24%' }
            ]
          },
          actions: [
            { label: '查看完整录像', primary: true },
            { label: '追加抄送' },
            { label: '归档' }
          ]
        }
      },
      {
        id: 's6',
        sender: { type: 'human', name: '林经理', avatar: '林', color: '#7a5a3a' },
        time: '15:35',
        html: '@GuDuu 把本月全链路"异常事件"汇总成表给我，按环节分类。'
      },
      {
        id: 's7',
        sender: duuBot,
        time: '15:35',
        html: '好的林经理，本月共 <b>11 起</b>，按环节分布如下：',
        chartCard: {
          chartId: 'chHelmet',
          title: '本月"异常事件" · 按环节'
        },
        trailingHtml: '需要我把详细清单导出 Excel，或者发起一次安全作业培训通知吗？'
      },
      {
        id: 's8',
        sender: alertBot,
        time: '16:02',
        html: '⚠ <b>强对流天气预警</b>：明日近海风力 8–9 级，建议暂停明日出海计划。已推送 <b>捕捞分身、总控分身</b>，联动详情见 <code>#预警-风险联动</code> 频道。'
      }
    ]
  }
])
