import { reactive } from 'vue'
import { workspaceDataMap, workspaces } from '@/data/channels'
import { getTodos } from '@/data/todos'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'
import { appendToOpsChannel } from '@/composables/useLiveFeed'
import { answerText } from '@/composables/useSmartReply'
import type { ChannelItem } from '@/types/channel'

/* ===== 对话消息与结果卡片 ===== */
export interface TaskStatusRow {
  name: string
  pending: number
  inProgress: number
  done: number
  overdue: number
}
/** 建群提案里的候选成员 */
export interface Candidate {
  name: string
  role: string
  reason: string
  selected: boolean
}
/** 执行卡片的明细行 / 步骤 / 跳转 / 主操作 */
export interface ExecRow { k: string; v: string }
export interface ExecStep { text: string; done: boolean }
export interface ExecLink { label: string; channelId?: string; hash?: string }
export interface ExecAction { label: string; done: boolean; doneText: string }
/** 主操作点击后的后续：向频道投递留痕消息 + AI 回复 */
export interface ExecFollowUp { feedChannel?: string; feedHtml?: string; reply: string }

export type AiCard =
  | { kind: 'proposal'; label: string; candidates: Candidate[]; done: boolean }
  | { kind: 'channel'; channelId: string; label: string; workspace: string; members: string[] }
  | { kind: 'tasks'; rows: TaskStatusRow[] }
  | {
      kind: 'exec'
      icon: string
      title: string
      sub?: string
      rows?: ExecRow[]
      steps?: ExecStep[]
      action?: ExecAction
      link?: ExecLink
      followUp?: ExecFollowUp
    }

export interface ThinkStep { label: string; done: boolean }

export interface AiMessage {
  id: number
  role: 'user' | 'ai'
  text?: string
  card?: AiCard
  /** 思考态：展示分步进度，完成后填充 text / card */
  thinking?: boolean
  steps?: ThinkStep[]
}

const messages = reactive<AiMessage[]>([])
let seq = 0
let channelSeq = 0

const { activeId } = useActiveWorkspace()

/** 每步思考间隔（ms）*/
const STEP_MS = 550

/* ===== 候选人花名册（带关键词与推荐理由）===== */
interface Roster { name: string; role: string; reason: string; always?: boolean; keys?: RegExp }
const ROSTER: Roster[] = [
  { name: 'GuDuu',        role: '总控',       reason: '总控协调（默认加入）', always: true },
  { name: '林经理',       role: '负责人',     reason: '终审/重大事项决策',   keys: /(订单|审批|决策|预算|裁定|调价|备货)/ },
  { name: '赵船长',       role: '捕捞队长',   reason: '渔船与出海作业把关',  keys: /(捕捞|渔船|出海|渔获|海况|码头)/ },
  { name: '钱厂长',       role: '加工厂长',   reason: '车间排产与产能',      keys: /(加工|排产|车间|产能|分拣|预制)/ },
  { name: '孙库管',       role: '仓储主管',   reason: '冷库与冷链调度',      keys: /(冷库|库存|冷链|配送|物流|仓储)/ },
  { name: '养殖分身',     role: '养殖 bot',   reason: '塘口/水质/出塘',      keys: /(养殖|出塘|水质|病害|苗种|塘口|网箱)/ },
  { name: '捕捞分身',     role: '捕捞 bot',   reason: '渔船调度/渔获上报',   keys: /(捕捞|渔船|出海|渔获|海域)/ },
  { name: '加工分身',     role: '加工 bot',   reason: '排产/产能管控',       keys: /(加工|排产|产能|分拣|包装)/ },
  { name: '销售分身',     role: '销售 bot',   reason: '订单/行情/渠道',      keys: /(订单|行情|客户|渠道|报价|销售)/ },
  { name: '仓储物流分身', role: '仓储 bot',   reason: '冷库/冷链/配送',      keys: /(冷库|冷链|物流|配送|入库|发货)/ },
  { name: '质检分身',     role: '质检 bot',   reason: '抽检/溯源/报告',      keys: /(质检|抽检|溯源|农残|鲜度|报告)/ },
  { name: '运维预警分身', role: '预警 bot',   reason: '天气/海况/设备预警',  keys: /(预警|台风|海况|风险|设备|温度|异常)/ }
]

