import { reactive } from 'vue'
import type { DayMessages } from '@/types/message'
import type { OpsChannelMeta } from '@/types/channel'

interface OpsScenario {
  meta: OpsChannelMeta
  days: DayMessages[]
}

const today = '今天 · 2026年6月12日'

/* ===== 常用发送方 ===== */
const duuBot   = { type: 'bot' as const, name: 'GuDuu 总控分身',  avatar: 'G' }
const saleBot  = { type: 'bot' as const, name: '销售分身',        avatar: '销' }
const procBot  = { type: 'bot' as const, name: '加工分身',        avatar: '加' }
const farmBot  = { type: 'bot' as const, name: '养殖分身',        avatar: '养' }
const fishBot  = { type: 'bot' as const, name: '捕捞分身',        avatar: '捕' }
const qcBot    = { type: 'bot' as const, name: '质检分身',        avatar: '质' }
const whBot    = { type: 'bot' as const, name: '仓储物流分身',    avatar: '仓' }
const alertBot = { type: 'bot' as const, name: '运维预警分身',    avatar: '警' }

const lin   = { type: 'human' as const, name: '林经理',   avatar: '林', color: '#7a5a3a' }
const zhou  = { type: 'human' as const, name: '周专员',   avatar: '周', color: '#8a6a8a' }
const zhao  = { type: 'human' as const, name: '赵船长',   avatar: '赵', color: '#5a7a8a' }
const wu    = { type: 'human' as const, name: '吴大副',   avatar: '吴', color: '#7a8a5a' }
const huang = { type: 'human' as const, name: '黄塘长',   avatar: '黄', color: '#7a8a5a' }
const xu    = { type: 'human' as const, name: '徐技术员', avatar: '徐', color: '#8a6a8a' }
const qian  = { type: 'human' as const, name: '钱厂长',   avatar: '钱', color: '#a07050' }
const sun   = { type: 'human' as const, name: '孙库管',   avatar: '孙', color: '#7a8a5a' }

/** ========== 总控-订单全链路（核心演示：6 步闭环）========== */
const orderFlow: OpsScenario = {
  meta: {
    title: '总控-订单全链路',
    topic: '接单 → 货源匹配 → 出库质检 → 加工 → 冷链发货 → 复盘 · A2A 自动流转',
    memberCount: 16,
    stack: [
      { label: 'G', bot: true },
      { label: '销', bot: true },
      { label: '林', color: '#7a5a3a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        /* —— 步骤 1：销售接单，任务下发（人 → 销售分身）—— */
        {
          id: 'of-0',
          sender: zhou,
          time: '09:30',
          html: '刚接到<b>加急订单</b>：生鲜海鱼 <b>4000 斤</b>，明早 8:00 前送达福州仓山区客户冷库。@销售分身 录入处理。'
        },
        {
          id: 'of-1',
          sender: saleBot,
          time: '09:30',
          html: '<b>① 订单解析</b> 完成。已通过 A2A 协议将需求推送至 <b>总控分身、加工分身、仓储物流分身</b>。',
          rich: {
            variant: 'info',
            tag: 'ORDER',
            title: '加急订单 #SO-0612-01',
            meta: '线上电商 + 线下渠道同步 · 加急',
            kv: [
              { k: 'category', v: '生鲜海鱼（大黄鱼为主）' },
              { k: 'quantity', v: '4,000 斤' },
              { k: 'deadline', v: '明日 08:00 前送达' },
              { k: 'address',  v: '福州 · 仓山区客户冷库' }
            ],
            actions: [
              { label: '查看订单详情', primary: true },
              { label: '同步客户' }
            ]
          }
        },

        /* —— 步骤 2：全局调度，货源匹配（分身间协商）—— */
        {
          id: 'of-2',
          sender: procBot,
          time: '09:31',
          html: '<b>② 产能核查</b> 今日剩余产能 <b>6,000 斤</b>，可承接 4,000 斤加工任务，预计 <b>1 小时</b>完成分拣包装。'
        },
        {
          id: 'of-3',
          sender: duuBot,
          time: '09:31',
          html: '<b>② 库存核查</b> 冷库现有库存 <b>2,000 斤</b>，缺口 <b>2,000 斤</b>。已向 <b>养殖分身、捕捞分身</b> 发起货源征询（A2A · 多方协商）。'
        },
        {
          id: 'of-4',
          sender: farmBot,
          time: '09:32',
          html: '反馈：1 号塘成品鱼可<b>紧急出塘 1,500 斤</b>，15 分钟内可运抵加工厂。'
        },
        {
          id: 'of-5',
          sender: fishBot,
          time: '09:32',
          html: '反馈：<code>闽蓝 012</code> 已返航，当日新鲜渔获 <b>1,000 斤</b>，30 分钟内可入库。'
        },
        {
          id: 'of-6',
          sender: duuBot,
          time: '09:33',
          html: '<b>② 多方协商达成共识</b>：库存 2000 + 养殖 1500 + 捕捞 1000 = <b>4,500 斤 ≥ 4,000 斤</b>，满足订单需求。',
          rich: {
            variant: 'ok',
            tag: 'SOURCING PLAN',
            title: '货源匹配方案（已锁定，待人工终审）',
            meta: '分配原则：冷库优先 → 养殖补量 → 捕捞收尾',
            kv: [
              { k: 'cold_store', v: '2,000 斤（全部启用）' },
              { k: 'aquafarm',   v: '1,500 斤（1 号塘紧急出塘）' },
              { k: 'catch',      v: '500 斤（剩余 500 斤转常规库存）' },
              { k: 'eta',        v: '预计 11:10 完成加工 · 明日 07:20 送达' }
            ],
            actions: [
              { label: '批准执行', primary: true },
              { label: '调整分配' },
              { label: '驳回' }
            ]
          }
        },
        {
          id: 'of-7',
          sender: duuBot,
          time: '09:33',
          chartCard: { chartId: 'chUnit', title: '货源分配：可供 vs 锁定（斤）' }
        },
        {
          id: 'of-8',
          sender: lin,
          time: '09:35',
          html: '方案没问题，<b>批准执行</b> ✅。加急单全程注意冷链温度，损耗按基线考核。'
        },

        /* —— 步骤 3：货源出库 + 渔获转运 → 质检 —— */
        {
          id: 'of-9',
          sender: farmBot,
          time: '09:36',
          html: '<b>③ 出塘转运</b> 已启动紧急出塘，批次 <code>#YZ-0612-7</code>，1,500 斤装车发往加工厂，实时推送数量与批次信息。'
        },
        {
          id: 'of-10',
          sender: fishBot,
          time: '09:38',
          html: '<b>③ 渔获转运</b> 批次 <code>#BL-0612-2</code> 完成分拣过磅 500 斤，随冷藏车转运中。'
        },
        {
          id: 'of-11',
          sender: qcBot,
          time: '09:55',
          html: '<b>③ 抽检完成</b> 货品抵厂，系统自动触发抽检流程：',
          rich: {
            variant: 'ok',
            tag: 'QC PASS',
            title: '质检报告 #QC-0612-15 · 检验合格',
            meta: '农残 / 兽残 / 重金属 / 鲜度(K 值) 全部合格',
            paragraph: '报告已同步至 <b>仓储、销售、总控分身</b>，批次溯源信息已上链存证。',
            kv: [
              { k: 'batches',   v: '#LK-0610-3 / #YZ-0612-7 / #BL-0612-2' },
              { k: 'freshness', v: 'K 值 12%（一级鲜度）' },
              { k: 'residue',   v: '未检出' }
            ],
            actions: [
              { label: '查看质检报告', primary: true },
              { label: '溯源详情' }
            ]
          }
        },

        /* —— 步骤 4：车间加工生产 —— */
        {
          id: 'of-12',
          sender: procBot,
          time: '10:05',
          html: '<b>④ 排产启动</b> 已接收合格货品 4,000 斤，自动拆分 <b>生鲜分拣线 + 包装线</b> 双线作业，排班 12 人。进度将实时同步销售分身（客户进度）与总控分身（全局监控）。'
        },
        {
          id: 'of-13',
          sender: procBot,
          time: '10:40',
          html: '加工进度 <b>65%</b>，预计 11:10 完成。',
          chartCard: { chartId: 'chProd', title: '加急订单加工进度：完成量 vs 计划' }
        },
        {
          id: 'of-14',
          sender: procBot,
          time: '11:08',
          html: '<b>④ 加工完成</b> ✅ 成品 <b>3,952 斤</b>（损耗率 1.2%，低于基线 0.6 pct），成品信息已推送仓储物流分身。'
        },

        /* —— 步骤 5：冷链打包 & 配送 —— */
        {
          id: 'of-15',
          sender: whBot,
          time: '11:20',
          html: '<b>⑤ 冷链履约</b> 入库称重、分区存放完成；已匹配冷链车并规划最优配送路线：',
          rich: {
            variant: 'info',
            tag: 'COLD CHAIN',
            title: '物流单 #WL-0612-09',
            meta: '冷链车 闽A·D2371 · 全程厢温 ≤ 4℃ 实时监控',
            kv: [
              { k: 'depart',  v: '明日 05:30 发车' },
              { k: 'eta',     v: '明日 07:20 送达（提前 40 分钟）' },
              { k: 'route',   v: '加工厂 → 沈海高速 → 仓山区客户冷库' }
            ],
            actions: [
              { label: '跟踪冷链温度', primary: true },
              { label: '同步客户' }
            ]
          }
        },
        {
          id: 'of-16',
          sender: saleBot,
          time: '11:21',
          html: '<b>⑤ 客户同步</b> 物流单号与预计送达时间已自动推送至客户端，客户已确认收货安排。'
        },

        /* —— 步骤 6：数据汇总 + 复盘（分身 → 企业负责人）—— */
        {
          id: 'of-17',
          sender: duuBot,
          time: '11:25',
          html: '<b>⑥ 订单复盘</b> 全流程完成，自动汇总本单数据：',
          rich: {
            variant: 'info',
            tag: 'REPORT',
            title: '订单复盘 #SO-0612-01',
            meta: '可视化报表已推送至负责人账号',
            kv: [
              { k: 'sourcing', v: '冷库 50% / 养殖 37.5% / 捕捞 12.5%' },
              { k: 'process',  v: '加工时长 1 小时 03 分' },
              { k: 'loss',     v: '损耗率 1.2%（基线 1.8%）' },
              { k: 'lead',     v: '接单 → 发运就绪 1 小时 55 分' },
              { k: 'profit',   v: '预计毛利 ¥ 18,400' }
            ],
            actions: [
              { label: '查看可视化报表', primary: true },
              { label: '下达备货指令' },
              { label: '调价策略建议' }
            ]
          },
          trailingHtml: '负责人可在此直接下达后续<b>备货、调价</b>等新指令，进入下一轮循环。'
        }
      ]
    }
  ]
}

