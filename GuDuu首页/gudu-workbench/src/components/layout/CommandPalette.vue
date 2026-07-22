<template>
  <div v-if="visible" class="cp-overlay" @click.self="close">
    <div class="cp-modal">
      <!-- 输入 -->
      <div class="cp-input-row">
        <svg v-if="!isCmdMode" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
        </svg>
        <span v-else class="cp-cmd-ic">/</span>
        <input
          ref="inputRef"
          v-model="query"
          :placeholder="isCmdMode ? '检索过滤器：/image 图片 · /doc 文档 · /from 发送人…' : '搜索 IM 聊天记录 / 频道，或输入 / 按类型检索…'"
          @keydown.escape="close"
          @keydown.enter.prevent="pick(selIdx)"
          @keydown.down.prevent="move(1)"
          @keydown.up.prevent="move(-1)"
        />
        <span class="cp-kbd">esc</span>
      </div>

      <div class="cp-body">
        <template v-for="(it, i) in items" :key="i">
          <div v-if="it.kind === 'sec'" class="cp-sec">{{ it.label }}</div>

          <!-- 过滤器命令 -->
          <div
            v-else-if="it.kind === 'cmd'"
            class="cp-item"
            :class="{ act: selIdx === it.idx }"
            @mouseenter="selIdx = it.idx"
            @click="pick(it.idx)"
          >
            <span class="cp-item-cmd">{{ it.cmd }}</span>
            <span class="cp-item-desc">{{ it.desc }}</span>
            <span v-if="it.usage" class="cp-item-usage">{{ it.usage }}</span>
          </div>

          <!-- 频道 -->
          <div
            v-else-if="it.kind === 'channel'"
            class="cp-item"
            :class="{ act: selIdx === it.idx }"
            @mouseenter="selIdx = it.idx"
            @click="pick(it.idx)"
          >
            <span class="cp-item-ch"># {{ it.label }}</span>
            <span class="cp-item-desc">{{ it.workspace }}</span>
          </div>

          <!-- 消息 / 检索结果 -->
          <div
            v-else
            class="cp-item cp-msg"
            :class="{ act: selIdx === it.idx }"
            @mouseenter="selIdx = it.idx"
            @click="pick(it.idx)"
          >
            <div class="cp-msg-top">
              <span v-if="it.icon" class="cp-msg-ic">{{ it.icon }}</span>
              <span class="cp-item-ch">{{ it.channel }}</span>
              <span class="cp-msg-meta">{{ it.sender }} · {{ it.time }}</span>
            </div>
            <div class="cp-msg-snippet" v-html="it.snippetHtml" />
          </div>
        </template>

        <div v-if="emptyText" class="cp-empty" v-html="emptyText" />

        <div v-if="!query.trim()" class="cp-hint">
          直接输入关键词全文搜索；<kbd>/</kbd> 按类型检索（图片 / 文档 / 图表 / 单据 / 发送人）；<kbd>⌘K</kbd> 随时唤起
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { MessageData } from '@/types/message'
import { useCommandPalette } from '@/composables/useCommandPalette'
import { useActiveWorkspace } from '@/composables/useActiveWorkspace'
import { allFeeds, type FeedSource } from '@/composables/useLiveFeed'
import { workspaceDataMap } from '@/data/channels'

const { visible, close } = useCommandPalette()
const { setActive } = useActiveWorkspace()

const query = ref('')
const selIdx = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)

const isCmdMode = computed(() => query.value.startsWith('/'))

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function msgText(m: MessageData): string {
  return [m.html, m.rich?.title, m.rich?.paragraph, m.doc?.title, m.trailingHtml]
    .filter(Boolean)
    .join(' ')
    .replace(/<[^>]+>/g, '')
}

/* ===================== 检索过滤器（搜索 IM 内容的命令）===================== */

const FILTERS = [
  { cmd: '/image',   desc: '检索 IM 中的图片与监控画面' },
  { cmd: '/doc',     desc: '检索文档与报告消息（质检报告 / 周报…）' },
  { cmd: '/chart',   desc: '检索数据图表消息' },
  { cmd: '/ref',     desc: '检索单据编号（#SO- / #YZ- / #AP- …）', usage: '/ref SO' },
  { cmd: '/from',    desc: '按发送人筛选消息', usage: '/from 林经理' },
  { cmd: '/channel', desc: '查找频道', usage: '/channel 订单' }
]

/* ===================== 条目模型（统一列表，方便键盘导航）===================== */

type PItem =
  | { kind: 'sec'; label: string; idx: -1 }
  | { kind: 'cmd'; cmd: string; desc: string; usage?: string; idx: number }
  | { kind: 'channel'; label: string; workspace: string; wsId: string; hash: string; idx: number }
  | { kind: 'msg'; icon?: string; channel: string; hash: string; sender: string; time: string; snippetHtml: string; idx: number }

