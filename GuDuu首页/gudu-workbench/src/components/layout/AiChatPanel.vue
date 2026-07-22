<template>
  <aside
    class="ai-panel"
    :class="{ expanded, floating }"
    :style="floating ? `left:${floatPos.x}px;top:${floatPos.y}px` : undefined"
  >
    <!-- Header（浮窗模式下作为拖拽 handle）-->
    <div class="ai-head" :class="{ draggable: floating }" @mousedown="onHeadMouseDown">
      <span class="ai-title">系统 AI</span>
      <div class="ai-head-actions">
        <button class="ai-ic-btn" title="系统 AI 设置" @click="openSettings">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        </button>
        <button v-if="!floating" class="ai-ic-btn" :title="expanded ? '收起' : '展开'" @click="toggleExpanded">
          <!-- 展开态：箭头朝内 -->
          <svg v-if="expanded" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="4 14 10 14 10 20" />
            <polyline points="20 10 14 10 14 4" />
            <line x1="14" y1="10" x2="21" y2="3" />
            <line x1="3" y1="21" x2="10" y2="14" />
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 3 21 3 21 9" />
            <polyline points="9 21 3 21 3 15" />
            <line x1="21" y1="3" x2="14" y2="10" />
            <line x1="3" y1="21" x2="10" y2="14" />
          </svg>
        </button>
        <button class="ai-ic-btn" :title="floating ? '收回侧栏' : '弹出浮窗'" @click="onToggleFloating">
          <!-- floating 态：四角合并 -->
          <svg v-if="floating" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7V3h4M21 7V3h-4M3 17v4h4M21 17v4h-4" />
          </svg>
          <!-- 默认态：windowed grid -->
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect width="18" height="18" x="3" y="3" rx="2" />
            <path d="M12 3v18M3 12h18" />
          </svg>
        </button>
        <button class="ai-ic-btn" title="关闭" @click="hide">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 主体：默认单列；floating 时三栏 -->
    <div class="ai-main">

    <!-- 左栏：最近对话（仅 floating）-->
    <div v-if="floating" class="ai-side ai-side-left">
      <button class="ai-new-chat-btn" @click="reset">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h14M12 5v14" />
        </svg>
        新对话
      </button>
      <div class="ai-side-sec">
        <div class="ai-side-title">最近对话</div>
        <ul class="ai-side-list">
          <li class="act">加急订单 货源调度</li>
          <li>强对流停航联动复盘</li>
          <li>批次 #YZ-0612-7 溯源</li>
          <li>产销日报 0611</li>
          <li>4 号塘病害处置跟进</li>
          <li>跨环节资源联动</li>
        </ul>
      </div>
    </div>

    <!-- 中间主对话 -->
    <div class="ai-center">
    <div ref="bodyRef" class="ai-body">
      <div class="ai-intro">
        <img class="ai-avatar" src="/gudu-logo.svg" alt="小蓝AI" />
        <div class="ai-meta">
          <div class="ai-name">小蓝 AI</div>
          <div class="ai-handle">@xiaolan_ai</div>
        </div>
        <button class="ai-clear-btn" @click="reset">清空本频道记录</button>
      </div>

      <p class="ai-desc">
        由 Guduu Main AI 插件提供服务，在右侧栏与你对话。
      </p>
      <p class="ai-desc dim">
        对话记录由服务端保存（按频道）；切换频道可查看各频道独立记录。
      </p>

      <div class="ai-divider" />

      <p v-if="agentMessages.length === 0" class="ai-tip">
        我是能操控系统的主 AI——在对话里就能<b>建群拉人、汇总任务、调度货源、停航应急联动、批次溯源、生成产销日报</b>，
        执行结果会留痕到对应频道。试试下面的快捷动作，或直接输入需求。
      </p>

      <!-- 对话流 -->
      <div v-else class="ai-convo">
        <div v-for="m in agentMessages" :key="m.id" class="ai-msg" :class="m.role">
          <!-- 思考进度 -->
          <div v-if="m.thinking" class="ai-thinking">
            <div
              v-for="(s, si) in stepsOf(m)"
              :key="si"
              class="ai-think-step"
              :class="{ done: s.done, active: !s.done && si === firstPendingIdx(m) }"
            >
              <span class="ai-think-ic">
                <svg v-if="s.done" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <span v-else class="ai-spin" />
              </span>
              <span class="ai-think-label">{{ s.label }}</span>
            </div>
          </div>

          <div v-if="m.text" class="ai-bubble">{{ m.text }}</div>

          <!-- 建群人员提案卡（先确认再建群）-->
          <div v-if="m.card && m.card.kind === 'proposal'" class="ai-card">
            <div class="ai-card-h">🤝 建群提案 · <b>#{{ m.card.label }}</b></div>
            <div class="ai-card-sub">勾选要拉入的成员（按任务推荐），确认后建群</div>
            <div class="ai-propose">
              <label
                v-for="c in m.card.candidates"
                :key="c.name"
                class="ai-cand"
                :class="{ off: !c.selected, locked: m.card.done }"
              >
                <input type="checkbox" v-model="c.selected" :disabled="m.card.done" />
                <span class="ai-cand-name">{{ c.name }}</span>
                <span class="ai-cand-role">{{ c.role }}</span>
                <span class="ai-cand-reason">{{ c.reason }}</span>
              </label>
            </div>
            <div v-if="!m.card.done" class="ai-card-actions">
              <button class="ai-card-btn" @click="confirmProposal(m.card)">确认建群（{{ selectedCount(m.card) }} 人）</button>
              <button class="ai-card-btn ghost" @click="cancelProposal(m.card)">取消</button>
            </div>
            <div v-else class="ai-card-done">— 已处理 —</div>
          </div>

          <!-- 建群结果卡 -->
          <div v-else-if="m.card && m.card.kind === 'channel'" class="ai-card">
            <div class="ai-card-h">✅ 已建群 <b>#{{ m.card.label }}</b> · {{ m.card.workspace }}</div>
            <div class="ai-card-sub">自动拉入 {{ m.card.members.length }} 人</div>
            <div class="ai-card-members">
              <span v-for="n in m.card.members" :key="n" class="ai-chip-m">{{ n }}</span>
            </div>
            <button class="ai-card-btn" @click="goChannel(m.card.channelId)">前往频道 →</button>
          </div>

          <!-- 任务状态卡 -->
          <div v-else-if="m.card && m.card.kind === 'tasks'" class="ai-card">
            <div class="ai-card-h">📋 各业务群任务状态</div>
            <table class="ai-task-table">
              <thead>
                <tr><th>业务群</th><th>待办</th><th>进行</th><th>完成</th><th>逾期</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in m.card.rows" :key="r.name">
                  <td class="nm">{{ r.name }}</td>
                  <td>{{ r.pending }}</td>
                  <td>{{ r.inProgress }}</td>
                  <td>{{ r.done }}</td>
                  <td :class="{ over: r.overdue > 0 }">{{ r.overdue }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 执行卡（调度 / 应急 / 溯源 / 日报）-->
          <div v-else-if="m.card && m.card.kind === 'exec'" class="ai-card">
            <div class="ai-card-h">{{ m.card.icon }} {{ m.card.title }}</div>
            <div v-if="m.card.sub" class="ai-card-sub">{{ m.card.sub }}</div>

            <div v-if="m.card.rows && m.card.rows.length" class="ai-exec-rows">
              <div v-for="(r, ri) in m.card.rows" :key="ri" class="ai-exec-row">
                <span class="ai-exec-k">{{ r.k }}</span>
                <span class="ai-exec-v">{{ r.v }}</span>
              </div>
            </div>

            <ul v-if="m.card.steps && m.card.steps.length" class="ai-exec-steps">
              <li v-for="(s, si) in m.card.steps" :key="si" :class="{ pending: !s.done }">
                <span class="ai-exec-dot">{{ s.done ? '✓' : '…' }}</span>{{ s.text }}
              </li>
            </ul>

            <div class="ai-card-actions">
              <button
                v-if="m.card.action"
                class="ai-card-btn"
                :class="{ ghost: m.card.action.done }"
                :disabled="m.card.action.done"
                @click="confirmExec(m.card)"
              >
                {{ m.card.action.done ? '✓ ' + m.card.action.doneText : m.card.action.label }}
              </button>
              <button v-if="m.card.link" class="ai-card-btn ghost" @click="goLink(m.card.link)">
                {{ m.card.link.label }} →
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Slash 命令面板 -->
    <div v-if="showSlash" class="ai-slash-pop">
      <div class="ai-slash-sh">SLASH COMMANDS</div>
      <div
        v-for="(c, i) in slashCommands"
        :key="c.cmd"
        class="ai-slash-si"
        :class="{ act: i === 0 }"
        @mousedown.prevent="pickCommand(c.cmd)"
      >
        <span class="cmd">{{ c.cmd }}</span>
        <span class="desc">{{ c.desc }}</span>
      </div>
    </div>

    <!-- 底部输入区 -->
    <div class="ai-composer">
      <div class="ai-quick">
        <button class="ai-quick-chip" @click="quick('建群')">＋ 建群并拉人</button>
        <button class="ai-quick-chip" @click="quick('任务')">📋 查任务状态</button>
        <button class="ai-quick-chip" @click="quick('调度')">🐟 货源调度</button>
        <button class="ai-quick-chip" @click="quick('应急')">🌀 停航应急</button>
        <button class="ai-quick-chip" @click="quick('溯源')">🔗 批次溯源</button>
        <button class="ai-quick-chip" @click="quick('日报')">📊 产销日报</button>
      </div>
      <div class="ai-input-box">
        <textarea
          v-model="text"
          placeholder="Enter 发送，Ctrl+Enter 换行"
          @keydown.enter.exact.prevent="send"
          @input="onInput"
          @blur="onBlur"
        />
        <div class="ai-toolbar">
          <div class="ai-tb-left">
            <button class="ai-tb-btn" title="添加附件" @click="notify('📎', '附件', '选择图片 / 文件让 AI 分析（演示环境未启用）。')">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 17.93 8.8L9.41 17.32a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            </button>
            <button class="ai-tb-btn" title="@提及" @click="insert('@')">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="4" />
                <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8" />
              </svg>
            </button>
            <button class="ai-tb-btn" title="命令" @click="insert('/')">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="m17 6-10 12" />
              </svg>
            </button>
            <button class="ai-tb-btn" title="表情" @click="insert('🐟')">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01" />
              </svg>
            </button>
            <button class="ai-tb-btn" title="语音输入" @click="notify('🎤', '语音输入', '按住说话即可向 AI 提问（演示环境未启用麦克风）。')">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect width="6" height="11" x="9" y="2" rx="3" />
                <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4M8 22h8" />
              </svg>
            </button>
          </div>
          <button class="ai-send-ic" :disabled="!text.trim()" title="发送" @click="send">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 2 11 13" />
              <path d="M22 2 15 22l-4-9-9-4Z" />
            </svg>
          </button>
        </div>
      </div>
    </div>
    </div><!-- /ai-center -->

    <!-- 右栏：进度 + 上下文（仅 floating）-->
    <div v-if="floating" class="ai-side ai-side-right">
      <div class="ai-side-sec">
        <div class="ai-side-title with-meta">
          <span>Progress</span>
          <span class="ai-side-meta">5/8</span>
        </div>
        <ul class="ai-progress-list">
          <li class="done">海况预警解读</li>
          <li class="done">行情趋势抓取</li>
          <li class="done">货源缺口匹配</li>
          <li class="done">处置预案查询</li>
          <li class="done">码头监控接入</li>
          <li class="in">日报草稿生成中…</li>
          <li>溯源链校验</li>
          <li>推送业务群</li>
        </ul>
      </div>
      <div class="ai-side-sec">
        <div class="ai-side-title">GuDuuOS · 上下文</div>
        <ul class="ai-ctx-list">
          <li><span class="ic">📄</span>Instructions · CLAUDE.md</li>
          <li><span class="ic">📊</span>产销数据_2026Q2.xlsx</li>
          <li><span class="ic">📑</span>渔业作业规范.pdf</li>
          <li><span class="ic">🧾</span>出塘报备单模板.docx</li>
        </ul>
      </div>
    </div>

    </div><!-- /ai-main -->
  </aside>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAiPanel } from '@/composables/useAiPanel'