/** ========== 预警-风险联动（拓展场景 A：海况应急）========== */
const riskAlert: OpsScenario = {
  meta: {
    title: '预警-风险联动',
    topic: '天气 / 海况 / 设备 / 病害 实时联动预警 · 自动调整产销策略',
    memberCount: 14,
    stack: [
      { label: '警', bot: true },
      { label: '捕', bot: true },
      { label: '林', color: '#7a5a3a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'ra-0',
          sender: alertBot,
          time: '16:02',
          html: '⚠ 监测到<b>强对流天气</b>来袭，近海捕捞作业风险升高。已自动推送至 <b>捕捞分身、总控分身</b>。',
          rich: {
            variant: 'alert',
            tag: 'WEATHER ALERT',
            title: '强对流天气预警 · 闽东渔场',
            meta: '气象台 16:00 发布 · 高优先级',
            kv: [
              { k: 'wind',   v: '8–9 级，阵风 10 级' },
              { k: 'wave',   v: '浪高 3.5 m' },
              { k: 'period', v: '明日 06:00 – 18:00' },
              { k: 'scope',  v: '闽东渔场 / 近海网箱区' }
            ],
            actions: [
              { label: '查看海况云图', primary: true },
              { label: '上报总控' }
            ]
          }
        },
        {
          id: 'ra-1',
          sender: fishBot,
          time: '16:03',
          html: '已<b>暂停明日全部出海计划</b>，6 艘渔船回港避风。预计短期新鲜渔获减产约 <b>3,000 斤/日</b>，已同步销售分身。'
        },
        {
          id: 'ra-2',
          sender: saleBot,
          time: '16:04',
          html: '接单策略已调整：暂停「次日达生鲜」承诺，<b>优先消化冷库现有库存</b>；货源变动通知已推送 <b>12 家渠道客户</b>。'
        },
        {
          id: 'ra-3',
          sender: duuBot,
          time: '16:05',
          html: '<b>总控统筹</b>：未来 2 日提高<b>养殖品类供货占比至 70%</b>，平衡供需。请养殖分身评估出塘能力。'
        },
        {
          id: 'ra-4',
          sender: farmBot,
          time: '16:06',
          html: '评估完成：2、4 号塘可增加出塘 <b>2,500 斤/日</b>，规格与水质均满足出塘标准，供需可平衡。同时已安排<b>台风前网箱加固巡查</b>。'
        },
        {
          id: 'ra-5',
          sender: lin,
          time: '16:08',
          html: '同意按此执行 ✅。恢复出海前每 6 小时同步一次海况，网箱加固今晚完成。'
        },
        {
          id: 'ra-6',
          sender: alertBot,
          time: '16:08',
          html: '收到。已设置<b>海况定时播报（每 6 小时）</b>，风险解除后将自动提醒恢复出海评估。'
        }
      ]
    }
  ]
}

