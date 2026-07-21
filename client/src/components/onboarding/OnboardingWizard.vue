<template>
  <!-- 首次引导：全屏覆盖层 + 聊天式「主 AI 问答」向导。
       答完直接真建工作区/频道/AI人设（见 useOnboarding）。完成 emit done(spaceId)，跳过 emit skip。 -->
  <div v-if="visible" class="onb-mask">
    <div class="onb">
      <header class="onb-head">
        <span class="onb-logo">✦ GuDuu OS</span>
        <span class="onb-sub">初次设置</span>
        <button v-if="step !== 'creating'" class="onb-skip" @click="onSkip">跳过，直接进入</button>
      </header>

      <!-- 对话区 -->
      <div ref="scroll" class="onb-chat">
        <div v-for="(m, i) in messages" :key="i" class="onb-msg" :class="m.role">
          <span v-if="m.role === 'ai'" class="onb-ava">智</span>
          <div class="onb-bubble">{{ m.text }}</div>
        </div>
        <div v-if="error" class="onb-err">⚠️ {{ error }}</div>
      </div>

      <!-- 当前步骤的输入控件 -->
      <footer class="onb-foot">
        <!-- ① 行业模板 -->
        <div v-if="step === 'template'" class="onb-tpls">
          <button v-for="t in templates" :key="t.key" class="onb-tpl" :class="{ locked: templateLocked(t) }" @click="pickTemplate(t.key)">
            <span class="onb-tpl-ic">{{ t.icon }}</span>
            <span class="onb-tpl-main">
              <span class="onb-tpl-label">{{ t.label }}<span v-if="t.paid" class="onb-tpl-paid">{{ templateLocked(t) ? '🔒 付费' : '付费' }}</span></span>
              <span class="onb-tpl-desc">{{ t.desc }}</span>
            </span>
          </button>
        </div>

        <!-- ② 工作区名 -->
        <form v-else-if="step === 'name'" class="onb-row" @submit.prevent="onName">
          <input v-model="nameInput" class="onb-input" placeholder="给工作区起个名字" autofocus />
          <button class="onb-send" :disabled="!nameInput.trim()">下一步 →</button>
        </form>

        <!-- ③ 频道增删 -->
        <div v-else-if="step === 'channels'" class="onb-chans">
          <div class="onb-chips">
            <span v-for="(c, i) in answers.channels" :key="i" class="onb-chip"># {{ c }}<button class="onb-chip-x" @click="removeChannel(i)">×</button></span>
            <span v-if="!answers.channels.length" class="onb-chip-empty">先不建频道也行</span>
          </div>
          <form class="onb-row" @submit.prevent="onAddChan">
            <input v-model="chanInput" class="onb-input" placeholder="再加一个频道，回车添加" />
            <button class="onb-add" :disabled="!chanInput.trim()" type="submit">＋ 加</button>
            <button class="onb-send" type="button" @click="onConfirmChannels">下一步 →</button>
          </form>
        </div>

        <!-- ④ 主 AI 人设 -->
        <form v-else-if="step === 'persona'" class="onb-persona" @submit.prevent="onPersona">
          <input v-model="aiNameInput" class="onb-input" placeholder="AI 的名字（如 中枢 AI）" />
          <textarea v-model="aiPersonaInput" class="onb-textarea" rows="3" placeholder="一句话人设：它是谁、擅长什么" />
          <button class="onb-send" :disabled="!aiNameInput.trim()">下一步 →</button>
        </form>

        <!-- ⑤ 确认 -->
        <div v-else-if="step === 'confirm'" class="onb-confirm">
          <div class="onb-review">
            <div class="onb-rv"><span>工作区</span><b>{{ answers.workspace }}</b></div>
            <div class="onb-rv"><span>频道</span><b>{{ answers.channels.join('、') || '（无）' }}</b></div>
            <div class="onb-rv"><span>中枢 AI</span><b>{{ answers.aiName }}</b></div>
            <div v-if="answers.model" class="onb-rv"><span>模型</span><b>{{ answers.model }}</b></div>
            <div v-if="answers.skillSlugs.length" class="onb-rv"><span>技能</span><b>{{ answers.skillSlugs.length }} 项</b></div>
            <div v-if="answers.kbDocs.length" class="onb-rv"><span>知识库</span><b>{{ answers.kbDocs.length }} 篇</b></div>
            <div v-if="answers.workflowSlugs.length" class="onb-rv"><span>工作流</span><b>{{ answers.workflowSlugs.length }} 个</b></div>
          </div>
          <div class="onb-row">
            <button class="onb-back" @click="goStep('template')">重来</button>
            <button class="onb-create" :disabled="busy" @click="onCreate">✦ 创建我的工作台</button>
          </div>
        </div>

        <!-- 创建中 -->
        <div v-else-if="step === 'creating'" class="onb-creating">
          <span class="onb-spin" /> 正在搭建工作台…
        </div>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onBeforeUnmount } from 'vue'