/* ===== 意图解析 ===== */
function extractGroupName(text: string): string {
  const quoted = text.match(/[「"'《]([^」"'》\n]{1,20})[」"'》]/)
  if (quoted) return quoted[1].trim()
  const m = text.match(/([一-龥A-Za-z0-9·\-]{2,16})(群|组|频道|专班)/)
  if (m) {
    const stem = m[1].replace(/^(请|帮我|帮忙|麻烦)?\s*(新建|创建|建立|建|开|拉|搞|起)?\s*一?\s*个?\s*/, '')
    return (stem || m[1]) + m[2]
  }
  return '临时协作群'
}

/** 按任务匹配候选人，命中者预选；至少预选 2 人 */
function proposeMembers(text: string): Candidate[] {
  const list: Candidate[] = ROSTER.map((r) => ({
    name: r.name,
    role: r.role,
    reason: r.reason,
    selected: !!r.always || (r.keys ? r.keys.test(text) : false)
  }))
  if (list.filter((c) => c.selected).length <= 1) {
    for (const n of ['林经理', '赵船长']) {
      const c = list.find((x) => x.name === n)
      if (c) c.selected = true
    }
  }
  return list
}

const isCreateIntent = (t: string) =>
  /(群|组|频道|专班)/.test(t) && /(建|创建|新建|建立|组建|开|拉|搞|起)/.test(t)