/** ========== 协商-货源冲突（拓展场景 B：多订单抢货）========== */
const conflict: OpsScenario = {
  meta: {
    title: '协商-货源冲突',
    topic: '多订单抢货 · 分身自动比对优先级 / 利润 / 合作等级 · 超权限上报人工裁定',
    memberCount: 12,
    stack: [
      { label: '销', bot: true },
      { label: 'G', bot: true },
      { label: '林', color: '#7a5a3a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'cf-0',
          sender: saleBot,
          time: '14:20',
          html: '⚠ 同时接到 <b>2 笔加急订单</b>，总需求 <b>5,200 斤</b>，当前可调配货源仅 <b>3,000 斤</b>，触发多方协商博弈。'
        },
        {
          id: 'cf-1',
          sender: saleBot,
          time: '14:21',
          rich: {
            variant: 'warn',
            tag: 'CONFLICT',
            title: '货源冲突 · 订单优先级比对',
            meta: '#SO-0612-02 vs #SO-0612-03',
            kv: [
              { k: 'order_A', v: '商超渠道 3,000 斤 · 毛利率 22% · 合作等级 S 级（年度框架）' },
              { k: 'order_B', v: '餐饮直供 2,200 斤 · 毛利率 31% · 合作等级 A 级' },
              { k: 'risk',    v: '订单 A 已签年度框架，违约成本高' }
            ]
          }
        },
        {
          id: 'cf-2',
          sender: duuBot,
          time: '14:22',
          html: '<b>协商结论</b>（3 轮博弈）：优先满足<b>订单 A 全量 3,000 斤</b>；订单 B 建议拆分为<b>今日 1,200 斤 + 明日补足 1,000 斤</b>。该分配涉及客户承诺调整，<b>超出分身决策权限，上报负责人裁定</b>。',
          rich: {
            variant: 'info',
            tag: 'PROPOSAL',
            title: '分配方案（待人工裁定）',
            meta: '依据：合作等级 > 违约成本 > 单笔利润',
            kv: [
              { k: 'plan_A', v: '订单 A：今日全量交付 3,000 斤' },
              { k: 'plan_B', v: '订单 B：今日 1,200 斤 + 明日 1,000 斤（养殖增量出塘）' }
            ],
            actions: [
              { label: '按方案执行', primary: true },
              { label: '人工改派' }
            ]
          }
        },
        {
          id: 'cf-3',
          sender: lin,
          time: '14:25',
          html: '同意方案 ✅。订单 B 客户由我亲自电话沟通，给予<b>运费减免</b>作为补偿。'
        },
        {
          id: 'cf-4',
          sender: saleBot,
          time: '14:26',
          html: '已按裁定<b>锁定货源</b>并回复两位客户；运费减免已记入订单 B 账单，明日补量已联动养殖分身排产。'
        }
      ]
    }
  ]
}

/** ========== 审批-异常裁定（总控）========== */
const approvals: OpsScenario = {
  meta: {
    title: '审批-异常裁定',
    topic: '关键操作人工终审 · 紧急调货 / 停产停航 / 冲突裁定 留痕',
    memberCount: 6,
    stack: [
      { label: 'G', bot: true },
      { label: '林', color: '#7a5a3a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'ap-0',
          sender: duuBot,
          time: '09:34',
          html: '新审批事项：养殖分身申请<b>紧急出塘 1,500 斤</b>（关联加急订单 <code>#SO-0612-01</code>）。',
          rich: {
            variant: 'info',
            tag: 'APPROVAL',
            title: '紧急出塘审批 #AP-0612-01',
            meta: '发起：养殖分身 · 优先级 高',
            kv: [
              { k: 'pond',   v: '1 号塘 · 成品大黄鱼' },
              { k: 'amount', v: '1,500 斤' },
              { k: 'reason', v: '加急订单货源缺口补量' }
            ],
            actions: [
              { label: '批准', primary: true },
              { label: '驳回' }
            ]
          }
        },
        {
          id: 'ap-1',
          sender: lin,
          time: '09:35',
          html: '<b>已批准</b> ✅ 注意出塘规格分级，按订单标准走。'
        },
        {
          id: 'ap-2',
          sender: duuBot,
          time: '14:23',
          html: '新裁定事项：双加急订单<b>货源冲突</b>，分身协商方案已生成（详见 <code>#协商-货源冲突</code>），超出分身决策权限。',
          rich: {
            variant: 'warn',
            tag: 'ARBITRATION',
            title: '货源冲突裁定 #AP-0612-02',
            meta: '发起：销售分身 + 总控分身 · 优先级 高',
            kv: [
              { k: 'demand', v: '订单 A 3,000 斤 + 订单 B 2,200 斤' },
              { k: 'supply', v: '可调配货源 3,000 斤' },
              { k: 'plan',   v: 'A 全量 · B 拆分两日交付' }
            ],
            actions: [
              { label: '按方案裁定', primary: true },
              { label: '人工改派' }
            ]
          }
        },
        {
          id: 'ap-3',
          sender: lin,
          time: '14:25',
          html: '<b>已裁定</b> ✅ 按方案执行，订单 B 运费减免由我跟客户沟通。'
        },
        {
          id: 'ap-4',
          sender: duuBot,
          time: '16:07',
          html: '新审批事项：捕捞分身报备<b>明日全员停航</b>（强对流天气，详见 <code>#预警-风险联动</code>）。',
          rich: {
            variant: 'alert',
            tag: 'APPROVAL',
            title: '停航报备审批 #AP-0612-03',
            meta: '发起：捕捞分身 · 安全类 · 优先级 紧急',
            kv: [
              { k: 'scope',  v: '6 艘渔船 · 明日 06:00–18:00' },
              { k: 'impact', v: '新鲜渔获减产约 3,000 斤/日' },
              { k: 'hedge',  v: '养殖供货占比提至 70%' }
            ],
            actions: [
              { label: '批准停航', primary: true },
              { label: '驳回' }
            ]
          }
        },
        {
          id: 'ap-5',
          sender: lin,
          time: '16:08',
          html: '<b>已批准</b> ✅ 安全第一。恢复出海需重新审批。'
        }
      ]
    }
  ]
}

