<template>
  <div v-if="wizardActive" class="wiz-overlay">
    <div class="wiz-dialog">
      <!-- 头部 -->
      <div class="wiz-head">
        <img class="wiz-avatar" src="/gudu-logo.svg" alt="GuDuu" />
        <div class="wiz-meta">
          <div class="wiz-name">GuDuu 总控分身</div>
          <div class="wiz-sub">智能协作体系 · 初始化向导</div>
        </div>
        <div class="wiz-progress">{{ Math.min(wizStage + 1, WIZ_TOTAL) }}/{{ WIZ_TOTAL }}</div>
        <button class="wiz-skip" @click="skipWizard">跳过搭建，直接进入 →</button>
      </div>

      <!-- 对话流 -->
      <div ref="bodyRef" class="wiz-body">
        <div v-for="m in wizMsgs" :key="m.id" class="wiz-msg" :class="m.role">
          <!-- 思考 / 执行步骤 -->
          <div v-if="m.steps" class="wiz-think">
            <div
              v-for="(s, si) in m.steps"
              :key="si"
              class="wiz-step"
              :class="{ done: s.done, active: !s.done && si === firstPending(m) }"
            >
              <span class="wiz-step-ic">
                <svg v-if="s.done" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <span v-else class="wiz-spin" />
              </span>
              {{ s.label }}
            </div>
          </div>
          <template v-else>
            <div v-if="m.text" class="wiz-bubble">{{ m.text }}</div>

            <!-- 邀请卡：二维码 + 企业码 -->
            <div v-if="m.invite" class="wiz-card">
              <div class="wiz-card-h">📨 {{ m.invite.method }} · 加入「蓝湾渔业」</div>
              <div class="wiz-invite">
                <div class="wiz-qr" aria-label="邀请二维码">
                  <span v-for="(on, qi) in QR_PATTERN" :key="qi" :class="{ on }" />
                </div>
                <div class="wiz-invite-info">
                  <div class="wiz-invite-row"><span class="k">企业码</span><code>{{ m.invite.code }}</code></div>
                  <div class="wiz-invite-row"><span class="k">有效期</span>企业码长期 · 二维码 24h</div>
                  <div class="wiz-invite-row"><span class="k">权限</span>加入后默认「岗位成员」，可再调整</div>
                  <div class="wiz-invite-tip">短信 / 邮箱邀请将携带同一入口链接</div>
                </div>
              </div>
            </div>

            <!-- 分身配置方案卡 -->
            <div v-if="m.agents" class="wiz-card">
              <div class="wiz-card-h">🤖 分身配置方案（{{ m.agents.length }} 个）</div>
              <div class="wiz-agents">
                <div v-for="a in m.agents" :key="a.name" class="wiz-agent">
                  <span class="wiz-agent-av" :data-avatar="a.avatar">{{ a.avatar }}</span>
                  <span class="wiz-agent-name">{{ a.name }}</span>
                  <span class="wiz-agent-duty">{{ a.duty }}</span>
                  <span class="wiz-agent-src" :class="{ tpl: a.src === '模板补齐' }">{{ a.src }}</span>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- 快捷回复 + 输入 -->
      <div class="wiz-foot">
        <div v-if="wizQuick.length" class="wiz-quick">
          <button v-for="q in wizQuick" :key="q" class="wiz-quick-btn" :disabled="wizBusy" @click="onQuick(q)">
            {{ q }}
          </button>
        </div>
        <div class="wiz-input-row">
          <input
            v-model="text"
            class="wiz-input"
            :disabled="wizBusy"
            placeholder="也可以直接输入回答…"
            @keydown.enter="onSend"
          />
          <button class="wiz-send" :disabled="wizBusy || !text.trim()" @click="onSend">发送</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import {
  WIZ_TOTAL,
  answerWizard,
  finishWizard,
  skipWizard,
  startWizard,
  wizardActive,
  wizBusy,
  wizMsgs,
  wizQuick,
  wizStage,
  type WizMsg
} from '@/composables/useSetupWizard'

const text = ref('')
const bodyRef = ref<HTMLElement | null>(null)