import { useRightPanel } from '@/composables/useRightPanel'
import { useSystemAi } from '@/composables/useSystemAi'
import { useAiAgent } from '@/composables/useAiAgent'
import { notify } from '@/composables/useDemoHeartbeat'

const { hide, toggleExpanded, toggleFloating, expanded, floating } = useAiPanel()
const { hide: hideRight } = useRightPanel()
const { open: openSettings } = useSystemAi()
const { messages: agentMessages, runCommand, reset, confirmProposal, cancelProposal, confirmExec } = useAiAgent()
const router = useRouter()


function selectedCount(card: { candidates: { selected: boolean }[] }) {
  return card.candidates.filter((c) => c.selected).length
}

function stepsOf(m: { steps?: { label: string; done: boolean }[] }) {
  return m.steps ?? []
}
function firstPendingIdx(m: { steps?: { label: string; done: boolean }[] }) {
  return (m.steps ?? []).findIndex((s) => !s.done)
}

/** 对话区随内容增长自动滚到底部（含思考步骤、结果填充）*/
const bodyRef = ref<HTMLElement | null>(null)
function scrollToBottom() {
  const el = bodyRef.value
  if (el) el.scrollTop = el.scrollHeight
}
watch(agentMessages, () => nextTick(scrollToBottom), { deep: true })