/** ========== 数据-溯源同步（总控）========== */
const traceSync: OpsScenario = {
  meta: {
    title: '数据-溯源同步',
    topic: '海域 / 塘口 / 加工 / 冷链 全节点数据上链存证 · 扫码可查',
    memberCount: 10,
    stack: [
      { label: 'G', bot: true },
      { label: '质', bot: true },
      { label: '仓', bot: true }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'ts-0',
          sender: duuBot,
          time: '09:40',
          html: '批次 <code>#YZ-0612-7</code>（1 号塘 · 1,500 斤）<b>出塘节点</b>已上链：出塘时间 09:36 · 责任人 黄塘长 · 运输车 闽A·C8821。'
        },
        {
          id: 'ts-1',
          sender: duuBot,
          time: '09:42',
          html: '批次 <code>#BL-0612-2</code>（闽蓝 012 · 1,000 斤）<b>捕捞节点</b>已上链：作业海域 闽东渔场 E-12 · 返航 09:18 · 冰鲜舱温 -1.2℃。'
        },
        {
          id: 'ts-2',
          sender: qcBot,
          time: '09:56',
          html: '质检报告 <code>#QC-0612-15</code> 已上链存证：',
          rich: {
            variant: 'ok',
            tag: 'ON-CHAIN',
            title: '质检节点存证完成',
            meta: '区块高度 #2,841,206',
            kv: [
              { k: 'hash',    v: '0x8f3a…c41d' },
              { k: 'batches', v: '#LK-0610-3 / #YZ-0612-7 / #BL-0612-2' },
              { k: 'result',  v: '全部合格 · 一级鲜度' }
            ],
            actions: [
              { label: '查看链上记录', primary: true },
              { label: '生成溯源码' }
            ]
          }
        },
        {
          id: 'ts-3',
          sender: whBot,
          time: '11:22',
          html: '<b>冷链节点</b>数据流已接入：物流单 <code>#WL-0612-09</code> 厢温每 30 秒采样一次，自动写入溯源链。'
        },
        {
          id: 'ts-3b',
          sender: sun,
          time: '11:24',
          html: '成品入库复核完毕，称重与批次标签一致，溯源码扫码验证通过 ✅'
        },
        {
          id: 'ts-4',
          sender: duuBot,
          time: '11:26',
          html: '今日溯源上链 <b>28 条</b>，覆盖 海域/塘口 → 出塘/捕捞 → 转运 → 质检 → 加工 → 冷链 <b>6 个节点</b>，完整率 <b>100%</b>。'
        },
        {
          id: 'ts-5',
          sender: lin,
          time: '11:30',
          html: '给本单渠道客户开通<b>扫码溯源</b>查看权限，发货时把溯源码贴在外箱上。'
        },
        {
          id: 'ts-6',
          sender: duuBot,
          time: '11:30',
          html: '已开通 ✅ 溯源码已生成并推送仓储物流分身，随 <code>#WL-0612-09</code> 出库张贴。'
        }
      ]
    }
  ]
}

/** ========== 捕捞-渔船调度 ========== */
const fishDispatch: OpsScenario = {
  meta: {
    title: '捕捞-渔船调度',
    topic: '出海计划 · 航次跟踪 · 返航卸货联动',
    memberCount: 9,
    stack: [
      { label: '捕', bot: true },
      { label: '赵', color: '#5a7a8a' },
      { label: '吴', color: '#7a8a5a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'fd-0',
          sender: fishBot,
          time: '05:30',
          html: '<b>今日出海计划</b>已生成（依据海况 3 级 · 适宜作业）：',
          rich: {
            variant: 'info',
            tag: 'DISPATCH',
            title: '6 月 12 日出海计划',
            meta: '4 艘出海 · 2 艘留港',
            kv: [
              { k: 'vessels', v: '闽蓝 001 / 003 / 012 / 015' },
              { k: 'area',    v: '闽东渔场 E-12 / E-14 作业区' },
              { k: 'target',  v: '计划渔获 3,000 斤' },
              { k: 'return',  v: '预计 09:00–10:30 陆续返航' }
            ],
            actions: [
              { label: '确认计划', primary: true },
              { label: '查看航迹' }
            ]
          }
        },
        {
          id: 'fd-1',
          sender: zhao,
          time: '05:32',
          html: '确认 ✅ 闽蓝 009 留港检修，006 留港待卸。各船注意 E-14 区流速。'
        },
        {
          id: 'fd-2',
          sender: fishBot,
          time: '09:20',
          html: '<code>闽蓝 012</code> 已返航靠泊。总控分身有<b>加急订单货源征询</b>，本船次渔获 1,000 斤优先安排过磅转运。'
        },
        {
          id: 'fd-3',
          sender: wu,
          time: '09:22',
          html: '收到，012 优先卸货，码头吊机已就位。'
        },
        {
          id: 'fd-4',
          sender: fishBot,
          time: '16:03',
          html: '⚠ <b>调度变更</b>：接运维预警分身强对流预警，<b>明日全部出海计划暂停</b>，在港渔船加固缆绳。停航报备已提交总控审批。'
        },
        {
          id: 'fd-5',
          sender: zhao,
          time: '16:05',
          html: '收到。各船今晚 20:00 前完成回港避风确认，明早 6 点我到码头巡检。'
        }
      ]
    }
  ]
}

/** ========== 捕捞-渔获上报 ========== */
const fishCatch: OpsScenario = {
  meta: {
    title: '捕捞-渔获上报',
    topic: '渔获过磅 · 批次登记 · 自动同步质检 / 仓储 / 加工 / 销售',
    memberCount: 9,
    stack: [
      { label: '捕', bot: true },
      { label: '吴', color: '#7a8a5a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'fc-0',
          sender: wu,
          time: '09:18',
          html: '闽蓝 012 靠泊完成，渔获开始过磅。@捕捞分身 登记批次。'
        },
        {
          id: 'fc-1',
          sender: fishBot,
          time: '09:20',
          html: '<b>批次登记完成</b>，称重数据由码头电子磅自动采集：',
          rich: {
            variant: 'ok',
            tag: 'CATCH',
            title: '渔获批次 #BL-0612-2',
            meta: '闽蓝 012 · 闽东渔场 E-12 · 冰鲜舱 -1.2℃',
            kv: [
              { k: 'total',   v: '1,000 斤' },
              { k: 'detail',  v: '大黄鱼 620 / 带鱼 240 / 梭子蟹 140' },
              { k: 'quality', v: '感官鲜度 优 · 待入厂抽检' }
            ],
            actions: [
              { label: '查看批次详情', primary: true },
              { label: '打印标签' }
            ]
          }
        },
        {
          id: 'fc-2',
          sender: fishBot,
          time: '09:21',
          html: '批次数据已通过 A2A 自动同步至 <b>质检、仓储、加工、销售分身</b>；其中 <b>500 斤已锁定</b>加急订单 <code>#SO-0612-01</code>，余量转常规库存。'
        },
        {
          id: 'fc-3',
          sender: fishBot,
          time: '17:30',
          html: '<b>今日渔获日报</b>：5 船次合计 <b>3,000 斤</b>（+12% vs 昨日），全部完成批次登记与转运，零滞港。明日因停航无新增渔获，已提前告知销售分身。'
        }
      ]
    }
  ]
}

