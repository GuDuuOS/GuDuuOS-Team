import { nextTick } from 'vue'
import type { DayMessages, MessageData, Sender } from '@/types/message'
import { opsScenarios } from '@/data/messages/ops'
import { safetyMessages } from '@/data/messages/safety'
import { energyMessages } from '@/data/messages/energy'
import { officeMessages } from '@/data/messages/office'
import { duuMessages } from '@/data/messages/duu'
import { workspaceDataMap } from '@/data/channels'

let seq = 0

/** 全部消息源（搜索 / 纪要 / 过滤器共用）*/
export interface FeedSource { channel: string; hash: string; days: DayMessages[] }

export function allFeeds(): FeedSource[] {
  const feeds: FeedSource[] = Object.entries(opsScenarios).map(([id, sc]) => ({
    channel: sc.meta.title,
    hash: `#/ops/${id}`,
    days: sc.days
  }))
  feeds.push(
    { channel: '预警-风险监测中心', hash: '#/safety', days: safetyMessages },
    { channel: '销售-行情与产销分析', hash: '#/energy', days: energyMessages },
    { channel: '质检-溯源与报告', hash: '#/office', days: officeMessages },
    { channel: 'GuDuu 总控', hash: '#/duu', days: duuMessages }
  )
  return feeds
}

/** 依据当前 hash 路由找到正在展示的消息流（找不到则返回 null）*/
function currentDays(): DayMessages[] | null {
  const hash = window.location.hash
  const ops = hash.match(/^#\/ops\/([^/?#]+)/)
  if (ops) return opsScenarios[ops[1]]?.days ?? null
  if (hash.startsWith('#/safety')) return safetyMessages
  if (hash.startsWith('#/energy')) return energyMessages
  if (hash.startsWith('#/office')) return officeMessages
  if (hash.startsWith('#/duu')) return duuMessages
  return null
}

/** 渲染后把消息流滚到底部，让新消息可见 */
export function scrollFeedToBottom() {
  nextTick(() => {
    const el = document.querySelector('.stream') as HTMLElement | null
    if (!el) return
    const scroller = el.scrollHeight > el.clientHeight ? el : el.parentElement
    if (scroller) scroller.scrollTop = scroller.scrollHeight
  })
}

/**
 * 向当前频道追加一条"刚刚"发生的消息（按钮执行回执、用户输入等）。
 * 返回创建的消息对象（可继续改写，如"正在输入…"占位）；不在消息频道时返回 null。
 */
export function appendLiveMessage(sender: Sender, html: string): MessageData | null {
  const days = currentDays()
  if (!days || !days.length) return null
  const list = days[days.length - 1].messages
  list.push({
    id: `live-${++seq}`,
    sender,
    time: '刚刚',
    html
  })
  scrollFeedToBottom()
  // 必须返回 reactive 代理（而非 push 前的原始对象），后续改写 html 才能触发更新
  return list[list.length - 1]
}

/**
 * 向指定 ops 频道投递一条消息（主 AI 执行动作的留痕）。
 * 当前没在看该频道时，给侧边栏对应频道的未读红点 +1。
 */
export function appendToOpsChannel(channelId: string, sender: Sender, html: string): boolean {
  const days = opsScenarios[channelId]?.days
  if (!days || !days.length) return false
  days[days.length - 1].messages.push({
    id: `live-${++seq}`,
    sender,
    time: '刚刚',
    html
  })
  if (window.location.hash.startsWith(`#/ops/${channelId}`)) {
    scrollFeedToBottom()
  } else {
    for (const ws of Object.values(workspaceDataMap)) {
      const ch = ws.channels.find((c) => c.id === channelId)
      if (ch) {
        ch.unread = (ch.unread ?? 0) + 1
        break
      }
    }
  }
  return true
}