/** 打开主 AI 面板时自动收起「关于此频道」右栏，腾出空间（组件随 v-if 挂载，挂载即打开）*/
onMounted(() => {
  hideRight()
  nextTick(scrollToBottom)
})

/** 展开时同样确保 RightPanel 已收起 */
watch(expanded, (e) => { if (e) hideRight() })

/** ===== 浮窗拖拽 ===== */
const floatPos = reactive({ x: 0, y: 0 })

/** 按实际渲染尺寸居中（CSS 用了 min()，运行时尺寸可能小于声明值）*/
function recenter() {
  const panel = document.querySelector<HTMLElement>('.ai-panel.floating')
  if (!panel) return
  const r = panel.getBoundingClientRect()
  floatPos.x = Math.max(0, Math.round((window.innerWidth  - r.width)  / 2))
  floatPos.y = Math.max(0, Math.round((window.innerHeight - r.height) / 2))
}

function onToggleFloating() {
  toggleFloating()
  if (floating.value) {
    // 先粗算一次居中（用 CSS 声明值），消除 (0,0) 闪烁
    floatPos.x = Math.max(0, Math.round((window.innerWidth  - Math.min(1200, window.innerWidth  * 0.95)) / 2))
    floatPos.y = Math.max(0, Math.round((window.innerHeight - Math.min(720,  window.innerHeight * 0.90)) / 2))
    // 等 floating class 生效 + 浏览器布局后，按真实尺寸再精确居中一次
    setTimeout(recenter, 30)
  }
}

