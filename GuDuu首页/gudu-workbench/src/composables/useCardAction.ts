import { ref } from 'vue'
import type { ChartConfiguration } from 'chart.js'
import type { KV, RichVariant, Sender } from '@/types/message'
import { appendLiveMessage, appendToOpsChannel } from '@/composables/useLiveFeed'
import { notify } from '@/composables/useDemoHeartbeat'

/** 卡片按钮点击后弹出的内容类型 */
export type CardActionKind = 'trend' | 'doc' | 'confirm'

export interface CardActionDocSection {
  title: string
  body?: string
  table?: { headers: string[]; rows: string[][] }
}

export interface CardActionStep {
  text: string
  /** 是否已完成（打勾），未完成显示为进行中 */
  done?: boolean
}

export interface CardActionPayload {
  kind: CardActionKind
  /** 顶部小标签 */
  tag: string
  title: string
  subtitle?: string
  variant?: RichVariant
  /** trend：复用 charts.ts 中的图表工厂 id */
  chartId?: string
  /** trend：直接传入的图表配置工厂（优先于 chartId，用于仪表盘动态数据）*/
  chartConfig?: (ctx: CanvasRenderingContext2D) => ChartConfiguration
  chartNote?: string
  /** doc：文档分节 */
  sections?: CardActionDocSection[]
  footer?: string
  /** confirm：结果标题 + 执行步骤 */
  resultTitle?: string
  steps?: CardActionStep[]
}

/** 触发按钮所在卡片的上下文，用于生成贴合卡片的弹层内容 */
export interface CardActionCtx {
  tag: string
  title: string
  meta?: string
  variant: RichVariant
  kv?: KV[]
  /** 卡片所属消息的发送方（执行类操作的聊天回执以它的身份发出）*/
  sender?: Sender
  /** 卡片数据的响应式引用：终审类操作会写入 handled 终态，按钮收起防重复 */
  raw?: { handled?: string }
}

const visible = ref(false)
const payload = ref<CardActionPayload | null>(null)

function open(p: CardActionPayload) {
  payload.value = p
  visible.value = true
}
function close() {
  visible.value = false
}

const has = (label: string, ...keys: string[]) => keys.some((k) => label.includes(k))

const FOOTER = '// 演示视图 · 数据来自 GuDuu OS 关联系统（渔船 AIS / 水质物联网 / MES / 冷链温控 / 溯源链）'

/** 把卡片 KV 整理成详情表 */
function kvTable(ctx: CardActionCtx): CardActionDocSection | null {
  if (!ctx.kv || !ctx.kv.length) return null
  return {
    title: '卡片详情',
    table: {
      headers: ['项', '值'],
      rows: ctx.kv.map((kv) => [kv.k, kv.v])
    }
  }
}

/* ===================== 跳转类 ===================== */

/** label → hash 路由（命中则跳转，不弹窗）*/
const JUMP_RULES: { keys: string[]; hash: string }[] = [
  { keys: ['查看订单看板', '查看可视化报表', '查看趋势图表'], hash: '#/case' },
  { keys: ['上报总控'], hash: '#/ops/approvals' },
  { keys: ['溯源详情', '查看链上记录'], hash: '#/ops/trace-sync' }
]

function jumpHash(label: string): string | null {
  const rule = JUMP_RULES.find((r) => r.keys.some((k) => label === k || label.includes(k)))
  return rule ? rule.hash : null
}

/* ===================== 趋势曲线类 ===================== */

/** 趋势/曲线：按指标关键词路由到对应图表 */
function buildTrend(label: string, ctx: CardActionCtx): CardActionPayload {
  const text = label + ctx.title + ctx.tag
  let chartId = 'chTrend'
  let chartNote = '实际值与 AI 预测、历史平均对比，数据每日自动更新。'

  if (has(text, '厢温', '冷链', '温度', 'COLD')) {
    chartId = 'chP201'
    chartNote = '近 9 分钟厢温持续爬升并越过 4.0℃ 上限，已通知司机靠服务区检查制冷机组。'
  } else if (has(text, '油压')) {
    chartId = 'chOil'
    chartNote = '近 6 日油压持续走低，模型推断机油滤芯堵塞概率 78%，已停航检修。'
  } else if (has(text, '振动', '压缩机', '保养')) {
    chartId = 'chVib'
    chartNote = '振动幅值连续缓升，按趋势 10–14 天后达报警线，建议本周五停机保养。'
  } else if (has(text, '溶氧', '水质', '分点位', '增氧', 'DO')) {
    chartId = 'chDO'
    chartNote = '14:12 远程开启增氧机后溶氧明显回升，15:00 已回到安全区间并解除预警。'
  } else if (has(text, '行情', '价格', '批发')) {
    chartId = 'chTrend'
    chartNote = '批发价连续走低且低于历史平均，AI 建议本周以去库存为主。'
  }

  return {
    kind: 'trend',
    tag: '趋势分析',
    title: ctx.title + ' · 实时趋势',
    subtitle: ctx.meta,
    variant: ctx.variant,
    chartId,
    chartNote
  }
}