/** ========== 捕捞-出海安全 ========== */
const fishSafety: OpsScenario = {
  meta: {
    title: '捕捞-出海安全',
    topic: '出海前点检 · 作业行为监控 · 海况预警联动',
    memberCount: 11,
    stack: [
      { label: '警', bot: true },
      { label: '捕', bot: true },
      { label: '赵', color: '#5a7a8a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'fs-0',
          sender: alertBot,
          time: '05:00',
          html: '<b>出海前安全点检</b>完成：4 艘出海渔船救生设备、通信设备、AIS 定位全部正常，今日海况 3 级，<b>准予出海</b>。'
        },
        {
          id: 'fs-1',
          sender: alertBot,
          time: '07:42',
          html: '⚠ <code>码头卸货区·CAM03</code> AI 识别 1 名作业人员<b>未穿戴救生衣</b>（置信度 96%），已派单安全员现场纠正。',
          rich: {
            variant: 'warn',
            tag: 'SAFETY',
            title: '卸货作业未穿戴救生衣',
            meta: '#WO-0613 · 已派单',
            kv: [
              { k: 'camera', v: 'CAM-03 · 码头卸货区' },
              { k: 'action', v: '安全员张师傅 5 分钟内到位' }
            ],
            actions: [
              { label: '查看抓拍帧', primary: true },
              { label: '安全台账' }
            ]
          }
        },
        {
          id: 'fs-2',
          sender: zhao,
          time: '07:50',
          html: '已现场纠正并登记。今天班前会再强调一遍穿戴规范。'
        },
        {
          id: 'fs-3',
          sender: alertBot,
          time: '16:02',
          html: '🌀 <b>强对流天气预警</b>：明日 06:00–18:00 近海风力 8–9 级、浪高 3.5 米，<b>建议停航</b>。已联动捕捞分身与总控分身（详见 <code>#预警-风险联动</code>）。'
        },
        {
          id: 'fs-4',
          sender: fishBot,
          time: '16:10',
          html: '明日出海计划已全部暂停。<b>回港避风确认</b>：闽蓝 001 ✅ / 003 ✅ / 006 ✅ / 009 ✅ / 012 ✅ / 015 ✅，6 艘全部在港。'
        },
        {
          id: 'fs-5',
          sender: zhao,
          time: '20:05',
          html: '缆绳加固完毕，值班表已排。安全作业天数继续保持，明天大家休整。'
        }
      ]
    }
  ]
}

/** ========== 捕捞-设备维护 ========== */
const fishMaint: OpsScenario = {
  meta: {
    title: '捕捞-设备维护',
    topic: '渔船机务 · 传感器校准 · 检修工单跟踪',
    memberCount: 6,
    stack: [
      { label: '警', bot: true },
      { label: '捕', bot: true },
      { label: '赵', color: '#5a7a8a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'fm-0',
          sender: alertBot,
          time: '08:10',
          html: '⚠ <code>闽蓝 009</code> 主机油压持续偏低（2.1 bar，基线 2.8 bar），建议立即检修。',
          rich: {
            variant: 'warn',
            tag: 'MAINTENANCE',
            title: '闽蓝 009 主机油压异常',
            meta: '#WX-0609 · 已停航检修',
            kv: [
              { k: 'reading',  v: '2.1 bar（基线 2.8）' },
              { k: 'diagnose', v: '模型推断：机油滤芯堵塞 概率 78%' },
              { k: 'assignee', v: '机务组' }
            ],
            actions: [
              { label: '查看油压曲线', primary: true },
              { label: '备件库存' }
            ]
          }
        },
        {
          id: 'fm-1',
          sender: fishBot,
          time: '08:12',
          html: '已将 <code>闽蓝 009</code> 移出今日出海序列，检修排期同步至调度计划。备件（滤芯 × 2）库存充足。'
        },
        {
          id: 'fm-2',
          sender: zhao,
          time: '08:15',
          html: '机务组上午进场，更换滤芯后试车，验收报告发这里。'
        },
        {
          id: 'fm-3',
          sender: alertBot,
          time: '15:00',
          html: '提醒：5 艘渔船<b>冰鲜舱温控传感器</b>月度校准本周四截止，当前完成 2/5。明日停航正好集中作业。'
        },
        {
          id: 'fm-4',
          sender: zhao,
          time: '15:06',
          html: '好，明天停航全员在港，传感器校准一次性做完。009 试车正常的话周四复航申请。'
        }
      ]
    }
  ]
}

/** ========== 养殖-塘口日常 ========== */
const farmPond: OpsScenario = {
  meta: {
    title: '养殖-塘口日常',
    topic: '晨巡 / 投喂 / 出塘作业 · 12 处塘口网箱实时联动',
    memberCount: 8,
    stack: [
      { label: '养', bot: true },
      { label: '黄', color: '#7a8a5a' },
      { label: '徐', color: '#8a6a8a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'fp-0',
          sender: farmBot,
          time: '06:00',
          html: '<b>晨巡报告</b>：12 处塘口/网箱状态正常，夜间无离群/浮头现象。今日投喂计划已按存塘量与水温自动生成（4 号塘病害复核期<b>减半投喂</b>）。'
        },
        {
          id: 'fp-1',
          sender: huang,
          time: '06:05',
          html: '收到，按计划投喂。网箱 B 上午补一次防逃网检查。'
        },
        {
          id: 'fp-2',
          sender: farmBot,
          time: '09:32',
          html: '⚡ 接总控分身<b>紧急出塘指令</b>：1 号塘出塘 1,500 斤（加急订单 <code>#SO-0612-01</code>，负责人已批准）。拉网组、装车组已通知。'
        },
        {
          id: 'fp-3',
          sender: huang,
          time: '09:36',
          html: '拉网开始，按订单规格分级，预计 15 分钟装车完毕。'
        },
        {
          id: 'fp-4',
          sender: farmBot,
          time: '09:50',
          html: '<b>出塘完成</b> ✅ 批次 <code>#YZ-0612-7</code> 共 1,500 斤已装车发往加工厂，规格合格率 99.4%，批次信息已上链。'
        },
        {
          id: 'fp-5',
          sender: farmBot,
          time: '16:06',
          html: '🌀 台风前准备：已生成<b>网箱加固巡查清单</b>（锚链 × 8、缆绳 × 24、防逃网 × 6），请今晚完成并拍照回传。'
        },
        {
          id: 'fp-6',
          sender: huang,
          time: '18:30',
          html: '加固完成 ✅ 照片已回传系统，网箱 A/B 锚链全部复紧。'
        }
      ]
    }
  ]
}

/** ========== 养殖-水质监测 ========== */
const farmWater: OpsScenario = {
  meta: {
    title: '养殖-水质监测',
    topic: '36 点位传感器 · 溶氧 / pH / 水温 / 氨氮 实时采集',
    memberCount: 6,
    stack: [
      { label: '养', bot: true },
      { label: '徐', color: '#8a6a8a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'fw-0',
          sender: farmBot,
          time: '08:00',
          html: '<b>水质日报</b>（36 点位 · 物联网自动采集）：',
          rich: {
            variant: 'info',
            tag: 'WATER DAILY',
            title: '6 月 12 日水质日报',
            meta: '达标率 98% · 1 处待关注',
            kv: [
              { k: 'DO',   v: '溶氧均值 6.8 mg/L（≥5 达标）' },
              { k: 'pH',   v: '8.1（7.8–8.6 正常）' },
              { k: 'temp', v: '水温 25.6 ℃' },
              { k: 'NH3',  v: '氨氮 0.02 mg/L（优）' }
            ],
            actions: [
              { label: '查看分点位曲线', primary: true },
              { label: '导出日报' }
            ]
          }
        },
        {
          id: 'fw-1',
          sender: farmBot,
          time: '14:10',
          html: '⚠ <code>4 号塘</code> 溶氧 2 小时内由 6.4 降至 <b>5.2 mg/L</b>（午后高温 + 减料期藻相波动），建议<b>立即开启增氧机</b>。',
          rich: {
            variant: 'warn',
            tag: 'DO ALERT',
            title: '4 号塘溶氧下行',
            meta: '传感器 W-04A/B 双点位一致 · 置信度高',
            kv: [
              { k: 'current', v: '5.2 mg/L' },
              { k: 'floor',   v: '预警线 5.0 mg/L' },
              { k: 'action',  v: '开启 2 台增氧机 · 持续监测' }
            ],
            actions: [
              { label: '远程开启增氧机', primary: true },
              { label: '查看曲线' }
            ]
          }
        },
        {
          id: 'fw-2',
          sender: xu,
          time: '14:12',
          html: '已远程开启 4 号塘 2 台增氧机，现场再去看一眼藻色。'
        },
        {
          id: 'fw-3',
          sender: farmBot,
          time: '15:00',
          html: '4 号塘溶氧回升至 <b>6.3 mg/L</b> ✅ 解除预警。增氧机将在 17:00 自动转为间歇模式。'
        }
      ]
    }
  ]
}