let dragStart: { mx: number; my: number; px: number; py: number } | null = null

function onHeadMouseDown(e: MouseEvent) {
  if (!floating.value) return
  // 仅允许点 header 空白区域开始拖拽（点按钮不触发）
  if ((e.target as HTMLElement).closest('button')) return
  dragStart = { mx: e.clientX, my: e.clientY, px: floatPos.x, py: floatPos.y }
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup',   onDragEnd)
  e.preventDefault()
}
function onDragMove(e: MouseEvent) {
  if (!dragStart) return
  const dx = e.clientX - dragStart.mx
  const dy = e.clientY - dragStart.my
  // 限制不被拖出视口
  floatPos.x = Math.min(window.innerWidth  - 120, Math.max(0, dragStart.px + dx))
  floatPos.y = Math.min(window.innerHeight - 60,  Math.max(0, dragStart.py + dy))
}
function onDragEnd() {
  dragStart = null
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup',   onDragEnd)
}

const text = ref('')
const showSlash = ref(false)

const slashCommands = [
  { cmd: '/help',    desc: '查看所有命令' },
  { cmd: '/summary', desc: '总结当前频道近期内容' },
  { cmd: '/draft',   desc: '帮我起草一份文档' },
  { cmd: '/explain', desc: '解释一段代码或概念' },
  { cmd: '/kb',      desc: '在企业知识库中搜索' }
]