import { useOnboarding } from '@/composables/useOnboarding'

const emit = defineEmits<{ (e: 'done', spaceId: string): void; (e: 'skip'): void }>()

const {
  visible, step, messages, busy, error, answers, templates, templateLocked,
  pickTemplate: pick, submitName, addChannel, removeChannel, confirmChannels,
  submitPersona, goStep, runCreate, skip,
} = useOnboarding()

// 各步骤输入
const nameInput = ref('')
const chanInput = ref('')
const aiNameInput = ref('')
const aiPersonaInput = ref('')

function pickTemplate(key: string) { pick(key) }
function onName() { submitName(nameInput.value); nameInput.value = '' }
function onAddChan() { addChannel(chanInput.value); chanInput.value = '' }
// "下一步"前先把输入框里没点"＋加"的残留频道补进去(QA:手动输了频道名没点加就下一步→丢失)
function onConfirmChannels() {
  if (chanInput.value.trim()) { addChannel(chanInput.value); chanInput.value = '' }
  confirmChannels()
}

// 进入 persona 步时把模板预填的 AI 名/人设带进输入框
watch(step, (s) => {
  if (s === 'persona') { aiNameInput.value = answers.aiName; aiPersonaInput.value = answers.aiPersona }
})
function onPersona() { submitPersona(aiNameInput.value, aiPersonaInput.value) }

let doneTimer: ReturnType<typeof setTimeout> | null = null
async function onCreate() {
  try {
    const sid = await runCreate()
    // 稍等让"搭好了"气泡显示一下，再切进新工作区
    doneTimer = setTimeout(() => { doneTimer = null; visible.value = false; emit('done', sid) }, 700)
  } catch { /* 错误已在 composable 里写进 error，停在确认页 */ }
}
// 组件卸载时清掉未触发的定时器，避免卸载后还 emit('done')/改 visible（对已销毁实例操作）。
onBeforeUnmount(() => { if (doneTimer) { clearTimeout(doneTimer); doneTimer = null } })
async function onSkip() { await skip(); emit('skip') }

// 新消息自动滚到底
const scroll = ref<HTMLElement | null>(null)
watch(messages, () => { nextTick(() => { if (scroll.value) scroll.value.scrollTop = scroll.value.scrollHeight }) }, { deep: true })
</script>

<style scoped>
/* 毛玻璃遮罩：半透明 + 背景模糊，让后面的应用数据透出来但虚化，聚焦在 AI 引导卡片上。
   （backdrop-filter 不支持的旧浏览器会回退成半透明底色，仍可用。）*/