function channelHits(q: string): PItem[] {
  if (!q) return []
  const hits: PItem[] = []
  for (const [wsId, ws] of Object.entries(workspaceDataMap)) {
    for (const ch of ws.channels) {
      if (ch.label.includes(q)) hits.push({ kind: 'channel', label: ch.label, workspace: ws.name, wsId, hash: `#/ops/${ch.id}`, idx: 0 })
      if (hits.length >= 5) return hits
    }
  }
  return hits
}

function textSearchHits(q: string): PItem[] {
  const hits: PItem[] = []
  for (const feed of allFeeds()) {
    for (const day of feed.days) {
      for (const m of day.messages) {
        const text = msgText(m)
        const i = text.indexOf(q)
        if (i < 0) continue
        const start = Math.max(0, i - 18)
        const seg = (start > 0 ? '…' : '') + text.slice(start, i + q.length + 30) + '…'
        hits.push({
          kind: 'msg',
          channel: feed.channel,
          hash: feed.hash,
          sender: m.sender.name,
          time: m.time,
          snippetHtml: esc(seg).replace(esc(q), `<mark>${esc(q)}</mark>`),
          idx: 0
        })
        if (hits.length >= 8) return hits
      }
    }
  }
  return hits
}

/** 按类型过滤：/image /doc /chart /ref /from */
function filterHits(cmd: string, arg: string): PItem[] {
  const hits: PItem[] = []
  const seenRef = new Set<string>()
  const push = (feed: FeedSource, m: MessageData, icon: string, snippet: string) =>
    hits.push({
      kind: 'msg',
      icon,
      channel: feed.channel,
      hash: feed.hash,
      sender: m.sender.name,
      time: m.time,
      snippetHtml: esc(snippet),
      idx: 0
    })

  for (const feed of allFeeds()) {
    for (const day of feed.days) {
      for (const m of day.messages) {
        if (cmd === '/image') {
          if (m.rich?.cctv) push(feed, m, '📷', `监控画面 · ${m.rich.cctv.camera} · ${m.rich.title}`)
          else if (m.html?.includes('<svg')) push(feed, m, '🎨', `AI 生成配图 · ${msgText(m).slice(0, 40)}`)
        } else if (cmd === '/doc') {
          if (m.doc) push(feed, m, '📄', `${m.doc.title} · ${m.doc.subtitle.slice(0, 30)}…`)
        } else if (cmd === '/chart') {
          if (m.chartCard) push(feed, m, '📈', m.chartCard.title)
        } else if (cmd === '/from') {
          if (arg && m.sender.name.includes(arg)) {
            const text = msgText(m)
            if (text) push(feed, m, '💬', text.slice(0, 56) + (text.length > 56 ? '…' : ''))
          }
        } else if (cmd === '/ref') {
          const refs = msgText(m).match(/#[A-Z]{2,3}-[\w-]+/g) ?? []
          for (const r of refs) {
            if (arg && !r.toUpperCase().includes(arg.toUpperCase())) continue
            const key = r + feed.hash
            if (seenRef.has(key)) continue
            seenRef.add(key)
            push(feed, m, '🔖', `${r} · ${msgText(m).slice(0, 40)}…`)
          }
        }
        if (hits.length >= 10) return hits
      }
    }
  }
  return hits
}

/* ===================== 统一条目列表 ===================== */

const items = computed<PItem[]>(() => {
  const list: PItem[] = []
  let idx = 0
  const add = (it: PItem) => { it.idx = idx++; list.push(it) }
  const sec = (label: string) => list.push({ kind: 'sec', label, idx: -1 })

  if (isCmdMode.value) {
    const [head, ...rest] = query.value.trim().split(/\s+/)
    const arg = rest.join(' ')
    const known = FILTERS.find((f) => f.cmd === head)
    if (known && head !== '/channel') {
      const hits = filterHits(head, arg)
      if (hits.length) {
        sec(`${known.cmd} 检索结果`)
        hits.forEach((h) => add(h))
      }
      return list
    }
    if (head === '/channel') {
      const hits = channelHits(arg)
      if (hits.length) {
        sec('频道')
        hits.forEach((h) => add(h))
      }
      return list
    }
    // 命令提示（前缀过滤）
    sec('检索过滤器')
    FILTERS.filter((f) => f.cmd.startsWith(head) || head === '/').forEach((f) =>
      add({ kind: 'cmd', cmd: f.cmd, desc: f.desc, usage: f.usage, idx: 0 })
    )
    return list
  }

  const q = query.value.trim()
  if (q) {
    const chs = channelHits(q)
    if (chs.length) {
      sec('频道')
      chs.forEach((h) => add(h))
    }
    const msgs = textSearchHits(q)
    if (msgs.length) {
      sec('聊天记录')
      msgs.forEach((h) => add(h))
    }
    return list
  }

  sec('按类型检索')
  FILTERS.forEach((f) => add({ kind: 'cmd', cmd: f.cmd, desc: f.desc, usage: f.usage, idx: 0 }))
  return list
})

const selectable = computed(() => items.value.filter((i) => i.kind !== 'sec'))

const emptyText = computed(() => {
  if (selectable.value.length) return ''
  const q = query.value.trim()
  if (!q) return ''
  if (isCmdMode.value) {
    const head = q.split(/\s+/)[0]
    if (head === '/from') return '输入发送人名称，如 <code>/from 林经理</code>'
    if (head === '/channel') return '输入频道关键词，如 <code>/channel 订单</code>'
    return `没有找到匹配「${esc(q)}」的内容`
  }
  return `没有找到「${esc(q)}」相关内容 —— 试试 <code>/</code> 按类型检索`
})

function move(d: number) {
  const n = selectable.value.length
  if (!n) return
  selIdx.value = (selIdx.value + d + n) % n
}

function pick(i: number) {
  const it = selectable.value[i]
  if (!it) return
  if (it.kind === 'cmd') {
    query.value = it.cmd + ' '
    selIdx.value = 0
    inputRef.value?.focus()
    return
  }
  if (it.kind === 'channel') {
    setActive(it.wsId)
    window.location.hash = it.hash
    close()
    return
  }
  window.location.hash = it.hash
  close()
}

watch(query, () => { selIdx.value = 0 })
watch(visible, (v) => {
  if (v) {
    query.value = ''
    selIdx.value = 0
    nextTick(() => inputRef.value?.focus())
  }
})

/* ⌘K / Ctrl+K 全局唤起 */
function onGlobalKey(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    visible.value = true
  }
}
onMounted(() => document.addEventListener('keydown', onGlobalKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onGlobalKey))
</script>