function send() {
  if (!text.value.trim()) return
  runCommand(text.value)
  text.value = ''
  showSlash.value = false
}

/** 快捷动作：给出一句代表性指令交给 agent 执行 */
function quick(kind: '建群' | '任务' | '调度' | '应急' | '溯源' | '日报') {
  const cmd: Record<typeof kind, string> = {
    建群: '为台风应急建一个「台风应急专班」群，拉上捕捞、养殖的负责人和预警分身',
    任务: '汇总各业务群的任务状态',
    调度: '帮我调配 3000 斤大黄鱼货源，明早发货',
    应急: '明天有强对流大风，启动停航应急联动',
    溯源: '查一下批次 #YZ-0612-7 的全链路溯源',
    日报: '生成今天的产销日报'
  }
  runCommand(cmd[kind])
}

/** 卡片「前往频道」：跳到新建的频道 */
function goChannel(id: string) {
  router.push({ name: 'ops', params: { id } })
}

/** 执行卡跳转：频道 or 任意 hash 路由 */
function goLink(link: { channelId?: string; hash?: string }) {
  if (link.channelId) router.push({ name: 'ops', params: { id: link.channelId } })
  else if (link.hash) window.location.hash = link.hash
}

function onInput() {
  showSlash.value = text.value.startsWith('/')
}
function onBlur() {
  setTimeout(() => (showSlash.value = false), 200)
}
function pickCommand(cmd: string) {
  text.value = cmd + ' '
  showSlash.value = false
  nextTick(() => {
    const ta = document.querySelector<HTMLTextAreaElement>('.ai-panel textarea')
    ta?.focus()
  })
}
function insert(s: string) {
  text.value = (text.value + s).trim().length ? text.value + s : s
  if (s === '/') showSlash.value = true
  nextTick(() => {
    const ta = document.querySelector<HTMLTextAreaElement>('.ai-panel textarea')
    ta?.focus()
  })
}
</script>

<style scoped>
/* —— 快捷动作 —— */
.ai-quick { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.ai-quick-chip {
  border: 1px solid var(--border);
  background: var(--bg-panel);
  color: var(--text-2);
  font-size: var(--fs-75);
  padding: 5px 11px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}
.ai-quick-chip:hover { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }

/* —— 对话流 —— */
.ai-convo { display: flex; flex-direction: column; gap: 12px; padding-top: 4px; }
.ai-msg { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.ai-msg.user { align-items: flex-end; }
.ai-bubble {
  max-width: 88%;
  font-size: var(--fs-100);
  line-height: 1.55;
  padding: 9px 12px;
  border-radius: 12px;
  background: var(--bg-soft);
  color: var(--text);
  white-space: pre-wrap;
}
.ai-msg.user .ai-bubble { background: var(--accent); color: #fff; }

/* —— 思考进度 —— */
.ai-thinking {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 13px;
  border-radius: 12px;
  background: var(--bg-soft);
  border: 1px solid var(--border-soft);
}
.ai-think-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-75);
  color: var(--text-3);
  transition: color 0.2s ease;
}
.ai-think-step.done { color: var(--text-2); }
.ai-think-step.active { color: var(--text); font-weight: var(--fw-bold); }
.ai-think-ic {
  width: 16px; height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--ok);
}
.ai-spin {
  width: 12px; height: 12px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: ai-spin 0.7s linear infinite;
}
.ai-think-step:not(.active):not(.done) .ai-spin { opacity: 0.4; animation: none; }
@keyframes ai-spin { to { transform: rotate(360deg); } }

