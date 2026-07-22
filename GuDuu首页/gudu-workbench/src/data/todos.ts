import { reactive } from 'vue'

export type TodoStatus = 'pending' | 'in_progress' | 'done'
export type TodoPriority = 'high' | 'mid' | 'low'

export interface TodoItem {
  id: string
  title: string
  /** 来源场景，跟左侧频道 id 对应，方便联跳 */
  source?: string
  sourceLabel?: string
  status: TodoStatus
  priority: TodoPriority
  assignee?: string
  due?: string
  /** 工单号 / 票据号 */
  refNo?: string
}

export interface TodoGroup {
  id: string
  title: string
  /** 分组下面的备注（例如"今日截止 5 项"）*/
  meta?: string
  items: TodoItem[]
}

export interface TodoSummary {
  total: number
  pending: number
  inProgress: number
  done: number
  overdue: number
}

export interface WorkspaceTodos {
  groups: TodoGroup[]
  summary: TodoSummary
}

export const todoMap: Record<string, WorkspaceTodos> = reactive({
  /* ===== 总控中心 ===== */
  hq: {
    summary: { total: 23, pending: 9, inProgress: 7, done: 7, overdue: 1 },
    groups: [
      {
        id: 'today', title: '今日截止', meta: '5 项',
        items: [
          { id: 'hq-1', title: '批准 4000 斤加急订单货源分配方案', source: 'order-flow', sourceLabel: '总控-订单全链路', status: 'done', priority: 'high', assignee: '林经理', due: '今日 09:35', refNo: '#SO-0612-01' },
          { id: 'hq-2', title: '裁定双加急订单货源冲突分配', source: 'conflict', sourceLabel: '协商-货源冲突', status: 'done', priority: 'high', assignee: '林经理', due: '今日 14:30', refNo: '#SO-0612-02/03' },
          { id: 'hq-3', title: '确认强对流天气停航与养殖补供方案', source: 'risk-alert', sourceLabel: '预警-风险联动', status: 'in_progress', priority: 'high', assignee: '林经理', due: '今日 17:00' }
        ]
      },
      {
        id: 'this-week', title: '本周待办', meta: '12 项',
        items: [
          { id: 'hq-4', title: '复核 4 号塘病害预警处置进展', source: 'risk-alert', sourceLabel: '预警-风险联动', status: 'in_progress', priority: 'high', assignee: '养殖分身', due: '本周五', refNo: '#RW-0610-04' },
          { id: 'hq-5', title: '审阅本周全链路损耗复盘报告', source: 'trace-sync', sourceLabel: '数据-溯源同步', status: 'pending', priority: 'mid', assignee: '林经理', due: '本周五', refNo: '#RP-W24' },
          { id: 'hq-6', title: '组织产销月度协调会', source: 'order-flow', sourceLabel: '总控-订单全链路', status: 'pending', priority: 'mid', assignee: '林经理', due: '6/16 周二' },
          { id: 'hq-7', title: '核对溯源链上数据同步记录', source: 'trace-sync', sourceLabel: '数据-溯源同步', status: 'done', priority: 'low', assignee: 'GuDuu', refNo: '#DS-0612-11' }
        ]
      },
      {
        id: 'long-term', title: '中长期跟进', meta: '6 项',
        items: [
          { id: 'hq-8', title: '下季度备货与塘口投苗计划评审', status: 'pending', priority: 'high', assignee: '林经理 / 养殖基地', due: '6/25' },
          { id: 'hq-9', title: '冷库扩容方案（库容已达 82%）', status: 'in_progress', priority: 'mid', assignee: '孙库管', due: '7/10' },
          { id: 'hq-10', title: '渠道客户溯源看板上线', source: 'trace-sync', sourceLabel: '数据-溯源同步', status: 'done', priority: 'low', assignee: '林经理', due: '6/10' }
        ]
      }
    ]
  },

  /* ===== 捕捞船队 ===== */
  fish: {
    summary: { total: 15, pending: 6, inProgress: 4, done: 5, overdue: 1 },
    groups: [
      {
        id: 'today', title: '今日截止', meta: '4 项',
        items: [
          { id: 'fish-1', title: '全部渔船回港避风确认（强对流预警）', source: 'fish-safety', sourceLabel: '捕捞-出海安全', status: 'in_progress', priority: 'high', assignee: '赵船长', due: '今日 18:00', refNo: '#WX-0612' },
          { id: 'fish-2', title: '闽蓝 012 当日渔获 1000 斤过磅上报', source: 'fish-catch', sourceLabel: '捕捞-渔获上报', status: 'done', priority: 'high', assignee: '吴大副', due: '今日 10:00', refNo: '#BL-0612-2' },
          { id: 'fish-3', title: '提交明日停航报备单', source: 'fish-dispatch', sourceLabel: '捕捞-渔船调度', status: 'pending', priority: 'mid', assignee: '赵船长', due: '今日 20:00' }
        ]
      },
      {
        id: 'this-week', title: '本周待办', meta: '7 项',
        items: [
          { id: 'fish-4', title: '闽蓝 009 主机检修验收', source: 'fish-maint', sourceLabel: '捕捞-设备维护', status: 'in_progress', priority: 'mid', assignee: '机务组', due: '本周五', refNo: '#WX-0609' },
          { id: 'fish-5', title: '渔获冰鲜舱温控传感器校准', source: 'fish-maint', sourceLabel: '捕捞-设备维护', status: 'pending', priority: 'mid', assignee: '机务组', due: '本周四' },
          { id: 'fish-6', title: '上月出海安全台账归档', source: 'fish-safety', sourceLabel: '捕捞-出海安全', status: 'done', priority: 'low', assignee: '赵船长', due: '6/8' }
        ]
      }
    ]
  },

  /* ===== 养殖基地 ===== */
  farm: {
    summary: { total: 14, pending: 5, inProgress: 5, done: 4, overdue: 0 },
    groups: [
      {
        id: 'today', title: '今日截止', meta: '4 项',
        items: [
          { id: 'farm-1', title: '1 号塘紧急出塘 1500 斤（加急订单）', source: 'farm-harvest', sourceLabel: '养殖-出塘报备', status: 'done', priority: 'high', assignee: '黄塘长', due: '今日 09:50', refNo: '#YZ-0612-7' },
          { id: 'farm-2', title: '4 号塘病害预警复核与取样送检', source: 'farm-disease', sourceLabel: '养殖-病害防治', status: 'in_progress', priority: 'high', assignee: '徐技术员', due: '今日 16:00', refNo: '#BH-0612-1' },
          { id: 'farm-3', title: '评估 2、4 号塘增供 2500 斤/日能力', source: 'farm-harvest', sourceLabel: '养殖-出塘报备', status: 'in_progress', priority: 'high', assignee: '养殖分身', due: '今日 17:00' }
        ]
      },
      {
        id: 'this-week', title: '本周待办', meta: '6 项',
        items: [
          { id: 'farm-4', title: '台风前网箱加固巡查', source: 'farm-pond', sourceLabel: '养殖-塘口日常', status: 'pending', priority: 'high', assignee: '黄塘长', due: '本周四', refNo: '#JG-0612' },
          { id: 'farm-5', title: '水质传感器月度校准（36 点位）', source: 'farm-water', sourceLabel: '养殖-水质监测', status: 'pending', priority: 'mid', assignee: '徐技术员', due: '本周五' },
          { id: 'farm-6', title: '上批苗种生长数据归档', source: 'farm-pond', sourceLabel: '养殖-塘口日常', status: 'done', priority: 'low', assignee: '徐技术员', due: '6/9' }
        ]
      }
    ]
  },

  /* ===== 加工中心 ===== */
  proc: {
    summary: { total: 13, pending: 4, inProgress: 5, done: 4, overdue: 0 },
    groups: [
      {
        id: 'today', title: '今日截止', meta: '4 项',
        items: [
          { id: 'proc-1', title: '加急单 4000 斤分拣包装（双线作业）', source: 'proc-plan', sourceLabel: '加工-车间排产', status: 'done', priority: 'high', assignee: '钱厂长', due: '今日 11:10', refNo: '#SO-0612-01' },
          { id: 'proc-2', title: '成品 3952 斤移交仓储并核对损耗', source: 'proc-line', sourceLabel: '加工-生产进度', status: 'done', priority: 'high', assignee: '包装组', due: '今日 11:30' },
          { id: 'proc-3', title: '预制菜线明日排产确认', source: 'proc-plan', sourceLabel: '加工-车间排产', status: 'pending', priority: 'mid', assignee: '钱厂长', due: '今日 18:00' }
        ]
      },
      {
        id: 'this-week', title: '本周待办', meta: '6 项',
        items: [
          { id: 'proc-4', title: '速冻线压缩机保养', source: 'proc-equip', sourceLabel: '加工-设备保养', status: 'in_progress', priority: 'mid', assignee: '设备组', due: '本周五', refNo: '#EQ-0610' },
          { id: 'proc-5', title: '车间卫生与留样室月度自查', source: 'proc-qc', sourceLabel: '加工-质量管控', status: 'pending', priority: 'mid', assignee: '质检分身', due: '本周四' },
          { id: 'proc-6', title: '上月产线损耗分析归档', source: 'proc-line', sourceLabel: '加工-生产进度', status: 'done', priority: 'low', assignee: '钱厂长', due: '6/8' }
        ]
      }
    ]
  },

  /* ===== 销售公司 ===== */
  sale: {
    summary: { total: 19, pending: 8, inProgress: 6, done: 5, overdue: 2 },
    groups: [
      {
        id: 'today', title: '今日截止', meta: '6 项',
        items: [
          { id: 'sale-1', title: '加急订单 #SO-0612-01 物流信息同步客户', source: 'sale-orders', sourceLabel: '销售-订单接龙', status: 'done', priority: 'high', assignee: '销售分身', due: '今日 11:30', refNo: '#WL-0612-09' },
          { id: 'sale-2', title: '货源变动通知 12 家渠道客户（停航预警）', source: 'sale-channel', sourceLabel: '销售-渠道对接', status: 'in_progress', priority: 'high', assignee: '周专员', due: '今日 17:00' },
          { id: 'sale-3', title: '订单 B 客户运费减免沟通（负责人裁定）', source: 'sale-orders', sourceLabel: '销售-订单接龙', status: 'pending', priority: 'high', assignee: '林经理', due: '今日 16:00', refNo: '#SO-0612-03' }
        ]
      },
      {
        id: 'this-week', title: '本周待办', meta: '9 项',
        items: [
          { id: 'sale-4', title: '批发价走低 · 去库存促销方案', source: 'sale-market', sourceLabel: '销售-行情分析', status: 'in_progress', priority: 'high', assignee: '销售分身', due: '本周五', refNo: '#MK-0612' },
          { id: 'sale-5', title: '逾期账款跟进（2 家）', source: 'sale-channel', sourceLabel: '销售-渠道对接', status: 'pending', priority: 'mid', assignee: '周专员', due: '本周四' },
          { id: 'sale-6', title: '月度行情复盘报告', source: 'sale-market', sourceLabel: '销售-行情分析', status: 'done', priority: 'low', assignee: '销售分身', due: '6/8' }
        ]
      }
    ]
  }
})

export const fallbackTodoId = 'hq'

export function getTodos(id: string): WorkspaceTodos {
  return todoMap[id] ?? todoMap[fallbackTodoId]
}

/** 各工作区的初始状态计数（模块加载即快照，作为汇总卡增量基准；晚于此的增删改都会反映为 ±N）*/
export const initialStatusCounts: Record<string, Record<TodoStatus, number>> = {}
for (const [id, w] of Object.entries(todoMap)) {
  const items = w.groups.flatMap((g) => g.items)
  initialStatusCounts[id] = {
    pending: items.filter((t) => t.status === 'pending').length,
    in_progress: items.filter((t) => t.status === 'in_progress').length,
    done: items.filter((t) => t.status === 'done').length
  }
}