/* ===================== 文档 / 详情类 ===================== */

/** 文档/详情：质检报告、溯源、批次、海况、影像等渔业场景 */
function buildDoc(label: string, ctx: CardActionCtx): CardActionPayload {
  const text = label + ctx.title + ctx.tag
  const base: CardActionPayload = {
    kind: 'doc',
    tag: '详情',
    title: ctx.title,
    subtitle: ctx.meta,
    variant: ctx.variant,
    sections: [],
    footer: FOOTER
  }
  const sections: CardActionDocSection[] = []
  const kvt = kvTable(ctx)

  if (has(text, '质检报告', '检测')) {
    base.tag = '质检报告'
    base.title = '质检报告 #QC-0612-15'
    sections.push({
      title: '检测项目与结果',
      table: {
        headers: ['项目', '标准限值', '实测', '判定'],
        rows: [
          ['农药残留', '不得检出', '未检出', '合格'],
          ['兽药残留', '不得检出', '未检出', '合格'],
          ['重金属（铅/镉/汞）', '≤ 0.5 mg/kg', '0.02–0.08', '合格'],
          ['鲜度 K 值', '≤ 20%（一级）', '12%', '一级鲜度'],
          ['菌落总数', 'GB 2733 限值', '符合', '合格']
        ]
      }
    })
    sections.push({ title: '结论', body: '三个批次抽检<b>全部合格</b>，准予流入加工环节；留样 6 份封存 72 小时备查。报告已同步仓储、销售、总控分身并上链存证。' })
  } else if (has(text, '溯源', '链上', '溯源码')) {
    base.tag = '全链路溯源'
    sections.push({
      title: '溯源节点（已上链）',
      table: {
        headers: ['节点', '时间', '责任方', '状态'],
        rows: [
          ['塘口出塘 #YZ-0612-7', '09:36', '黄塘长 / 养殖分身', '✓ 已存证'],
          ['渔获返港 #BL-0612-2', '09:18', '赵船长 / 捕捞分身', '✓ 已存证'],
          ['冷藏转运', '09:38–09:53', '冷藏车 闽A·C8821', '✓ 已存证'],
          ['入厂质检', '09:55', '质检分身', '✓ 已存证'],
          ['分拣包装', '10:05–11:08', '加工分身', '✓ 已存证'],
          ['冷链配送', '明日 05:30 起', '仓储物流分身', '待发车']
        ]
      }
    })
    sections.push({ title: '链上凭证', body: '区块高度 <b>#2,841,206</b> · 哈希 <code>0x8f3a…c41d</code>。渠道客户扫码即可查看全部节点与温控记录。' })
  } else if (has(text, '订单')) {
    base.tag = '订单详情'
    sections.push({
      title: '订单要素',
      table: {
        headers: ['项', '值'],
        rows: [
          ['订单号', '#SO-0612-01 · 加急'],
          ['品类 / 数量', '生鲜海鱼（大黄鱼为主）· 4,000 斤'],
          ['交付时效', '明日 08:00 前送达'],
          ['收货地址', '福州 · 仓山区客户冷库'],
          ['渠道来源', '线上电商 + 线下渠道同步']
        ]
      }
    })
    sections.push({
      title: '履约节点',
      table: {
        headers: ['节点', '时间', '状态'],
        rows: [
          ['货源锁定（4,500 斤）', '09:33', '✓ 完成'],
          ['质检放行', '09:55', '✓ 完成'],
          ['加工完成（3,952 斤）', '11:08', '✓ 完成'],
          ['冷链发车', '明日 05:30', '待执行'],
          ['送达客户', '明日 07:20（预计）', '待执行']
        ]
      }
    })
  } else if (has(text, '批次')) {
    base.tag = '批次明细'
    sections.push({
      title: '批次构成',
      table: {
        headers: ['来源', '批次号', '数量', '状态'],
        rows: [
          ['冷库库存', '#LK-0610-3', '2,000 斤', '已出库'],
          ['养殖出塘（1 号塘）', '#YZ-0612-7', '1,500 斤', '已到厂'],
          ['捕捞渔获（闽蓝 012）', '#BL-0612-2', '500 斤', '已到厂']
        ]
      }
    })
    if (kvt) sections.push(kvt)
  } else if (has(text, '海况', '云图')) {
    base.tag = '海况详情'
    sections.push({
      title: '海况要素（气象台 16:00 发布）',
      table: {
        headers: ['要素', '当前', '明日预报'],
        rows: [
          ['风力', '4 级', '8–9 级，阵风 10 级'],
          ['浪高', '1.2 m', '3.5 m'],
          ['能见度', '良好', '中-差（雷雨）'],
          ['影响海域', '—', '闽东渔场 / 近海网箱区']
        ]
      }
    })
    sections.push({ title: 'AI 建议', body: '明日 06:00–18:00 <b>暂停出海作业</b>；网箱锚链今晚完成加固；冷链运输不受影响。' })
  } else if (has(text, '航迹')) {
    base.tag = '渔船航迹'
    sections.push({
      title: '今日航迹（AIS 采样）',
      table: {
        headers: ['时间', '船位', '航速', '状态'],
        rows: [
          ['05:42', '出港 · 三都澳锚地', '8.2 kn', '出航'],
          ['06:55', '闽东渔场 E-12', '4.1 kn', '作业'],
          ['08:30', '闽东渔场 E-12', '0.8 kn', '收网'],
          ['09:18', '回港靠泊', '—', '卸货']
        ]
      }
    })
  } else if (has(text, '录像', '抓拍', '照片', '画面')) {
    base.tag = '影像记录'
    sections.push({
      title: '影像信息',
      table: {
        headers: ['项', '值'],
        rows: [
          ['来源', has(text, '客户') ? '客户上传 · 收货现场' : 'CAM-03 · 码头卸货区'],
          ['时间', has(text, '客户') ? '2026-06-12 11:32' : '2026-06-12 07:42:11'],
          ['AI 识别', has(text, '客户') ? '外箱挤压破损 × 2（内袋完好）' : '未穿戴救生衣 · 置信度 96%'],
          ['留存', '已归档至安全/客诉台账，保留 90 天']
        ]
      }
    })
    sections.push({ title: '说明', body: '完整视频与原图已在系统留存，可在监控墙插件中回放调阅（演示环境仅展示识别结论）。' })
  } else if (has(text, '防治方案')) {
    base.tag = '防治方案'
    sections.push({
      title: '处置步骤（刺激隐核虫 · 轻度）',
      table: {
        headers: ['步骤', '内容', '周期'],
        rows: [
          ['1', '淡水浴 5 分钟，清除体表虫体', '今日执行'],
          ['2', '移入隔离网箱观察，独立工具作业', '7 天'],
          ['3', '4 号塘换水 20% + 增氧，降低密度', '2 天内'],
          ['4', '镜检复查，合格后恢复出塘资格', '6 月 15 日']
        ]
      }
    })
    sections.push({ title: '联动措施', body: '4 号塘暂停出塘资格；2、3 号塘加测水质一次/日；处置进展自动同步总控分身。' })
  } else if (has(text, '预案')) {
    base.tag = '处置预案'
    sections.push({
      title: '分级响应（渔业）',
      table: {
        headers: ['等级', '触发条件', '响应动作'],
        rows: [
          ['III 级', '单点异常（设备/水质波动）', '岗位分身处置 + 设观察期'],
          ['II 级', '影响扩面（冷链越限/病害扩散）', '5 分钟内上报总控 + 暂停流转'],
          ['I 级', '重大风险（台风/食安事件）', '停航停产 + 负责人决策 + 应急联动']
        ]
      }
    })
    sections.push({ title: '处置要点', body: '先控风险后恢复生产；全程操作留痕并上链，用于事后复盘与监管追溯。' })
  } else if (has(text, '回执')) {
    base.tag = '渠道回执'
    sections.push({
      title: '通知回执明细（12 家）',
      table: {
        headers: ['渠道', '客户数', '状态'],
        rows: [
          ['商超', '4 家', '✓ 全部确认'],
          ['餐饮直供', '3 家', '✓ 全部确认'],
          ['批发', '3 家', '✓ 2 家确认 · 1 家改订养殖品'],
          ['电商大客户', '2 家', '✓ 1 家确认 · 1 家顺延周五']
        ]
      }
    })
  } else if (has(text, '备件', '库存')) {
    base.tag = '备件库存'
    sections.push({
      title: '相关备件在库',
      table: {
        headers: ['备件', '在库', '安全库存', '状态'],
        rows: [
          ['机油滤芯（主机）', '6 个', '4 个', '充足'],
          ['增氧机叶轮', '3 套', '2 套', '充足'],
          ['温感探头 T 系列', '5 支', '4 支', '充足'],
          ['压缩机皮带', '2 条', '3 条', '⚠ 低于安全线 · 已触发补货']
        ]
      }
    })
  } else if (has(text, '台账', '日报')) {
    base.tag = '台账记录'
    sections.push({
      title: '近期记录',
      table: {
        headers: ['日期', '事项', '结果'],
        rows: [
          ['2026-06-12', ctx.title, '见本卡片 · 处理中/已闭环'],
          ['2026-06-11', '冷链车厢温抽检 3 车次', '全部达标'],
          ['2026-06-10', '码头作业安全巡检', '无违规'],
          ['2026-06-08', '上月安全/质量台账归档', '已归档']
        ]
      }
    })
    if (kvt) sections.push(kvt)
  } else if (has(text, '报备单')) {
    base.tag = '报备单'
    sections.push({
      title: '单据要素',
      table: {
        headers: ['项', '值'],
        rows: [
          ['单号', '#YZ-0612-7 · 紧急出塘'],
          ['关联审批', '#AP-0612-01（林经理已批准）'],
          ['塘口 / 数量', '1 号塘 · 1,500 斤 · 500–600 g/尾'],
          ['运输', '活水车 闽A·C8821 · 水温 18℃ 充氧'],
          ['溯源', '出塘节点已上链存证']
        ]
      }
    })
  } else if (has(text, '依据')) {
    base.tag = '分析依据'
    sections.push({
      title: '数据来源与口径',
      table: {
        headers: ['数据源', '样本', '更新'],
        rows: [
          ['批发市场价格接口', '近 90 日 · 6 大市场', '每日 2 次'],
          ['自有渠道成交价', '近 30 日 · 全渠道', '实时'],
          ['冷库批次鲜度档案', '在库 11 批次', '实时'],
          ['历史同期产销数据', '近 3 年', '每周']
        ]
      }
    })
    sections.push({ title: '模型结论', body: '渠道配比调整后预计日增收 <b>¥ 18,600</b>，置信度 92%；建议执行后 3 日复核一次效果。' })
  } else {
    if (kvt) sections.push(kvt)
    sections.push({
      title: '关联记录',
      body: '该卡片的完整明细、操作留痕与关联文件均已在系统中归档，可在此查阅。'
    })
  }

  base.sections = sections
  return base
}