/* —— 结果卡片 —— */
.ai-card {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--bg-panel);
}
.ai-card-h { font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); }
.ai-card-sub { font-size: var(--fs-75); color: var(--text-3); margin-top: 2px; }
.ai-card-members { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }

/* —— 建群提案：候选成员勾选 —— */
.ai-propose { display: flex; flex-direction: column; margin: 10px 0; }
.ai-cand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 4px;
  border-bottom: 1px solid var(--border-soft);
  cursor: pointer;
  font-size: var(--fs-75);
}
.ai-cand:last-child { border-bottom: none; }
.ai-cand input { accent-color: var(--accent); cursor: pointer; }
.ai-cand-name { font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); }
.ai-cand-role {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  background: var(--bg-soft);
  padding: 1px 6px;
  border-radius: 9px;
}
.ai-cand-reason { margin-left: auto; color: var(--text-3); }
.ai-cand.off .ai-cand-name { color: var(--text-3); font-weight: var(--fw-regular); }
.ai-cand.locked { cursor: default; }

.ai-card-actions { display: flex; gap: 8px; margin-top: 4px; }
.ai-card-btn.ghost { background: transparent; color: var(--text-2); border: 1px solid var(--border); }
.ai-card-btn.ghost:hover { background: var(--bg-soft); filter: none; }
.ai-card-done { font-size: var(--fs-75); color: var(--text-3); text-align: center; margin-top: 4px; }
.ai-chip-m {
  font-size: var(--fs-75);
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--bg-soft);
  color: var(--text-2);
}
.ai-card-btn {
  border: none;
  background: var(--accent);
  color: #fff;
  font-size: var(--fs-75);
  font-weight: var(--fw-bold);
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: filter 0.12s ease;
}
.ai-card-btn:hover { filter: brightness(1.05); }

/* —— 执行卡（调度/应急/溯源/日报）—— */
.ai-exec-rows { margin: 10px 0 4px; display: flex; flex-direction: column; }
.ai-exec-row {
  display: flex;
  gap: 10px;
  padding: 6px 2px;
  border-bottom: 1px solid var(--border-soft);
  font-size: var(--fs-75);
}
.ai-exec-row:last-child { border-bottom: none; }
.ai-exec-k {
  flex-shrink: 0;
  width: 64px;
  color: var(--text-3);
  font-family: var(--mono);
}
.ai-exec-v { color: var(--text); line-height: 1.45; }
.ai-exec-steps { list-style: none; margin: 10px 0 4px; padding: 0; display: flex; flex-direction: column; gap: 7px; }
.ai-exec-steps li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: var(--fs-75);
  color: var(--text);
  line-height: 1.45;
}
.ai-exec-steps li.pending { color: var(--text-3); }
.ai-exec-dot {
  flex-shrink: 0;
  width: 16px; height: 16px;
  margin-top: 1px;
  border-radius: 50%;
  background: var(--ok); color: #fff;
  font-size: 10px;
  display: inline-flex; align-items: center; justify-content: center;
}
.ai-exec-steps li.pending .ai-exec-dot { background: var(--bg-hover); color: var(--text-3); }
.ai-card-btn:disabled { cursor: default; opacity: 0.75; }

/* —— 任务状态表 —— */
.ai-task-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: var(--fs-75); }
.ai-task-table th {
  text-align: center;
  color: var(--text-3);
  font-weight: var(--fw-regular);
  padding: 4px 6px;
  border-bottom: 1px solid var(--border);
}
.ai-task-table th:first-child { text-align: left; }
.ai-task-table td {
  text-align: center;
  padding: 5px 6px;
  border-bottom: 1px solid var(--border-soft);
  color: var(--text-2);
}
.ai-task-table td.nm { text-align: left; color: var(--text); font-weight: var(--fw-bold); white-space: nowrap; }
.ai-task-table td.over { color: var(--danger); font-weight: var(--fw-bold); }
</style>