/** ========== 养殖-病害防治 ========== */
const farmDisease: OpsScenario = {
  meta: {
    title: '养殖-病害防治',
    topic: 'AI 图像识别 + 镜检确诊 · 防治方案自动生成',
    memberCount: 7,
    stack: [
      { label: '养', bot: true },
      { label: '质', bot: true },
      { label: '徐', color: '#8a6a8a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'fdz-0',
          sender: farmBot,
          time: '10:20',
          html: '⚠ <code>4 号塘</code> 投喂监控 AI 识别 <b>3 尾体表异常</b>（白点状附着），建议取样送检。',
          rich: {
            variant: 'warn',
            tag: 'DISEASE',
            title: '4 号塘疑似病害预警 #BH-0612-1',
            meta: 'AI 初筛 · 置信度 87%',
            kv: [
              { k: 'suspect', v: '刺激隐核虫（海水小瓜虫）' },
              { k: 'scope',   v: '3 尾/观测 200 尾 · 暂未扩散' },
              { k: 'action',  v: '取样镜检 + 减半投喂 + 独立工具' }
            ],
            actions: [
              { label: '生成送检单', primary: true },
              { label: '查看抓拍图' }
            ]
          }
        },
        {
          id: 'fdz-1',
          sender: xu,
          time: '11:00',
          html: '已取样 3 尾送质检实验室，4 号塘工具单独存放，进出消毒。'
        },
        {
          id: 'fdz-2',
          sender: qcBot,
          time: '15:40',
          html: '<b>镜检结果</b>：确认刺激隐核虫<b>轻度感染</b>（幼虫期，密度低）。',
          rich: {
            variant: 'ok',
            tag: 'LAB RESULT',
            title: '4 号塘镜检报告 #LB-0612-3',
            meta: '处置窗口期内 · 可控',
            kv: [
              { k: 'finding', v: '虫体 2–4 个/视野 · 轻度' },
              { k: 'plan',    v: '淡水浴 5 分钟 × 隔离观察 7 天' },
              { k: 'recheck', v: '6 月 15 日复检' }
            ],
            actions: [
              { label: '查看防治方案', primary: true },
              { label: '预约复检' }
            ]
          }
        },
        {
          id: 'fdz-3',
          sender: farmBot,
          time: '16:00',
          html: '防治方案已生成并同步总控分身：4 号塘<b>暂停出塘资格</b>至复检合格；周边 2、3 号塘加测水质一次/日。复检已预约 6 月 15 日。'
        }
      ]
    }
  ]
}

/** ========== 养殖-出塘报备 ========== */
const farmHarvest: OpsScenario = {
  meta: {
    title: '养殖-出塘报备',
    topic: '出塘申请 / 批次登记 / 与订单联动 · 关键操作人工批准',
    memberCount: 5,
    stack: [
      { label: '养', bot: true },
      { label: '黄', color: '#7a8a5a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'fh-0',
          sender: farmBot,
          time: '09:33',
          html: '<b>紧急出塘报备单</b>已提交并获负责人批准（审批号 <code>#AP-0612-01</code>）：',
          rich: {
            variant: 'info',
            tag: 'HARVEST',
            title: '出塘报备 #YZ-0612-7',
            meta: '1 号塘 · 关联订单 #SO-0612-01 · 已批准',
            kv: [
              { k: 'amount', v: '1,500 斤 · 成品大黄鱼' },
              { k: 'spec',   v: '500–600 g/尾 为主' },
              { k: 'truck',  v: '活水车 闽A·C8821 已调度' }
            ],
            actions: [
              { label: '查看报备单', primary: true },
              { label: '溯源登记' }
            ]
          }
        },
        {
          id: 'fh-1',
          sender: huang,
          time: '09:36',
          html: '拉网作业开始，按 500–600 g 规格分级装车。'
        },
        {
          id: 'fh-2',
          sender: farmBot,
          time: '09:50',
          html: '<b>出塘完成</b> ✅ 实出 1,500 斤，装车水温 18℃ 充氧正常，已发车。出塘节点已写入溯源链。'
        },
        {
          id: 'fh-3',
          sender: farmBot,
          time: '16:30',
          html: '<b>明日增供出塘计划</b>已报备：2、4 号塘合计 2,500 斤/日（停航期养殖补位，总控统筹方案）。备注：4 号塘病害复核中，<b>实际仅安排 2 号塘出塘</b>，缺量由网箱 A 补足，待总控确认。'
        }
      ]
    }
  ]
}

/** ========== 加工-车间排产 ========== */
const procPlan: OpsScenario = {
  meta: {
    title: '加工-车间排产',
    topic: '订单驱动自动排产 · 产线 / 人员 / 时序一键拆分',
    memberCount: 8,
    stack: [
      { label: '加', bot: true },
      { label: '钱', color: '#a07050' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'pp-0',
          sender: procBot,
          time: '09:31',
          html: '接总控分身推送：加急订单 <code>#SO-0612-01</code> 需加工 <b>4,000 斤</b>。产能核查通过（今日剩余 6,000 斤），等待货源到厂。'
        },
        {
          id: 'pp-1',
          sender: procBot,
          time: '10:05',
          html: '<b>排产方案</b>已生成（货品已质检放行）：',
          rich: {
            variant: 'info',
            tag: 'SCHEDULE',
            title: '加急单排产 #PS-0612-04',
            meta: '双线并行 · 10:05 开线',
            kv: [
              { k: 'lines',  v: '生鲜分拣线 + 包装线' },
              { k: 'staff',  v: '12 人（分拣 7 / 包装 5）' },
              { k: 'window', v: '10:05 – 11:10（65 分钟）' },
              { k: 'output', v: '目标 4,000 斤 · 损耗基线 1.8%' }
            ],
            actions: [
              { label: '确认开线', primary: true },
              { label: '调整排班' }
            ]
          }
        },
        {
          id: 'pp-2',
          sender: qian,
          time: '10:06',
          html: '确认开线 ✅ 包装间预冷已到位，按一级鲜度标准走。'
        },
        {
          id: 'pp-3',
          sender: procBot,
          time: '17:00',
          html: '<b>明日排产预案</b>：停航期渔获减少，主排 <b>预制菜线 860 斤</b> + 常规鲜品 1,800 斤（养殖货源为主）。预案已同步总控分身，明早 7:30 自动确认。'
        }
      ]
    }
  ]
}