/* ===================== 导出 / 下载 / 打印类 ===================== */

function buildExport(label: string, ctx: CardActionCtx): CardActionPayload {
  if (has(label, '标签')) {
    return {
      kind: 'confirm',
      tag: '标签已打印',
      title: label,
      subtitle: ctx.title,
      variant: 'ok',
      resultTitle: '批次标签已发送打印',
      steps: [
        { text: '已生成含溯源码的批次标签', done: true },
        { text: '码头打印机出纸中（2 联）', done: true },
        { text: '贴签后扫码即关联溯源链', done: false }
      ]
    }
  }
  const verb = has(label, '下载') ? '下载' : has(label, '打印') ? '打印' : '导出'
  const ext = has(label, 'pdf', '.pdf') ? 'pdf' : has(label, 'Excel', 'xlsx', '明细', '台账') ? 'xlsx' : 'pdf'
  const file = `${ctx.title}.${ext}`
  return {
    kind: 'confirm',
    tag: '文件已生成',
    title: label,
    subtitle: ctx.title,
    variant: 'ok',
    resultTitle: `已${verb} · ${file}`,
    steps: [
      { text: '已汇总卡片关联数据', done: true },
      { text: `已生成 ${ext.toUpperCase()} 并加盖电子签章`, done: true },
      { text: `文件已${verb}至本地 / 推送至接收方`, done: true }
    ]
  }
}