/** 9×9 伪二维码图案（定位角 + 固定数据位，渲染稳定）*/
const QR_PATTERN: boolean[] = (() => {
  const n = 9
  const g = Array.from({ length: n * n }, () => false)
  const set = (r: number, c: number) => { g[r * n + c] = true }
  // 三个定位角
  for (const [r0, c0] of [[0, 0], [0, 6], [6, 0]] as const) {
    for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) {
      if (r === 1 && c === 1) continue
      set(r0 + r, c0 + c)
    }
    set(r0 + 1, c0 + 1)
  }
  // 固定"数据"位
  for (const [r, c] of [[1, 4], [3, 1], [3, 3], [3, 5], [3, 8], [4, 0], [4, 2], [4, 4], [4, 7], [5, 3], [5, 6], [5, 8], [6, 4], [7, 6], [7, 8], [8, 4], [8, 5], [8, 7]]) set(r, c)
  return g
})()

function firstPending(m: WizMsg) {
  return (m.steps ?? []).findIndex((s) => !s.done)
}

function onQuick(q: string) {
  if (wizStage.value >= WIZ_TOTAL && q.includes('进入工作台')) {
    finishWizard()
    return
  }
  answerWizard(q)
}

function onSend() {
  const t = text.value.trim()
  if (!t || wizBusy.value) return
  text.value = ''
  if (wizStage.value >= WIZ_TOTAL) {
    finishWizard()
    return
  }
  answerWizard(t)
}

watch(
  wizMsgs,
  () => nextTick(() => {
    const el = bodyRef.value
    if (el) el.scrollTop = el.scrollHeight
  }),
  { deep: true }
)

onMounted(startWizard)
</script>

<style scoped>
.wiz-overlay {
  position: fixed;
  inset: 0;
  z-index: 500;
  /* 渐变遮罩：右侧重、左侧轻且不模糊，搭建过程（工作区/频道/分身长出来）清晰可见 */
  background: linear-gradient(90deg, rgba(20, 18, 14, 0.08) 0%, rgba(20, 18, 14, 0.18) 40%, rgba(20, 18, 14, 0.42) 100%);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 28px;
  animation: wiz-fade 0.25s ease;
}
@keyframes wiz-fade { from { opacity: 0 } to { opacity: 1 } }

.wiz-dialog {
  width: min(560px, 92vw);
  height: min(720px, 88vh);
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-radius: 16px;
  box-shadow: 0 32px 80px rgba(0, 0, 0, 0.3), 0 4px 12px rgba(0, 0, 0, 0.12);
  overflow: hidden;
  animation: wiz-pop 0.28s ease;
}
@keyframes wiz-pop { from { opacity: 0; transform: translateY(14px) scale(0.98) } to { opacity: 1; transform: none } }

/* 头部 */
.wiz-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}
.wiz-avatar {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: var(--bot-avatar);
  padding: 4px;
  box-sizing: border-box;
  object-fit: contain;
}
.wiz-meta { min-width: 0; }
.wiz-name { font-weight: var(--fw-bold); font-size: var(--fs-200); color: var(--text); }
.wiz-sub { font-size: var(--fs-75); color: var(--text-3); }
.wiz-progress {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-3);
  background: var(--bg-soft);
  padding: 3px 9px;
  border-radius: 999px;
}
.wiz-skip {
  border: none;
  background: transparent;
  color: var(--text-3);
  font-size: var(--fs-75);
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 6px;
}
.wiz-skip:hover { color: var(--accent); background: var(--bg-soft); }

/* 对话流 */
.wiz-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 260px;
}
.wiz-msg { display: flex; flex-direction: column; align-items: flex-start; }
.wiz-msg.user { align-items: flex-end; }
.wiz-bubble {
  max-width: 90%;
  font-size: var(--fs-100);
  line-height: 1.6;
  padding: 10px 13px;
  border-radius: 12px;
  background: var(--bg-soft);
  color: var(--text);
  white-space: pre-wrap;
}
.wiz-msg.user .wiz-bubble { background: var(--accent); color: #fff; }

/* 思考步骤 */
.wiz-think {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 13px;
  border-radius: 12px;
  background: var(--bg-soft);
  border: 1px solid var(--border-soft);
  min-width: 60%;
}
.wiz-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-75);
  color: var(--text-3);
}
.wiz-step.done { color: var(--text-2); }
.wiz-step.active { color: var(--text); font-weight: var(--fw-bold); }
.wiz-step-ic {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--ok);
}
.wiz-spin {
  width: 12px;
  height: 12px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: wiz-spin 0.7s linear infinite;
}
.wiz-step:not(.active):not(.done) .wiz-spin { opacity: 0.35; animation: none; }
@keyframes wiz-spin { to { transform: rotate(360deg) } }