/** ========== 加工-生产进度 ========== */
const procLine: OpsScenario = {
  meta: {
    title: '加工-生产进度',
    topic: '产线实时进度 · 自动同步销售（客户）与总控（全局）',
    memberCount: 8,
    stack: [
      { label: '加', bot: true },
      { label: '钱', color: '#a07050' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'pl-0',
          sender: procBot,
          time: '10:30',
          html: '加急单 <code>#SO-0612-01</code> 加工进度 <b>50%</b>（2,100 斤），分拣线节拍正常。'
        },
        {
          id: 'pl-1',
          sender: procBot,
          time: '10:40',
          html: '进度 <b>65%</b>，预计 11:10 完成：',
          chartCard: { chartId: 'chProd', title: '加急订单加工进度：完成量 vs 计划' }
        },
        {
          id: 'pl-2',
          sender: procBot,
          time: '11:08',
          html: '<b>加工完成</b> ✅',
          rich: {
            variant: 'ok',
            tag: 'DONE',
            title: '加急单加工完结 #PS-0612-04',
            meta: '用时 63 分钟 · 提前 2 分钟',
            kv: [
              { k: 'output', v: '成品 3,952 斤' },
              { k: 'loss',   v: '损耗率 1.2%（基线 1.8%）' },
              { k: 'next',   v: '成品信息已推送仓储物流分身' }
            ],
            actions: [
              { label: '查看批次明细', primary: true },
              { label: '损耗分析' }
            ]
          }
        },
        {
          id: 'pl-3',
          sender: qian,
          time: '11:10',
          html: '辛苦！包装组随车把溯源码贴好，移交孙库管入库。'
        }
      ]
    }
  ]
}

/** ========== 加工-质量管控 ========== */
const procQc: OpsScenario = {
  meta: {
    title: '加工-质量管控',
    topic: '入厂必检 · 产线巡检 · 留样封存 72h',
    memberCount: 7,
    stack: [
      { label: '质', bot: true },
      { label: '加', bot: true },
      { label: '钱', color: '#a07050' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'pq-0',
          sender: qcBot,
          time: '09:55',
          html: '<b>入厂抽检</b>：加急单三个批次全部合格（报告 <code>#QC-0612-15</code>），准予流入加工。详情见私信「质检分身 · 溯源与报告」。'
        },
        {
          id: 'pq-1',
          sender: qcBot,
          time: '11:00',
          html: '<b>产线巡检</b>：包装间温度 11.8℃（≤12℃ 达标）、刀具消毒记录完整、金属探测仪校验通过。本批<b>留样 6 份已封存 72 小时</b>备查。'
        },
        {
          id: 'pq-2',
          sender: procBot,
          time: '11:09',
          html: '成品出线复核：净重抽查 20 件全部达标，包装封口完好率 100%。'
        },
        {
          id: 'pq-3',
          sender: qcBot,
          time: '17:20',
          html: '<b>今日质量日报</b>：',
          rich: {
            variant: 'ok',
            tag: 'QC DAILY',
            title: '6 月 12 日车间质量日报',
            meta: '综合评分 98 / 100',
            kv: [
              { k: 'inspect', v: '入厂抽检 3 批 · 合格率 100%' },
              { k: 'patrol',  v: '产线巡检 4 次 · 无不符合项' },
              { k: 'sample',  v: '留样 6 份 · 在存 18 份' }
            ],
            actions: [
              { label: '查看日报', primary: true },
              { label: '导出台账' }
            ]
          }
        }
      ]
    }
  ]
}

/** ========== 加工-设备保养 ========== */
const procEquip: OpsScenario = {
  meta: {
    title: '加工-设备保养',
    topic: '产线设备状态监测 · 预测性保养工单',
    memberCount: 5,
    stack: [
      { label: '警', bot: true },
      { label: '加', bot: true },
      { label: '钱', color: '#a07050' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'pe-0',
          sender: alertBot,
          time: '08:30',
          html: '⚠ <b>速冻线压缩机</b>振动幅值连续 3 日缓升（2.8 → 3.4 mm/s），建议本周内保养。',
          rich: {
            variant: 'warn',
            tag: 'PREDICTIVE',
            title: '速冻线压缩机保养建议 #EQ-0610',
            meta: '预测性维护 · 非紧急',
            kv: [
              { k: 'vibration', v: '3.4 mm/s（报警线 4.5）' },
              { k: 'forecast',  v: '按趋势 10–14 天后达报警线' },
              { k: 'window',    v: '建议周五停机保养 2 小时' }
            ],
            actions: [
              { label: '生成保养工单', primary: true },
              { label: '查看振动趋势' }
            ]
          }
        },
        {
          id: 'pe-1',
          sender: qian,
          time: '09:00',
          html: '安排周五上午保养，速冻任务挪到下午。工单派设备组。'
        },
        {
          id: 'pe-2',
          sender: procBot,
          time: '09:02',
          html: '已联动排产：周五上午速冻线<b>预留停机窗口 08:00–10:00</b>，不影响在手订单交付。'
        },
        {
          id: 'pe-3',
          sender: procBot,
          time: '15:30',
          html: '包装线 3 号封口机耗材（封口膜）更换完成 ✅ 试封 50 件合格率 100%，计数器已清零。'
        }
      ]
    }
  ]
}

/** ========== 销售-订单接龙 ========== */
const saleOrders: OpsScenario = {
  meta: {
    title: '销售-订单接龙',
    topic: '线上线下订单归集 · 自动解析 → A2A 推送全链路',
    memberCount: 9,
    stack: [
      { label: '销', bot: true },
      { label: '周', color: '#8a6a8a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'so-0',
          sender: zhou,
          time: '09:28',
          html: '电商后台 + 线下渠道同步进单：<b>生鲜海鱼 4,000 斤，明早 8:00 前送达</b>，客户要求全程冷链。@销售分身'
        },
        {
          id: 'so-1',
          sender: saleBot,
          time: '09:30',
          html: '订单 <code>#SO-0612-01</code> 解析完成（加急），已通过 A2A 推送总控/加工/仓储分身，货源匹配进行中 → 跟踪见 <code>#总控-订单全链路</code>。'
        },
        {
          id: 'so-2',
          sender: saleBot,
          time: '11:21',
          html: '<code>#SO-0612-01</code> 履约进度：加工完成 ✅ → 冷链已匹配（明日 07:20 送达）→ 物流单号已推送客户。'
        },
        {
          id: 'so-3',
          sender: saleBot,
          time: '14:20',
          html: '⚠ 新进 2 笔加急订单（<code>#SO-0612-02</code> / <code>#SO-0612-03</code>）合计 5,200 斤，<b>货源不足触发协商</b> → 处理过程见 <code>#协商-货源冲突</code>。'
        },
        {
          id: 'so-4',
          sender: saleBot,
          time: '16:30',
          html: '<b>今日订单日报</b>：',
          rich: {
            variant: 'info',
            tag: 'ORDER DAILY',
            title: '6 月 12 日订单日报',
            meta: '新增 36 单 · 加急 3 单',
            kv: [
              { k: 'volume',  v: '出货 4,000 斤 + 锁定 5,200 斤' },
              { k: 'fulfill', v: '履约率 100% · 零投诉' },
              { k: 'note',    v: '明日停航 · 已切换养殖货源接单口径' }
            ],
            actions: [
              { label: '查看订单看板', primary: true },
              { label: '导出明细' }
            ]
          }
        }
      ]
    }
  ]
}

