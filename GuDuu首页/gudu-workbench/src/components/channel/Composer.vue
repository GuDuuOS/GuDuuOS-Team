<template>
  <div class="composer">
    <!-- Slash 命令面板 -->
    <div v-if="commands && commands.length" class="slash-pop" :class="{ show: showSlash }">
      <div class="sh">SLASH COMMANDS</div>
      <div
        v-for="(c, i) in commands"
        :key="c.cmd"
        class="si"
        :class="{ act: i === 0 }"
        @mousedown.prevent="pickCommand(c.cmd)"
      >
        <span class="cmd">{{ c.cmd }}</span>
        <span class="desc">{{ c.desc }}</span>
      </div>
    </div>

    <div class="composer-box">
      <textarea
        ref="taRef"
        v-model="text"
        :placeholder="placeholder ?? `发送到${channelLabel}`"
        @input="onInput"
        @blur="onBlur"
        @keydown.enter.exact.prevent="send"
      />
      <div class="composer-toolbar">
        <div class="tb-left">
          <button class="tb-btn" title="加粗" @mousedown.prevent="wrap('**','**')"><b style="font-family:var(--serif)">B</b></button>
          <button class="tb-btn" title="斜体" @mousedown.prevent="wrap('*','*')"><i style="font-family:var(--serif)">I</i></button>
          <button class="tb-btn" title="删除线" @mousedown.prevent="wrap('~~','~~')"><s>S</s></button>
          <button class="tb-btn tb-heading" title="标题" @mousedown.prevent="prefixLine('# ')">H</button>
          <span class="tb-sep" />
          <button class="tb-btn" title="链接" @mousedown.prevent="wrap('[','](https://)')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
            </svg>
          </button>
          <button class="tb-btn" title="代码" @mousedown.prevent="wrap('`','`')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="16 18 22 12 16 6" />
              <polyline points="8 6 2 12 8 18" />
            </svg>
          </button>
          <button class="tb-btn" title="引用" @mousedown.prevent="prefixLine('> ')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 7v6H4V9c0-1.1.9-2 2-2h1Zm10 0v6h-3V9c0-1.1.9-2 2-2h1Z"/></svg>
          </button>
          <button class="tb-btn" title="无序列表" @mousedown.prevent="prefixLine('- ')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="8" y1="6" x2="21" y2="6" />
              <line x1="8" y1="12" x2="21" y2="12" />
              <line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" />
              <line x1="3" y1="12" x2="3.01" y2="12" />
              <line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
          </button>
          <button class="tb-btn" title="有序列表" @mousedown.prevent="prefixLine('1. ')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="10" y1="6" x2="21" y2="6" />
              <line x1="10" y1="12" x2="21" y2="12" />
              <line x1="10" y1="18" x2="21" y2="18" />
              <path d="M4 6h1v4M4 10h2M6 18H4c0-1 2-2 2-3s-1-1.5-2-1" />
            </svg>
          </button>
          <button class="tb-btn" title="提醒（@所有人）" @mousedown.prevent="insertText('@所有人 ')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </button>
          <button class="tb-btn" title="语音输入" @click="notify('🎤', '语音输入', '按住说话即可转文字录入（演示环境未启用麦克风）。')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect width="6" height="11" x="9" y="2" rx="3" />
              <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4M8 22h8" />
            </svg>
          </button>
          <button class="tb-btn" title="@提及" @mousedown.prevent="insertText('@')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="4" />
              <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8" />
            </svg>
          </button>
        </div>
        <div class="tb-right">
          <button class="tb-btn" title="字号" @click="notify('🅰', '字号', '正文 / 标题 / 小字 切换（演示）。')">
            <span style="font-family:var(--serif);font-weight:600">Aa</span>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="margin-left:2px"><path d="m6 9 6 6 6-6"/></svg>
          </button>
          <button class="tb-btn" title="附件" @click="notify('📎', '附件', '选择图片 / 文件上传（演示环境未启用）。')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 17.93 8.8L9.41 17.32a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
          </button>
          <button class="tb-btn" title="表情" @mousedown.prevent="insertText('🐟')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10" />
              <path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01" />
            </svg>
          </button>
          <button class="send" :disabled="!text.trim()" title="发送 (Enter)" aria-label="发送" @click="send">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 2 11 13"/>
              <path d="M22 2 15 22l-4-9-9-4Z"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import type { SlashCommand } from '@/data/messages/duu'
import { smartSend } from '@/composables/useSmartReply'
import { notify } from '@/composables/useDemoHeartbeat'

const props = defineProps<{
  channelLabel: string
  placeholder?: string
  enableEmoji?: boolean
  commands?: SlashCommand[]
}>()

const text = ref('')
const showSlash = ref(false)
const taRef = ref<HTMLTextAreaElement | null>(null)

/* ===== 工具栏：基于光标选区编辑（@mousedown.prevent 保留选区不失焦）===== */
function selRange(): [number, number] {
  const el = taRef.value
  if (!el) return [text.value.length, text.value.length]
  return [el.selectionStart ?? text.value.length, el.selectionEnd ?? text.value.length]
}
function applyAndFocus(next: string, caret: number) {
  text.value = next
  nextTick(() => {
    const el = taRef.value
    if (el) { el.focus(); el.setSelectionRange(caret, caret) }
  })
}
/** 在选区两侧包裹标记（如 **加粗**）；无选区则插入占位 */
function wrap(pre: string, post: string) {
  const [s, e] = selRange()
  const t = text.value
  const sel = t.slice(s, e) || '文字'
  applyAndFocus(t.slice(0, s) + pre + sel + post + t.slice(e), s + pre.length + sel.length + post.length)
}
/** 在当前行首插入前缀（如 # 、- 、> ）*/
function prefixLine(pre: string) {
  const [s] = selRange()
  const t = text.value
  const lineStart = t.lastIndexOf('\n', s - 1) + 1
  applyAndFocus(t.slice(0, lineStart) + pre + t.slice(lineStart), s + pre.length)
}
/** 在光标处插入文本（@、emoji 等）*/
function insertText(str: string) {
  const [s, e] = selRange()
  const t = text.value
  applyAndFocus(t.slice(0, s) + str + t.slice(e), s + str.length)
}

/** 发送：用户消息上屏，分身按关键词智能应答 */
function send() {
  if (!text.value.trim()) return
  if (smartSend(text.value)) {
    text.value = ''
    showSlash.value = false
  }
}

function onInput() {
  if (!props.commands || !props.commands.length) return
  showSlash.value = text.value.startsWith('/')
}

function onBlur() {
  setTimeout(() => (showSlash.value = false), 200)
}

function pickCommand(cmd: string) {
  text.value = cmd + ' '
  showSlash.value = false
}
</script>