/* ===================== 执行 / 确认类 ===================== */

function buildConfirm(label: string, ctx: CardActionCtx): CardActionPayload {
  let resultTitle = '操作已执行'
  let steps: CardActionStep[] = [
    { text: '已记录操作并写入日志', done: true },
    { text: '已通知相关分身与人员', done: true }
  ]

  if (has(label, '批准', '裁定', '签批', '通过')) {
    resultTitle = has(label, '停航') ? '停航报备已批准' : '人工终审已通过'
    steps = [
      { text: '电子签名已记录（林经理）', done: true },
      { text: '已写入审批流并上链留痕', done: true },
      { text: '已通过 A2A 通知相关分身执行', done: true }
    ]
  } else if (has(label, '驳回')) {
    resultTitle = '已驳回'
    steps = [
      { text: '驳回意见已记录', done: true },
      { text: '已退回发起分身重新拟定方案', done: true },
      { text: '等待新方案提交', done: false }
    ]
  } else if (has(label, '调整', '改派', '排班')) {
    resultTitle = '已进入人工调整模式'
    steps = [
      { text: '当前自动方案已暂停锁定', done: true },
      { text: '调整面板已开启（可改数量/优先级/班组）', done: true },
      { text: '提交后将重新走人工终审', done: false }
    ]
  } else if (has(label, '应用建议')) {
    resultTitle = '产销策略已应用'
    steps = [
      { text: '渠道配比已按建议更新', done: true },
      { text: '已推送电商/批发渠道执行', done: true },
      { text: '3 日后自动复核执行效果', done: false }
    ]
  } else if (has(label, '忽略')) {
    resultTitle = '已忽略本条建议'
    steps = [
      { text: '建议已标记忽略并记录原因待补', done: true },
      { text: '同类建议 7 日内不再推送', done: true }
    ]
  } else if (has(label, '增氧机', '远程开启')) {
    resultTitle = '设备指令已下发'
    steps = [
      { text: '增氧机启动指令已下发（物联网通道）', done: true },
      { text: '设备回执：2 台均已运转', done: true },
      { text: '持续监测溶氧，回升后自动转间歇模式', done: false }
    ]
  } else if (has(label, '生成')) {
    const thing = label.replace(/^生成/, '') || '单据'
    resultTitle = `${thing}已生成`
    steps = [
      { text: `已按模板生成${thing}并编号`, done: true },
      { text: '已推送相关分身与责任人', done: true },
      { text: '待接收方确认', done: false }
    ]
  } else if (has(label, '预约复检')) {
    resultTitle = '复检已预约 · 6 月 15 日'
    steps = [
      { text: '已加入质检实验室排期', done: true },
      { text: '已设置提前 1 天提醒徐技术员取样', done: true }
    ]
  } else if (has(label, '提醒')) {
    resultTitle = '提醒已发送'
    steps = [
      { text: '已向 3 家待回复客户再次推送通知', done: true },
      { text: '2 小时未回复将转人工电话跟进', done: false }
    ]
  } else if (has(label, '抄送')) {
    resultTitle = '已追加抄送'
    steps = [
      { text: '已抄送总控分身与林经理', done: true },
      { text: '抄送记录已写入工单', done: true }
    ]
  } else if (has(label, '归档')) {
    resultTitle = '已归档'
    steps = [
      { text: '事件已标记闭环', done: true },
      { text: '已写入安全台账并上链留痕', done: true }
    ]
  } else if (has(label, '转给', '转交')) {
    const target = label.replace(/^转给/, '').trim() || '值班'
    resultTitle = `已转给${target}`
    steps = [
      { text: `工单已移交${target}并确认接收`, done: true },
      { text: '处理时限自动顺延 30 分钟', done: true },
      { text: '处理中', done: false }
    ]
  } else if (has(label, '赔付')) {
    resultTitle = '先行赔付已发起'
    steps = [
      { text: '已按客诉先行赔付流程补发 2 件', done: true },
      { text: '已向承运商发起索赔并扣减考核分', done: true },
      { text: '待客户确认收货后闭环', done: false }
    ]
  } else if (has(label, '备货')) {
    resultTitle = '备货指令已下达'
    steps = [
      { text: '已向养殖/捕捞/加工分身下发备货需求', done: true },
      { text: '各分身产能与塘口存量核查中', done: false },
      { text: '汇总方案将在 10 分钟内回报', done: false }
    ]
  } else if (has(label, '调价')) {
    resultTitle = '调价建议已生成'
    steps = [
      { text: '已结合行情走势生成 3 档调价方案', done: true },
      { text: '已推送销售分身与负责人审阅', done: true },
      { text: '人工确认后生效', done: false }
    ]
  } else if (has(label, '确认')) {
    resultTitle = '已确认'
    steps = [
      { text: '确认记录已写入系统', done: true },
      { text: '已通知相关分身按计划执行', done: true }
    ]
  } else if (has(label, '锁定', '执行')) {
    resultTitle = '已按方案执行'
    steps = [
      { text: '货源已锁定并冻结重复占用', done: true },
      { text: '已通过 A2A 下发各环节分身', done: true },
      { text: '执行进度将实时回报本频道', done: false }
    ]
  } else if (has(label, '溯源登记')) {
    resultTitle = '溯源登记完成'
    steps = [
      { text: '批次节点信息已写入溯源链', done: true },
      { text: '溯源码已生成可供扫码查验', done: true }
    ]
  } else if (has(label, '同步')) {
    const target = has(label, '客户') ? '客户端' : '关联系统'
    resultTitle = `已同步至${target}`
    steps = [
      { text: `数据已推送${target}`, done: true },
      { text: '已校验回读一致', done: true }
    ]
  } else if (has(label, '推送')) {
    const target = label.replace('推送', '').replace(/^给/, '').trim() || '相关人员'
    resultTitle = `已推送给 ${target}`
    steps = [
      { text: '已生成通知卡片', done: true },
      { text: `已 @${target} 并发送提醒`, done: true },
      { text: '等待对方确认回执', done: false }
    ]
  } else if (has(label, '画布')) {
    resultTitle = '已在画布中打开'
    steps = [
      { text: '文档已载入协作画布', done: true },
      { text: '已开启多人协同编辑（变更自动留痕）', done: true }
    ]
  }

  return {
    kind: 'confirm',
    tag: '已执行',
    title: label,
    subtitle: ctx.title,
    variant: 'ok',
    resultTitle,
    steps
  }
}