.onb-mask { position: fixed; inset: 0; z-index: 3000; background: rgba(245, 243, 238, 0.35); backdrop-filter: blur(5px) saturate(1.05); -webkit-backdrop-filter: blur(5px) saturate(1.05); display: flex; align-items: center; justify-content: center; padding: 24px; }
.onb { width: 100%; max-width: 560px; height: min(680px, 90vh); display: flex; flex-direction: column; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 18px; box-shadow: 0 24px 64px rgba(0,0,0,.18); overflow: hidden; }
.onb-head { display: flex; align-items: center; gap: 10px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.onb-logo { font-weight: 800; color: var(--text); letter-spacing: .3px; }
.onb-sub { font-size: 12px; color: var(--text-3); }
.onb-skip { margin-left: auto; border: none; background: transparent; color: var(--text-3); font-size: 12px; cursor: pointer; }
.onb-skip:hover { color: var(--text); text-decoration: underline; }

.onb-chat { flex: 1; overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 12px; }
.onb-msg { display: flex; gap: 8px; align-items: flex-start; max-width: 90%; }
.onb-msg.ai { align-self: flex-start; }
.onb-msg.user { align-self: flex-end; flex-direction: row-reverse; }
.onb-ava { width: 26px; height: 26px; flex-shrink: 0; border-radius: 50%; background: linear-gradient(135deg, var(--accent), var(--warn, #e0883a)); color: #fff; font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.onb-bubble { padding: 9px 13px; border-radius: 13px; font-size: 14px; line-height: 1.6; }
.onb-msg.ai .onb-bubble { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-top-left-radius: 4px; }
.onb-msg.user .onb-bubble { background: var(--accent); color: #fff; border-top-right-radius: 4px; }
.onb-err { align-self: center; font-size: 12px; color: #b94a4a; }

.onb-foot { border-top: 1px solid var(--border); padding: 14px 20px; }
.onb-row { display: flex; gap: 8px; align-items: center; }
.onb-input { flex: 1; min-width: 0; padding: 10px 13px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-input, var(--bg)); color: var(--text); font-size: 14px; }
.onb-input:focus { outline: none; border-color: var(--accent); }
.onb-textarea { width: 100%; box-sizing: border-box; margin-bottom: 8px; padding: 10px 13px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-input, var(--bg)); color: var(--text); font-size: 14px; resize: vertical; font-family: inherit; }
.onb-textarea:focus { outline: none; border-color: var(--accent); }
.onb-send, .onb-create { border: none; background: var(--accent); color: #fff; font-size: 13px; font-weight: 700; padding: 10px 16px; border-radius: 10px; cursor: pointer; white-space: nowrap; }
.onb-send:disabled, .onb-create:disabled { opacity: .5; cursor: not-allowed; }
.onb-add { border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-2); font-size: 13px; padding: 10px 12px; border-radius: 10px; cursor: pointer; white-space: nowrap; }
.onb-add:disabled { opacity: .5; cursor: not-allowed; }

.onb-tpls { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.onb-tpl { display: flex; align-items: center; gap: 10px; text-align: left; padding: 10px 12px; border: 1px solid var(--border); border-radius: 11px; background: var(--bg); cursor: pointer; }
.onb-tpl:hover { border-color: var(--accent); }
.onb-tpl.locked { opacity: .6; }
.onb-tpl.locked:hover { border-color: var(--border); }
.onb-tpl-ic { font-size: 20px; }
.onb-tpl-main { display: flex; flex-direction: column; min-width: 0; }
.onb-tpl-label { font-size: 13px; font-weight: 700; color: var(--text); }
.onb-tpl-paid { margin-left: 6px; font-size: 10px; font-weight: 700; color: var(--accent); border: 1px solid var(--accent); border-radius: 999px; padding: 0 6px; vertical-align: middle; }
.onb-tpl-desc { font-size: 11px; color: var(--text-3); }

.onb-chans { display: flex; flex-direction: column; gap: 10px; }
.onb-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.onb-chip { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text); background: var(--bg); border: 1px solid var(--border); padding: 4px 8px; border-radius: 999px; }
.onb-chip-x { border: none; background: transparent; color: var(--text-3); cursor: pointer; font-size: 14px; line-height: 1; }
.onb-chip-x:hover { color: #b94a4a; }
.onb-chip-empty { font-size: 12px; color: var(--text-3); }

.onb-persona { display: flex; flex-direction: column; }
.onb-persona .onb-send { align-self: flex-end; }

.onb-confirm { display: flex; flex-direction: column; gap: 12px; }
.onb-review { background: var(--bg); border: 1px solid var(--border); border-radius: 11px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.onb-rv { display: flex; gap: 12px; font-size: 13px; }
.onb-rv > span { color: var(--text-3); width: 56px; flex-shrink: 0; }
.onb-rv > b { color: var(--text); }
.onb-back { border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-2); font-size: 13px; padding: 10px 16px; border-radius: 10px; cursor: pointer; }
.onb-create { flex: 1; }

.onb-creating { display: flex; align-items: center; justify-content: center; gap: 10px; color: var(--text-2); font-size: 14px; padding: 6px; }
.onb-spin { width: 16px; height: 16px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: onb-rot 0.8s linear infinite; }
@keyframes onb-rot { to { transform: rotate(360deg); } }
</style>