/** ========== 销售-行情分析 ========== */
const saleMarket: OpsScenario = {
  meta: {
    title: '销售-行情分析',
    topic: '批发价 / 电商价实时抓取 · AI 预测与产销策略',
    memberCount: 7,
    stack: [
      { label: '销', bot: true },
      { label: '周', color: '#8a6a8a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'sm-0',
          sender: saleBot,
          time: '08:31',
          html: '<b>行情早报</b>：大黄鱼批发价连续 5 日走低（18.2 元/斤，低于历史均值 12%），电商端价格坚挺。<b>建议本周以去库存为主</b>。',
          chartCard: { chartId: 'chTrend', title: '大黄鱼批发价 7 日：实际 vs AI 预测 vs 历史平均' }
        },
        {
          id: 'sm-1',
          sender: saleBot,
          time: '08:33',
          html: '配套策略已生成：批发渠道占比 32% → 24%，电商直发 38% → 46%，优先消化冷库临期批次（预计日增收 ¥18,600）。'
        },
        {
          id: 'sm-2',
          sender: zhou,
          time: '10:15',
          html: '@销售分身 中秋档期快到了，大黄鱼礼盒要不要提前备货？'
        },
        {
          id: 'sm-3',
          sender: saleBot,
          time: '10:16',
          html: '基于近 3 年数据：中秋前 2 周礼盒需求约 <b>+18%</b>，且批发价届时大概率回升。建议 <b>8 月底前锁定 2、3 号塘出塘排期</b>并预订礼盒包材，已将建议推送总控分身纳入备货计划。'
        },
        {
          id: 'sm-4',
          sender: saleBot,
          time: '16:05',
          html: '⚠ 停航联动：明日新鲜渔获断档，已在各渠道<b>下调「当日捕捞」标签商品库存</b>，养殖直供商品权重上调。'
        }
      ]
    }
  ]
}

/** ========== 销售-渠道对接 ========== */
const saleChannel: OpsScenario = {
  meta: {
    title: '销售-渠道对接',
    topic: '商超 / 电商 / 批发 / 餐饮直供 · 报价与补货协同',
    memberCount: 8,
    stack: [
      { label: '销', bot: true },
      { label: '周', color: '#8a6a8a' }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'sc-0',
          sender: saleBot,
          time: '10:00',
          html: '商超渠道<b>周补货单</b>已确认：永辉 3 店合计 1,200 斤（周四送达），价格按周协议价执行，排产需求已推送加工分身。'
        },
        {
          id: 'sc-1',
          sender: saleBot,
          time: '16:04',
          html: '<b>货源变动通知</b>（停航预警）已推送渠道客户：',
          rich: {
            variant: 'info',
            tag: 'NOTICE',
            title: '短期货源结构调整告知',
            meta: '推送 12 家 · 响应 9 家',
            kv: [
              { k: 'change', v: '明日起 2 日内捕捞鲜品暂停供应' },
              { k: 'offer',  v: '养殖大黄鱼/鲈鱼足量平价供应' },
              { k: 'status', v: '9 家已确认 · 3 家待回复' }
            ],
            actions: [
              { label: '查看回执明细', primary: true },
              { label: '再次提醒' }
            ]
          }
        },
        {
          id: 'sc-2',
          sender: zhou,
          time: '16:40',
          html: '剩余 3 家我电话沟通完了：2 家改订养殖品，1 家顺延到周五。回执已补录系统。'
        },
        {
          id: 'sc-3',
          sender: saleBot,
          time: '16:41',
          html: '已更新 ✅ 12/12 全部确认。渠道侧零客诉，调整后订单结构已同步总控分身。'
        }
      ]
    }
  ]
}

/** ========== 销售-售后客服 ========== */
const saleAfter: OpsScenario = {
  meta: {
    title: '销售-售后客服',
    topic: '客诉工单 · 与仓储 / 物流联动核查 · 满意度回访',
    memberCount: 6,
    stack: [
      { label: '销', bot: true },
      { label: '仓', bot: true }
    ]
  },
  days: [
    {
      daySep: today,
      messages: [
        {
          id: 'sa-0',
          sender: saleBot,
          time: '11:40',
          html: '新客诉工单：昨日批次 2 件<b>外包装破损</b>，客户上传照片已收录。',
          rich: {
            variant: 'warn',
            tag: 'TICKET',
            title: '客诉工单 #CS-0612-02',
            meta: '电商渠道 · 中优先级',
            kv: [
              { k: 'batch', v: '#WL-0611-05 · 鲜品礼盒 × 2' },
              { k: 'claim', v: '外箱挤压破损 · 内袋完好' },
              { k: 'route', v: '已联动仓储物流分身核查装运记录' }
            ],
            actions: [
              { label: '查看客户照片', primary: true },
              { label: '先行赔付' }
            ]
          }
        },
        {
          id: 'sa-1',
          sender: whBot,
          time: '13:10',
          html: '核查完成：装车交接照片完好，干线运输段有<b>急刹颠簸记录</b>（车载传感 G 值超限 1 次），判定责任在承运段。已按先行赔付流程<b>补发 2 件</b>，并向承运商发起索赔。'
        },
        {
          id: 'sa-2',
          sender: saleBot,
          time: '13:12',
          html: '已回复客户并同步补发单号，工单转「待回访」。承运商考核分已自动扣减。'
        },
        {
          id: 'sa-3',
          sender: saleBot,
          time: '15:00',
          html: '<b>回访完成</b> ✅ 客户对处理速度给出 5 星评价。今日客诉 1 起、已闭环，平均处置时长 1 小时 32 分（基线 4 小时）。'
        }
      ]
    }
  ]
}

/** ========== 导出全集（reactive：支持按钮回执等实时追加消息）========== */
export const opsScenarios: Record<string, OpsScenario> = reactive({
  /* 总控 */
  'order-flow': orderFlow,
  'risk-alert': riskAlert,
  'conflict':   conflict,
  'approvals':  approvals,
  'trace-sync': traceSync,
  /* 捕捞 */
  'fish-dispatch': fishDispatch,
  'fish-catch':    fishCatch,
  'fish-safety':   fishSafety,
  'fish-maint':    fishMaint,
  /* 养殖 */
  'farm-pond':    farmPond,
  'farm-water':   farmWater,
  'farm-disease': farmDisease,
  'farm-harvest': farmHarvest,
  /* 加工 */
  'proc-plan':  procPlan,
  'proc-line':  procLine,
  'proc-qc':    procQc,
  'proc-equip': procEquip,
  /* 销售 */
  'sale-orders':  saleOrders,
  'sale-market':  saleMarket,
  'sale-channel': saleChannel,
  'sale-after':   saleAfter
})