/** 把按钮文案 + 卡片上下文解析成弹层内容 */
export function resolveAction(label: string, ctx: CardActionCtx): CardActionPayload {
  if (has(label, '趋势', '曲线') || label === '跟踪冷链温度') return buildTrend(label, ctx)
  if (has(label, '导出', '下载', '打印')) return buildExport(label, ctx)
  if (
    has(label, '查看', '查处置', '展开') ||
    has(label, '详情', '明细', '台账', '依据', '预案', '回执', '报备单', '库存', '档案', '方案', '报告')
  )
    return buildDoc(label, ctx)
  return buildConfirm(label, ctx)
}

/* ===================== 跨频道联动：批准/驳回等操作的真实流转 ===================== */

const DUU_SENDER: Sender = { type: 'bot', name: 'GuDuu 总控分身', avatar: 'G' }
const FARM_SENDER: Sender = { type: 'bot', name: '养殖分身', avatar: '养' }
const PROC_SENDER: Sender = { type: 'bot', name: '加工分身', avatar: '加' }
const SALE_SENDER: Sender = { type: 'bot', name: '销售分身', avatar: '销' }
const ALERT_SENDER: Sender = { type: 'bot', name: '运维预警分身', avatar: '警' }

/** 分身 → 它的"主场"频道（审批结果/执行指令的留痕去向）*/
const BOT_HOME: Record<string, string> = {
  养殖分身: 'farm-harvest',
  捕捞分身: 'fish-dispatch',
  加工分身: 'proc-plan',
  销售分身: 'sale-orders',
  仓储物流分身: 'order-flow',
  质检分身: 'proc-qc',
  运维预警分身: 'risk-alert'
}

