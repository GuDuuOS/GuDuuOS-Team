import type { Sender } from '@/types/message'
import { allFeeds, appendLiveMessage, appendToOpsChannel, scrollFeedToBottom } from '@/composables/useLiveFeed'
import { notify } from '@/composables/useDemoHeartbeat'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'
import { currentUser } from '@/data/channels'
import { todoMap } from '@/data/todos'

/* ===== 分身花名册 ===== */
const BOTS: Record<string, Sender> = {
  duu:   { type: 'bot', name: 'GuDuu 总控分身', avatar: 'G' },
  fish:  { type: 'bot', name: '捕捞分身',       avatar: '捕' },
  farm:  { type: 'bot', name: '养殖分身',       avatar: '养' },
  proc:  { type: 'bot', name: '加工分身',       avatar: '加' },
  sale:  { type: 'bot', name: '销售分身',       avatar: '销' },
  wh:    { type: 'bot', name: '仓储物流分身',   avatar: '仓' },
  qc:    { type: 'bot', name: '质检分身',       avatar: '质' },
  alert: { type: 'bot', name: '运维预警分身',   avatar: '警' }
}

/** 按当前路由决定默认应答分身 */
function defaultBot(): Sender {
  const h = window.location.hash
  const ops = h.match(/^#\/ops\/([^/?#]+)/)?.[1] ?? ''
  if (ops.startsWith('fish')) return BOTS.fish
  if (ops.startsWith('farm')) return BOTS.farm
  if (ops === 'proc-qc') return BOTS.qc
  if (ops.startsWith('proc')) return BOTS.proc
  if (ops.startsWith('sale')) return BOTS.sale
  if (ops === 'risk-alert') return BOTS.alert
  if (ops === 'conflict') return BOTS.sale
  if (ops === 'trace-sync') return BOTS.qc
  if (h.startsWith('#/safety')) return BOTS.alert
  if (h.startsWith('#/energy')) return BOTS.sale
  if (h.startsWith('#/office')) return BOTS.qc
  return BOTS.duu
}

/** @提及 覆盖应答分身 */
function mentionBot(text: string): Sender | null {
  if (/@?(养殖)/.test(text) && text.includes('@')) return BOTS.farm
  if (/@(捕捞)/.test(text)) return BOTS.fish
  if (/@(加工)/.test(text)) return BOTS.proc
  if (/@(销售)/.test(text)) return BOTS.sale
  if (/@(仓储|物流)/.test(text)) return BOTS.wh
  if (/@(质检)/.test(text)) return BOTS.qc
  if (/@(预警|运维)/.test(text)) return BOTS.alert
  if (/@(GuDuu|总控|guduu)/i.test(text)) return BOTS.duu
  return null
}

/** 关键词 → 应答内容（首个命中生效）*/
const RULES: { re: RegExp; reply: string }[] = [
  { re: /^\/dispatch/, reply: '已发起<b>货源智能调度</b>：按「冷库 → 养殖 → 捕捞」优先级匹配中，方案生成后会推送本频道并等待人工确认。' },
  { re: /^\/trace/, reply: '已发起<b>批次溯源检索</b>：输入批次号（如 <code>#YZ-0612-7</code>）即可回溯海域 / 塘口 / 加工 / 冷链全节点。' },
  { re: /^\/report/, reply: '已开始生成<b>产销报告</b>：正在汇聚 8 个分身的当日数据，完成后推送负责人账号并归档。' },
  { re: /^\/market/, reply: '已抓取最新行情：大黄鱼批发价 <b>18.2 元/斤</b>（连续 5 日走低），完整分析见「销售-行情与产销分析」。' },
  { re: /^\/qc/, reply: '已发起<b>质检报告生成</b>：最近批次 #QC-0612-15 三批次全部合格（一级鲜度），报告可推送渠道客户。' },
  { re: /冷库|库存|库容/, reply: '冷库当前在库 <b>2,000 斤</b>（一级鲜度批次 × 3），库容占用 <b>82%</b>，已触发扩容评估。需要调度货源可以直接说数量，或输入 <code>/dispatch</code>。' },
  { re: /订单|接单|履约/, reply: '今日订单：出货 <b>4,000 斤</b> + 锁定 5,200 斤（加急 3 单），履约率 <b>100%</b>。加急单 <code>#SO-0612-01</code> 已发运就绪，明早 07:20 送达。' },
  { re: /台风|天气|海况|风浪|大风/, reply: '最新海况：当前近海风力 4 级；<b>明日 06:00–18:00 闽东渔场 8–9 级大风</b>（强对流），已建议停航，6 艘渔船全部回港避风。' },
  { re: /价格|行情|批发|售价/, reply: '大黄鱼批发价今日 <b>18.2 元/斤</b>，连续 5 日走低（低于历史均值 12%）。AI 建议：优先消化冷库库存，电商直发占比提至 46%。' },
  { re: /进度|排产|加工|车间/, reply: '加工进度：加急单 4,000 斤已完成（用时 63 分钟，损耗率 <b>1.2%</b>）；预制菜线明日排产 860 斤，物料齐套率 100%。' },
  { re: /溯源|批次|上链/, reply: '批次 <code>#YZ-0612-7</code> 全链路 6 节点已上链存证 5 个（冷链配送待发车）。溯源码已生成，扫码可向客户展示全部节点与温控记录。' },
  { re: /损耗/, reply: '本月全链路损耗率 <b>12‰</b>，低于基线 6 个千分点；主要损耗在分拣环节（0.8%），降损明细已纳入周报。' },
  { re: /病害|消毒|隔离/, reply: '4 号塘刺激隐核虫<b>轻度感染</b>，已执行淡水浴 + 隔离观察，暂停出塘资格；6 月 15 日复检，周边塘口加测水质一次/日。' },
  { re: /渔获|出海|渔船|返航/, reply: '船队动态：今日渔获 <b>3,000 斤</b>（5 船次）；因明日停航，全部渔船已回港避风，闽蓝 009 检修中（周四试车）。' },
  { re: /水质|溶氧|增氧/, reply: '水质播报：36 点位达标率 <b>98%</b>；4 号塘溶氧已回升至 6.3 mg/L（增氧机间歇模式），其余塘口正常。' },
  { re: /冷链|温度|厢温/, reply: '冷链监控：在途冷链车 3 辆，厢温全部 ≤4℃；闽A·D2371 滤网堵塞已处理，温度回落正常区间。' },
  { re: /审批|报备|终审|裁定/, reply: '当前待人工终审 <b>1 项</b>：停航报备单 <code>#AP-0612-03</code>（捕捞分身发起）。请前往 <b>#审批-异常裁定</b> 处理。' },
  { re: /客诉|售后|投诉/, reply: '今日客诉 1 起（包装破损）已闭环：判定承运段责任，补发 2 件 + 向承运商索赔，客户回访 5 星。平均处置时长 1 小时 32 分。' },
  { re: /谢谢|辛苦|好的|收到|👍/, reply: '不客气！全链路 8 个分身持续在线，有任何调度、查询需求随时叫我 🐟' }
]

function resolveReply(text: string): string {
  for (const r of RULES) if (r.re.test(text)) return r.reply
  return '收到 ✅ 已记录并同步相关分身跟进。你可以直接问我「库存 / 订单 / 海况 / 行情 / 进度 / 溯源 / 审批」等，或输入 <code>/</code> 调用命令。'
}

/** 纯文本版应答（供右侧 AI 面板等纯文本场景复用）*/
export function answerText(text: string): string {
  return resolveReply(text).replace(/<[^>]+>/g, '')
}

/* ===== 对话式指令：说了就真做（跨频道留痕 + 红点 + toast）===== */

interface ChatAction {
  re: RegExp
  run: (text: string) => { reply: string; effects: () => void }
}

/** /image：生成海报风格 SVG 配图（内联渲染在回复消息里）*/
function posterSvg(desc: string): string {
  const t = esc(desc.length > 14 ? desc.slice(0, 14) + '…' : desc)
  return (
    `<svg width="320" height="180" viewBox="0 0 320 180" xmlns="http://www.w3.org/2000/svg" style="border-radius:10px;display:block;max-width:100%">` +
    `<defs><linearGradient id="srp" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b4965"/><stop offset="0.55" stop-color="#2a6f8e"/><stop offset="1" stop-color="#5fa8c5"/></linearGradient></defs>` +
    `<rect width="320" height="180" fill="url(#srp)"/>` +
    `<path d="M0 130 Q40 118 80 130 T160 130 T240 130 T320 130 V180 H0 Z" fill="rgba(255,255,255,0.12)"/>` +
    `<path d="M0 146 Q40 134 80 146 T160 146 T240 146 T320 146 V180 H0 Z" fill="rgba(255,255,255,0.16)"/>` +
    `<text x="22" y="54" font-size="30">🐟</text>` +
    `<text x="22" y="94" fill="#fff" font-size="19" font-weight="700" font-family="-apple-system,'PingFang SC',sans-serif">${t}</text>` +
    `<text x="22" y="118" fill="rgba(255,255,255,0.85)" font-size="12" font-family="-apple-system,'PingFang SC',sans-serif">蓝湾渔业 · 源头直供 · 全程冷链</text>` +
    `<text x="22" y="166" fill="rgba(255,255,255,0.55)" font-size="10" font-family="monospace">AI GENERATED · GuDuu</text>` +
    `</svg>`
  )
}

/** /summary：频道纪要（主要频道有定制要点）*/
const SUMMARY_POINTS: Record<string, string> = {
  'order-flow': '加急订单 <code>#SO-0612-01</code> 完成全链路履约：货源匹配 → 质检放行 → 加工（损耗 1.2%）→ 冷链发运就绪，明早 07:20 送达。',
  'risk-alert': '强对流预警已闭环联动：停航 → 销售调整接单 → 养殖补供 70%，停航报备单经负责人终审。',
  'conflict': '双加急订单货源冲突已裁定：订单 A 全量交付，订单 B 拆分两日 + 运费减免，客户均已确认。'
}

function summarize(): string {
  const id = window.location.hash.match(/^#\/ops\/([^/?#]+)/)?.[1] ?? ''
  const feed = allFeeds().find((f) => f.hash === window.location.hash || f.hash === `#/ops/${id}`)
  const msgs = feed ? feed.days.flatMap((d) => d.messages) : []
  const senders = [...new Set(msgs.map((m) => m.sender.name))]
  const point = SUMMARY_POINTS[id] ?? '各分身协同正常，指令均已闭环留痕；待办事项已同步「待办事宜」。'
  return (
    `📋 <b>频道纪要</b>（/summary 自动生成）<br/>` +
    `今日共 <b>${msgs.length}</b> 条消息，参与方：${senders.slice(0, 5).join('、')}${senders.length > 5 ? ' 等' : ''}。<br/>` +
    `关键进展：${point}`
  )
}

let todoSeq = 0

const CHAT_ACTIONS: ChatAction[] = [
  /* /image 描述：AI 生成配图，直接出现在回复里 */
  {
    re: /^\/image/,
    run: (text) => {
      const desc = text.replace(/^\/image\s*/, '').trim() || '大黄鱼礼盒宣传海报'
      return {
        reply:
          `🎨 <b>AI 配图已生成</b>（${esc(desc)}）：<div style="margin-top:8px">${posterSvg(desc)}</div>` +
          `<span style="font-size:11px;color:var(--text-3)">由 GuDuu 文生图引擎生成 · 可发送给渠道客户或用于活动页</span>`,
        effects: () => notify('🎨', 'AI 配图已生成', `「${desc}」已发到本频道`)
      }
    }
  },
  /* /summary：自动总结当前频道 */
  {
    re: /^\/summary/,
    run: () => ({
      reply: summarize(),
      effects: () => notify('📋', '频道纪要已生成', '由 GuDuu 自动汇总今日要点')
    })
  },
  /* /todo 内容：真实创建待办 */
  {
    re: /^\/todo/,
    run: (text) => {
      const title = text.replace(/^\/todo\s*/, '').trim() || '跟进今日演示反馈'
      return {
        reply: `📝 待办已创建：「<b>${esc(title)}</b>」已加入「待办事宜 · 今日截止」，负责人 ${currentUser.name}。`,
        effects: () => {
          const { activeId } = useActiveWorkspace()
          const todos = todoMap[activeId.value] ?? todoMap.hq
          todos.groups[0]?.items.unshift({
            id: `chat-todo-${++todoSeq}`,
            title,
            status: 'pending',
            priority: 'mid',
            assignee: currentUser.name,
            due: '今日'
          })
          notify('📝', '待办已创建', `「${title}」已加入今日截止清单`)
        }
      }
    }
  },
  /* 货源调度：「帮我调配 3000 斤」/「/dispatch 2000」 */
  {
    re: /(调配|调货|补货|调度).*斤|^\/dispatch/,
    run: (text) => {
      const qty = text.match(/(\d[\d,，]*)\s*斤?/)?.[1]?.replace(/[，,]/g, ',') ?? '3,000'
      return {
        reply: `已发起 <b>${qty} 斤</b>货源智能调度 ✅ 正按「冷库 → 养殖 → 捕捞」优先级征询各分身，匹配方案生成后会推送 <code>#总控-订单全链路</code> 并等待人工终审。`,
        effects: () => {
          appendToOpsChannel('order-flow', BOTS.duu, `⚡ <b>调度指令</b>（来自对话）：${currentUser.name} 发起 <b>${qty} 斤</b>货源匹配，已向养殖 / 捕捞 / 仓储分身征询，方案生成后在本频道推送终审。`)
          notify('🐟', '货源调度已发起', `${qty} 斤 · #总控-订单全链路 已留痕`)
        }
      }
    }
  },
  /* 停航指令：「明天停航」「暂停出海」 */
  {
    re: /(停航|暂停.*出海|不要出海)/,
    run: () => ({
      reply: '收到 ✅ 已通知捕捞分身生成<b>停航报备单</b>；停航属关键操作，报备单将提交负责人人工终审（动态见 <code>#审批-异常裁定</code>）。',
      effects: () => {
        appendToOpsChannel('fish-dispatch', BOTS.fish, '⚓ <b>停航指令</b>（来自对话）：收到停航要求，正在生成停航报备单并提交负责人终审；在港渔船保持避风状态。')
        appendToOpsChannel('approvals', BOTS.fish, '📨 <b>待审批</b>：捕捞分身提交停航报备单（对话指令触发），请负责人终审。')
        notify('⚓', '停航报备生成中', '#捕捞-渔船调度 与 #审批-异常裁定 已留痕')
      }
    })
  },
  /* 推送溯源码：「把溯源码发给客户」 */
  {
    re: /(溯源码|溯源).*(发|推送|给客户)|(发|推送).*(溯源)/,
    run: () => ({
      reply: '溯源码已生成并推送渠道客户 ✅ 扫码可见 6 个节点与冷链温控记录（留痕见 <code>#数据-溯源同步</code>）。',
      effects: () => {
        appendToOpsChannel('trace-sync', BOTS.qc, '🔗 <b>溯源码推送</b>（来自对话）：批次 <code>#YZ-0612-7</code> 溯源码已推送渠道客户，扫码可查全节点与温控记录。')
        notify('🔗', '溯源码已推送客户', '#数据-溯源同步 已留痕')
      }
    })
  },
  /* 生成/推送日报：「把日报发给我」 */
  {
    re: /(日报|周报|复盘报告).*(发|推送|生成)|(生成|发|推送).*(日报|周报)/,
    run: () => ({
      reply: '今日<b>产销日报</b>已生成并推送负责人账号 ✅ 出货 4,000 斤 · 损耗率 1.2% · 履约率 100%；明早 7:30 自动生成次日计划简报。',
      effects: () => {
        notify('📊', '产销日报已推送', '已发送至林经理账号并归档')
      }
    })
  }
]

function resolveChatAction(text: string): { reply: string; effects: () => void } | null {
  for (const a of CHAT_ACTIONS) if (a.re.test(text)) return a.run(text)
  return null
}

/** 用户输入做 HTML 转义，防止破版 */
function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/**
 * 频道输入框统一发送入口：
 * 用户消息上屏 → 应答分身显示"正在输入…" → 0.9s 后替换为按关键词生成的智能应答。
 * 返回是否处理（当前页面不是消息频道时返回 false）。
 */
export function smartSend(rawText: string): boolean {
  const text = rawText.trim()
  if (!text) return false
  const mine = appendLiveMessage(
    { type: 'human', name: currentUser.name, avatar: currentUser.avatar, color: currentUser.color },
    esc(text)
  )
  if (!mine) return false

  const bot = mentionBot(text) ?? defaultBot()
  const action = resolveChatAction(text)
  const typing = appendLiveMessage(
    bot,
    '<span style="color:var(--text-3);font-style:italic">正在输入…</span>'
  )
  if (typing) {
    setTimeout(() => {
      typing.html = action ? action.reply : resolveReply(text)
      scrollFeedToBottom()
      // 对话式指令：应答落地的同时执行真实动作（跨频道留痕 + 红点 + toast）
      action?.effects()
    }, 900)
  }
  return true
}