<style scoped>
.cp-overlay {
  position: fixed;
  inset: 0;
  z-index: 460;
  background: rgba(20, 18, 14, 0.32);
  display: flex;
  justify-content: center;
  padding-top: 12vh;
  animation: cp-fade 0.15s ease;
}
@keyframes cp-fade { from { opacity: 0 } to { opacity: 1 } }

.cp-modal {
  width: min(640px, 92vw);
  max-height: 64vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-radius: 14px;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.28), 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  animation: cp-pop 0.18s ease;
  align-self: flex-start;
}
@keyframes cp-pop { from { opacity: 0; transform: translateY(-8px) scale(0.99) } to { opacity: 1; transform: none } }

.cp-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  color: var(--text-3);
}
.cp-cmd-ic {
  width: 16px;
  text-align: center;
  font-family: var(--mono);
  font-weight: 700;
  color: var(--accent);
}
.cp-input-row input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
  color: var(--text);
}
.cp-kbd {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 2px 6px;
}

.cp-body { overflow-y: auto; padding: 8px; }
.cp-sec {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  padding: 8px 10px 4px;
}
.cp-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: var(--fs-100);
}
.cp-item.act { background: var(--bg-soft); }
.cp-item-cmd {
  font-family: var(--mono);
  font-weight: 700;
  color: var(--accent);
  flex-shrink: 0;
  min-width: 86px;
}
.cp-item-desc { color: var(--text-2); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cp-item-usage {
  margin-left: auto;
  flex-shrink: 0;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-3);
}
.cp-item-ch { font-weight: var(--fw-bold); color: var(--text); flex-shrink: 0; }

.cp-msg { flex-direction: column; align-items: stretch; gap: 3px; }
.cp-msg-top { display: flex; align-items: baseline; gap: 8px; }
.cp-msg-ic { flex-shrink: 0; }
.cp-msg-meta { font-size: var(--fs-75); color: var(--text-3); }
.cp-msg-snippet { font-size: var(--fs-75); color: var(--text-2); line-height: 1.5; }
.cp-msg-snippet :deep(mark) {
  background: rgba(201, 100, 66, 0.18);
  color: var(--accent);
  border-radius: 3px;
  padding: 0 2px;
}

.cp-empty { padding: 22px 12px; text-align: center; color: var(--text-3); font-size: var(--fs-100); }
.cp-empty :deep(code) { font-family: var(--mono); background: var(--bg-soft); padding: 1px 6px; border-radius: 5px; }
.cp-hint {
  padding: 10px 12px 8px;
  font-size: var(--fs-75);
  color: var(--text-3);
  border-top: 1px solid var(--border-soft);
  margin-top: 6px;
}
.cp-hint kbd {
  font-family: var(--mono);
  font-size: 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 5px;
}
</style>