interface LinkPost { channelId: string; html: string; sender?: Sender }
interface LinkToast { icon: string; title: string; body: string }
/** 延时回报：动作发生 N 秒后，相关频道出现"执行回报"，形成因果闭环 */
interface LinkDelayed { delayMs: number; channelId: string; html: string; sender?: Sender; toast?: LinkToast }
interface LinkResult { posts: LinkPost[]; toast?: LinkToast; delayed?: LinkDelayed[] }

/**
 * 按钮 → 跨频道流转规则：
 * 批准/驳回/裁定/执行指令 会真实通知发起方频道（消息留痕 + 未读红点）并弹通知说明"通知到了谁"。
 */
function resolveLinkage(label: string, ctx: CardActionCtx): LinkResult | null {
  const t = ctx.title + ' ' + (ctx.meta ?? '')
  const approve = has(label, '批准', '裁定', '通过', '执行') && !has(label, '驳回')
  const reject = has(label, '驳回')

  /* —— 紧急出塘审批（#AP-0612-01）—— */
  if (t.includes('紧急出塘')) {
    if (approve)
      return {
        posts: [
          { channelId: 'farm-harvest', html: '✅ <b>审批通过</b>：<code>#AP-0612-01</code> 紧急出塘 1,500 斤已获<b>林经理</b>批准。请养殖分身立即执行出塘，活水车可即时调度。' }
        ],
        toast: { icon: '✅', title: '审批通过 · 已通知养殖分身', body: '出塘指令已下发，#养殖-出塘报备 已留痕' },
        delayed: [
          {
            delayMs: 50_000,
            channelId: 'farm-harvest',
            sender: FARM_SENDER,
            html: '🚚 <b>执行回报</b>：<code>#AP-0612-01</code> 出塘完成，实出 <b>1,500 斤</b>已装车发往加工厂（用时 14 分钟，规格合格率 99.4%）。',
            toast: { icon: '🚚', title: '养殖分身 · 执行回报', body: '出塘完成 1,500 斤已发车（批准后自动回报）' }
          }
        ]
      }
    if (reject)
      return {
        posts: [
          { channelId: 'farm-harvest', html: '❌ <b>审批驳回</b>：<code>#AP-0612-01</code> 紧急出塘申请被退回。请养殖分身补充出塘规格与水质数据后重新提交。' }
        ],
        toast: { icon: '↩️', title: '已驳回 · 已通知养殖分身', body: '申请退回重新拟定，#养殖-出塘报备 已留痕' }
      }
  }

  /* —— 停航报备审批（#AP-0612-03）—— */
  if (t.includes('停航')) {
    if (approve)
      return {
        posts: [
          { channelId: 'fish-dispatch', html: '✅ <b>停航报备已批准</b>：<code>#AP-0612-03</code> 明日 06:00–18:00 全员停航生效，6 艘渔船保持在港避风，恢复出海前需重新审批。' },
          { channelId: 'risk-alert', html: '✅ 林经理已批准停航报备 <code>#AP-0612-03</code>，应急联动方案全部生效，海况每 6 小时自动播报。' }
        ],
        toast: { icon: '⚓', title: '停航批准 · 已通知捕捞分身', body: '#捕捞-渔船调度 与 #预警-风险联动 已留痕' },
        delayed: [
          {
            delayMs: 80_000,
            channelId: 'risk-alert',
            sender: ALERT_SENDER,
            html: '🌤 <b>海况更新</b>：最新数值预报显示明日 18:00 后风力将回落至 5 级。已设置恢复出海评估提醒，窗口期到达时自动通知捕捞分身与负责人。',
            toast: { icon: '🌤', title: '运维预警分身 · 海况更新', body: '明日 18:00 后风力回落，已设恢复出海提醒' }
          }
        ]
      }
    if (reject)
      return {
        posts: [
          { channelId: 'fish-dispatch', html: '❌ <b>停航报备被驳回</b>：请捕捞分身补充海况评估数据后重新提交报备。' }
        ],
        toast: { icon: '↩️', title: '已驳回 · 已通知捕捞分身', body: '需补充海况评估重新报备' }
      }
  }

  /* —— 货源冲突裁定 / 分配方案（#AP-0612-02 · conflict 频道）—— */
  if (t.includes('冲突') || t.includes('分配方案')) {
    if (has(label, '改派'))
      return {
        posts: [
          { channelId: 'conflict', html: '🔁 林经理选择<b>人工改派</b>：原分配方案已解锁，请销售分身与总控分身待命接收新分配指令。' }
        ],
        toast: { icon: '🔁', title: '进入人工改派', body: '原方案已解锁，#协商-货源冲突 已留痕' }
      }
    if (approve)
      return {
        posts: [
          { channelId: 'sale-orders', html: '✅ <b>裁定生效</b>：订单 A 今日全量 3,000 斤；订单 B 拆分为今日 1,200 + 明日 1,000 斤。请销售分身回复两位客户并锁定货源。' },
          { channelId: 'conflict', html: '✅ 林经理已裁定：按协商方案执行，运费减免记入订单 B 账单。' }
        ],
        toast: { icon: '⚖️', title: '裁定生效 · 已通知销售分身', body: '#销售-订单接龙 与 #协商-货源冲突 已留痕' },
        delayed: [
          {
            delayMs: 55_000,
            channelId: 'conflict',
            sender: SALE_SENDER,
            html: '✅ <b>客户回执</b>：两位客户均已确认新交付方案；订单 B 客户对运费减免表示认可，合作关系无影响。',
            toast: { icon: '🤝', title: '销售分身 · 客户回执', body: '两位客户均已确认裁定方案' }
          }
        ]
      }
  }

  /* —— 货源匹配方案（订单全链路 SOURCING PLAN）—— */
  if (t.includes('货源匹配')) {
    if (approve)
      return {
        posts: [
          { channelId: 'farm-harvest', html: '⚡ <b>执行指令</b>：货源方案已获林经理批准，1 号塘紧急出塘 1,500 斤，15 分钟内发车。' },
          { channelId: 'fish-dispatch', html: '⚡ <b>执行指令</b>：货源方案已获批，渔获 <code>#BL-0612-2</code> 500 斤锁定加急订单，优先过磅转运。' },
          { channelId: 'approvals', html: '📝 <b>审批留痕</b>：<code>#SO-0612-01</code> 货源分配方案由林经理批准执行（冷库 2000 / 养殖 1500 / 捕捞 500）。' }
        ],
        toast: { icon: '⚡', title: '已批准 · 通知 3 个频道执行', body: '养殖 / 捕捞 / 审批裁定 均已留痕' },
        delayed: [
          {
            delayMs: 65_000,
            channelId: 'order-flow',
            sender: PROC_SENDER,
            html: '✅ <b>进度回报</b>：批准后货源已陆续到厂（养殖 1,500 斤 / 捕捞 500 斤），分拣线已开线，预计 1 小时完成加工。',
            toast: { icon: '🏭', title: '加工分身 · 进度回报', body: '货源到厂，分拣线已开线' }
          }
        ]
      }
    if (reject)
      return {
        posts: [
          { channelId: 'approvals', html: '📝 <b>审批留痕</b>：<code>#SO-0612-01</code> 货源分配方案被驳回，总控分身正在重新发起货源协商。' }
        ],
        toast: { icon: '↩️', title: '已驳回', body: '总控分身将重新协商货源，#审批-异常裁定 已留痕' }
      }
    if (has(label, '调整'))
      return {
        posts: [
          { channelId: 'approvals', html: '📝 <b>审批留痕</b>：<code>#SO-0612-01</code> 货源分配进入人工调整，原锁定暂挂。' }
        ],
        toast: { icon: '🔧', title: '进入人工调整', body: '原方案暂挂，#审批-异常裁定 已留痕' }
      }
  }

  /* —— 订单复盘的后续指令 —— */
  if (t.includes('订单复盘')) {
    if (has(label, '备货'))
      return {
        posts: [
          { channelId: 'proc-plan', html: '📦 <b>备货指令</b>：负责人基于 <code>#SO-0612-01</code> 复盘下达备货——明日预留产能 4,000 斤，优先承接生鲜加急单。' },
          { channelId: 'farm-harvest', html: '📦 <b>备货指令</b>：请评估明日增供出塘 2,000 斤的可行性，今晚 20:00 前回报。' }
        ],
        toast: { icon: '📦', title: '备货指令已下达', body: '#加工-车间排产 与 #养殖-出塘报备 已留痕' },
        delayed: [
          {
            delayMs: 50_000,
            channelId: 'proc-plan',
            sender: PROC_SENDER,
            html: '✅ <b>排产预案已生成</b>：明日产线预留 分拣线 3,000 斤 + 预制线 1,000 斤，物料齐套核查中，开线前自动确认。',
            toast: { icon: '🏭', title: '加工分身 · 排产预案', body: '备货指令已落为明日排产预案' }
          }
        ]
      }
    if (has(label, '调价'))
      return {
        posts: [
          { channelId: 'sale-market', html: '💰 <b>调价指令</b>：负责人要求基于今日复盘生成 3 档调价方案（批发让利 / 电商保价 / 礼盒预售），明早 9:00 前提交。' }
        ],
        toast: { icon: '💰', title: '调价指令已下达', body: '#销售-行情分析 已留痕' }
      }
  }

  /* —— 通用兜底：审批类卡片按 meta 中的「发起：X分身」路由 —— */
  const m = (ctx.meta ?? '').match(/发起：\s*([一-龥A-Za-z]{2,8}分身)/)
  if (m && (approve || reject)) {
    const bot = m[1]
    const home = BOT_HOME[bot]
    if (home)
      return {
        posts: [
          {
            channelId: home,
            html: approve
              ? `✅ <b>审批通过</b>：「${ctx.title}」已获林经理批准，请${bot}按方案执行。`
              : `❌ <b>审批驳回</b>：「${ctx.title}」被退回，请${bot}修订后重新提交。`
          }
        ],
        toast: {
          icon: approve ? '✅' : '↩️',
          title: `${approve ? '审批通过' : '已驳回'} · 已通知${bot}`,
          body: '结果已同步至该分身主场频道'
        }
      }
  }

  return null
}