/* 通用卡片 */
.wiz-card {
  width: 100%;
  margin-top: 8px;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--bg-panel);
  box-sizing: border-box;
}
.wiz-card-h { font-size: var(--fs-100); font-weight: var(--fw-bold); color: var(--text); margin-bottom: 10px; }

/* 邀请卡 */
.wiz-invite { display: flex; gap: 14px; align-items: flex-start; }
.wiz-qr {
  flex-shrink: 0;
  width: 92px;
  height: 92px;
  padding: 7px;
  box-sizing: border-box;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  display: grid;
  grid-template-columns: repeat(9, 1fr);
  grid-template-rows: repeat(9, 1fr);
  gap: 1px;
}
.wiz-qr span { background: transparent; border-radius: 1px; }
.wiz-qr span.on { background: #1a1a1a; }
.wiz-invite-info { min-width: 0; flex: 1; }
.wiz-invite-row {
  display: flex;
  gap: 8px;
  font-size: var(--fs-75);
  color: var(--text-2);
  padding: 3px 0;
  align-items: baseline;
}
.wiz-invite-row .k {
  flex-shrink: 0;
  width: 42px;
  color: var(--text-3);
  font-family: var(--mono);
  font-size: 11px;
}
.wiz-invite-row code {
  font-family: var(--mono);
  background: var(--bg-soft);
  padding: 1px 8px;
  border-radius: 6px;
  color: var(--accent);
  font-weight: 600;
  letter-spacing: 1px;
}
.wiz-invite-tip { font-size: 11px; color: var(--text-3); margin-top: 6px; }

/* 分身方案卡 */
.wiz-agents { display: flex; flex-direction: column; }
.wiz-agent {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 2px;
  border-bottom: 1px solid var(--border-soft);
  font-size: var(--fs-75);
}
.wiz-agent:last-child { border-bottom: none; }
.wiz-agent-av {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: var(--bot-avatar);
  color: var(--bot-avatar-text);
  font-size: 11px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.wiz-agent-name { font-weight: var(--fw-bold); color: var(--text); white-space: nowrap; }
.wiz-agent-duty { color: var(--text-3); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wiz-agent-src {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 10px;
  font-family: var(--mono);
  color: var(--ok);
  background: rgba(107, 142, 78, 0.1);
  padding: 1px 7px;
  border-radius: 9px;
}
.wiz-agent-src.tpl { color: var(--text-3); background: var(--bg-soft); }

/* 底部 */
.wiz-foot { border-top: 1px solid var(--border); padding: 12px 16px 14px; }
.wiz-quick { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.wiz-quick-btn {
  border: 1px solid var(--accent);
  background: var(--accent-soft, rgba(201, 100, 66, 0.08));
  color: var(--accent);
  font-size: var(--fs-100);
  font-weight: var(--fw-bold);
  padding: 8px 14px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}
.wiz-quick-btn:hover:not(:disabled) { background: var(--accent); color: #fff; }
.wiz-quick-btn:disabled { opacity: 0.5; cursor: default; }
.wiz-input-row { display: flex; gap: 8px; }
.wiz-input {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 8px 12px;
  font-size: var(--fs-100);
  background: var(--bg);
  color: var(--text);
  outline: none;
}
.wiz-input:focus { border-color: var(--accent); }
.wiz-send {
  border: none;
  background: var(--accent);
  color: #fff;
  font-size: var(--fs-100);
  font-weight: var(--fw-bold);
  padding: 8px 16px;
  border-radius: 9px;
  cursor: pointer;
}
.wiz-send:disabled { opacity: 0.45; cursor: default; }
</style>