const isDispatchIntent = (t: string) => /(调配|调货|货源|备货|补货|调度)/.test(t)
const isRiskIntent = (t: string) => /(停航|台风|强对流|大风|应急|海况|风险)/.test(t)
const isTraceIntent = (t: string) => /(溯源|批次|#YZ|#BL|#LK)/.test(t)
const isReportIntent = (t: string) => /(日报|周报|报告|复盘|产销)/.test(t)
const isTaskIntent = (t: string) => /(任务|进度|待办|逾期|汇总|状态)/.test(t)

function push(role: AiMessage['role'], text?: string, card?: AiCard) {
  messages.push({ id: ++seq, role, text, card })
}

/**
 * 推一条"思考中"的 AI 消息，按 STEP_MS 逐步完成各步骤，
 * 全部完成后调用 produce(m) 把结果填进同一条消息。
 */
function respond(steps: string[], produce: (m: AiMessage) => void) {
  const m: AiMessage = reactive({
    id: ++seq,
    role: 'ai',
    thinking: true,
    steps: steps.map((s) => ({ label: s, done: false }))
  })
  messages.push(m)
  let i = 0
  const tick = () => {
    if (!m.steps) return
    if (i < m.steps.length) {
      m.steps[i].done = true
      i++
      setTimeout(tick, STEP_MS)
    } else {
      m.thinking = false
      m.steps = undefined
      produce(m)
    }
  }
  setTimeout(tick, STEP_MS)
}

function buildTaskRows(): TaskStatusRow[] {
  return workspaces.map((w) => {
    const s = getTodos(w.id).summary
    return { name: w.title, pending: s.pending, inProgress: s.inProgress, done: s.done, overdue: s.overdue }
  })
}

export function useAiAgent() {
  return {
    messages,
    reset() { messages.splice(0, messages.length) },

    runCommand(raw: string) {
      const text = raw.trim()
      if (!text) return
      push('user', text)

      if (isCreateIntent(text)) {
        const label = extractGroupName(text)
        respond(['理解需求', '匹配相关人员', '生成建群提案'], (m) => {
          m.text = `要建「${label}」。我按任务匹配，建议拉入下面这些人（已勾选推荐人选）。你确认或调整后我再建群：`
          m.card = { kind: 'proposal', label, candidates: proposeMembers(text), done: false }
        })
      } else if (isDispatchIntent(text)) {
        respond(['解析需求（品类 / 数量 / 时效）', '核查冷库可用库存', 'A2A 征询养殖 / 捕捞分身', '生成货源匹配方案'], (m) => {
          m.text = '多方协商完成：3,000 斤货源按「冷库优先 → 养殖补量」匹配如下。确认后我会锁定货源并通知各分身执行：'
          m.card = {
            kind: 'exec',
            icon: '🐟',
            title: '货源匹配方案 · 3,000 斤',
            sub: '冷库优先 → 养殖补量 · 满足次日发货时效',
            rows: [
              { k: '冷库库存', v: '1,800 斤（批次 #LK-0610-3 · 一级鲜度）' },
              { k: '养殖出塘', v: '1,200 斤（2 号塘 · 30 分钟可到厂）' },
              { k: '加工排期', v: '今日 18:00 前完成分拣包装入库' }
            ],
            action: { label: '锁定货源并通知各分身', done: false, doneText: '已锁定' },
            link: { label: '前往 #总控-订单全链路 查看回执', channelId: 'order-flow' },
            followUp: {
              feedChannel: 'order-flow',
              feedHtml: '⚡ <b>小蓝 AI 调度指令</b>：已锁定 3,000 斤货源（冷库 1,800 + 2 号塘出塘 1,200）。请<b>加工分身</b>安排今日 18:00 前排产、<b>仓储物流分身</b>预留次日冷链运力。',
              reply: '已锁定货源 ✅ 并通过 A2A 通知养殖、加工、仓储物流分身；调度留痕已发到 #总控-订单全链路（频道红点 +1）。'
            }
          }
        })
      } else if (isRiskIntent(text)) {
        respond(['核验气象 / 海况数据', '通知捕捞分身调整出海计划', '联动销售 / 养殖分身', '生成停航报备单'], (m) => {
          m.text = '风险应急联动已启动，关键动作如下。停航属关键操作，分身无终审权，报备单需林经理人工终审：'
          m.card = {
            kind: 'exec',
            icon: '🌀',
            title: '强对流应急联动',
            sub: '明日 06:00–18:00 · 闽东渔场 8–9 级大风 · 浪高 3.5 m',
            steps: [
              { text: '捕捞分身：已暂停明日全部出海计划，6 艘渔船回港避风', done: true },
              { text: '销售分身：已调整接单策略并通知 12 家渠道客户', done: true },
              { text: '养殖分身：评估增供 2,500 斤/日，平衡供需缺口', done: true },
              { text: '停航报备单 #AP-0612-03 待林经理人工终审', done: false }
            ],
            action: { label: '推送报备单给林经理终审', done: false, doneText: '已推送' },
            link: { label: '前往 #预警-风险联动 查看', channelId: 'risk-alert' },
            followUp: {
              feedChannel: 'risk-alert',
              feedHtml: '🌀 <b>小蓝 AI 应急联动</b>：停航报备单 <code>#AP-0612-03</code> 已推送负责人终审；海况每 6 小时自动播报，风险解除后将提醒恢复出海评估。',
              reply: '报备单已推送林经理 ✅ 终审动态会同步在 #审批-异常裁定；联动留痕已发到 #预警-风险联动。'
            }
          }
        })
      } else if (isTraceIntent(text)) {
        respond(['检索溯源链', '校验 6 个节点完整性', '生成溯源档案'], (m) => {
          m.text = '批次 #YZ-0612-7 全链路节点完整，已上链存证 5 个、待执行 1 个：'
          m.card = {
            kind: 'exec',
            icon: '🔗',
            title: '批次溯源 · #YZ-0612-7',
            sub: '1 号塘 · 1,500 斤 · 关联订单 #SO-0612-01',
            rows: [
              { k: '出塘', v: '09:36 · 黄塘长 · ✓ 已存证' },
              { k: '冷藏转运', v: '09:38–09:53 · 闽A·C8821 · ✓ 已存证' },
              { k: '入厂质检', v: '09:55 · #QC-0612-15 合格 · ✓ 已存证' },
              { k: '分拣包装', v: '10:05–11:08 · 加工分身 · ✓ 已存证' },
              { k: '冷链配送', v: '明日 05:30 发车 · ⏳ 待执行' }
            ],
            action: { label: '生成溯源码并推送客户', done: false, doneText: '已推送' },
            link: { label: '前往 #数据-溯源同步 查看', channelId: 'trace-sync' },
            followUp: {
              feedChannel: 'trace-sync',
              feedHtml: '🔗 <b>小蓝 AI</b>：批次 <code>#YZ-0612-7</code> 溯源码已生成并推送渠道客户，扫码可见全部节点与冷链温控记录。',
              reply: '溯源码已生成并推送客户 ✅ 留痕已发到 #数据-溯源同步。'
            }
          }
        })
      } else if (isReportIntent(text)) {
        respond(['汇聚 8 个分身今日数据', '比对基线与昨日', '生成产销日报'], (m) => {
          m.text = '今日产销日报已生成，全链路健康度 96 分：'
          m.card = {
            kind: 'exec',
            icon: '📊',
            title: '产销日报 · 6 月 12 日',
            sub: '数据截至 17:30 · 各环节分身自动上报',
            rows: [
              { k: '订单', v: '出货 4,000 斤 + 锁定 5,200 斤（加急 3 单）' },
              { k: '货源', v: '渔获 3,000 斤 / 出塘 1,500 斤 / 冷库库容 82%' },
              { k: '加工', v: '完成 3,952 斤 · 损耗率 1.2%（基线 1.8%）' },
              { k: '履约', v: '准时率 100% · 客诉 1 起已闭环' },
              { k: '风险', v: '明日停航 · 养殖供货占比提至 70%' }
            ],
            action: { label: '推送负责人并归档', done: false, doneText: '已推送' },
            link: { label: '在全链路驾驶舱查看', hash: '#/case' },
            followUp: {
              reply: '日报已推送林经理并归档 ✅ 明早 7:30 将自动生成次日计划简报。'
            }
          }
        })
      } else if (isTaskIntent(text)) {
        respond(['连接各部门群', '汇总任务数据', '生成报表'], (m) => {
          const rows = buildTaskRows()
          const overdue = rows.reduce((a, r) => a + r.overdue, 0)
          const pending = rows.reduce((a, r) => a + r.pending, 0)
          m.text = `已汇总 ${rows.length} 个业务群的任务状态：合计待办 ${pending} 项、逾期 ${overdue} 项。`
          m.card = { kind: 'tasks', rows }
        })
      } else {
        respond(['检索全链路数据'], (m) => {
          m.text = answerText(text)
        })
      }
    },

    /** 用户确认提案 → 思考片刻后真正建群并拉入所选成员 */
    confirmProposal(card: Extract<AiCard, { kind: 'proposal' }>) {
      if (card.done) return
      const chosen = card.candidates.filter((c) => c.selected)
      if (chosen.length === 0) {
        push('ai', '至少选择 1 位成员再建群吧～')
        return
      }
      card.done = true
      respond(['核对所选成员', '创建频道', '拉入成员并通知'], (m) => {
        const id = `ai-grp-${++channelSeq}`
        const wsId = activeId.value
        const ws = workspaceDataMap[wsId] ?? workspaceDataMap['hq']
        const ch: ChannelItem = {
          id,
          label: card.label,
          routeName: 'ops',
          routeParams: { id },
          visibility: 'public',
          emphasized: true
        }
        ws.channels.push(ch)
        m.text = `已在「${ws.name}」建群 #${card.label}，并拉入 ${chosen.length} 人。`
        m.card = { kind: 'channel', channelId: id, label: card.label, workspace: ws.name, members: chosen.map((c) => c.name) }
      })
    },

    /** 取消提案 */
    cancelProposal(card: Extract<AiCard, { kind: 'proposal' }>) {
      if (card.done) return
      card.done = true
      push('ai', '好的，已取消本次建群。')
    },

    /** 执行卡片主操作：置已完成 → 向目标频道留痕（红点+1）→ AI 回复结果 */
    confirmExec(card: Extract<AiCard, { kind: 'exec' }>) {
      if (!card.action || card.action.done) return
      card.action.done = true
      const fu = card.followUp
      if (fu?.feedChannel && fu.feedHtml) {
        appendToOpsChannel(fu.feedChannel, { type: 'bot', name: 'GuDuu 总控分身', avatar: 'G' }, fu.feedHtml)
      }
      respond(['执行操作', '通知相关分身', '写入操作留痕'], (m) => {
        m.text = fu?.reply ?? '已执行 ✅'
      })
    }
  }
}