/**
 * 按钮统一入口：
 * 1. 命中跳转规则 → 路由跳转（「上报总控」会先向 #审批-异常裁定 投递上报消息再跳转）；
 * 2. 其余 → 弹窗展示；执行类操作额外：当前频道留回执 + 跨频道联动（通知发起方频道、红点、toast）。
 */
export function runAction(label: string, ctx: CardActionCtx) {
  const hash = jumpHash(label)
  if (hash) {
    if (has(label, '上报总控')) {
      appendToOpsChannel(
        'approvals',
        ctx.sender ?? { type: 'bot', name: '运维预警分身', avatar: '警' },
        `📨 <b>上报总控</b>：「${ctx.title}」${ctx.meta ? `（${ctx.meta}）` : ''}，请负责人关注并决策。`
      )
    }
    window.location.hash = hash
    return
  }
  const p = resolveAction(label, ctx)
  open(p)
  if (p.kind === 'confirm' && p.tag === '已执行') {
    const sender: Sender = ctx.sender ?? DUU_SENDER
    const doneSteps = (p.steps ?? []).filter((s) => s.done).map((s) => s.text)
    const pending = (p.steps ?? []).find((s) => !s.done)?.text
    const html =
      `✅ <b>${p.resultTitle}</b>（${label} · ${ctx.title}）` +
      (doneSteps.length ? `<br/>${doneSteps.join('；')}。` : '') +
      (pending ? `<br/>⏳ ${pending}` : '')
    appendLiveMessage(sender, html)

    const link = resolveLinkage(label, ctx)
    if (link) {
      link.posts.forEach((e) => appendToOpsChannel(e.channelId, e.sender ?? DUU_SENDER, e.html))
      if (link.toast) notify(link.toast.icon, link.toast.title, link.toast.body)
      /* 延时执行回报：动作发生约 1 分钟后，相关分身回报执行结果（因果闭环）*/
      link.delayed?.forEach((d) => {
        setTimeout(() => {
          appendToOpsChannel(d.channelId, d.sender ?? DUU_SENDER, d.html)
          if (d.toast) notify(d.toast.icon, d.toast.title, d.toast.body)
        }, d.delayMs)
      })
    }

    /* 终审类操作写入卡片终态：按钮收起为"已处理"，防止重复批准/驳回 */
    if (ctx.raw && /(批准|驳回|裁定|通过|改派|锁定|执行)/.test(label)) {
      ctx.raw.handled = label
    }
  }
}

export function useCardAction() {
  return { visible, payload, open, close, resolveAction, runAction }
}
