<template>
  <div v-if="visible" class="cli-overlay" @click.self="close">
    <div class="cli-modal" role="dialog" aria-modal="true">
      <div class="cli-head">
        <span class="cli-dot r" /><span class="cli-dot y" /><span class="cli-dot g" />
        <span class="cli-title">GuDuu CLI</span>
        <div class="cli-tabs">
          <button class="cli-tab" :class="{ active: tab === 'cloud' }" @click="tab = 'cloud'">云端应用</button>
          <button class="cli-tab" :class="{ active: tab === 'local' }" @click="tab = 'local'">本地连接</button>
        </div>
        <button class="cli-close" title="关闭" @click="close">×</button>
      </div>

      <!-- 界面一：云端应用 -->
      <div v-if="tab === 'cloud'" class="cli-cloud">
        <div class="cli-cloud-hint">在<b>云端电脑</b>上一键安装软件，装好即用——无需占用本地资源；带桥接的应用会在频道里实时收发消息。</div>
        <div class="cli-grid">
          <div v-for="a in cloudApps" :key="a.key" class="cli-app-card" @click="installCloud(a)">
            <div class="cli-app-tile" :style="{ background: a.color }">{{ a.initial }}</div>
            <div class="cli-app-info">
              <div class="cli-app-nm">{{ a.name }}<span v-if="a.bridge" class="cli-app-bridge">桥接</span></div>
              <button
                class="cli-install"
                :class="{ installing: a.status === 'installing', done: a.status === 'installed' }"
                @click.stop="installCloud(a)"
              >
                {{ a.status === 'installed' ? '使用' : a.status === 'installing' ? '安装中…' : '安装' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 界面二：本地连接（终端 + 右侧快捷操作）-->
      <div v-else class="cli-local">
        <div class="cli-term">
          <div ref="logRef" class="cli-log">
            <div v-for="(l, i) in lines" :key="i" class="cli-line" :class="l.type">
              <span v-if="l.type === 'in'" class="cli-prompt">gduu&nbsp;❯</span>{{ l.text }}
            </div>
          </div>
          <div class="cli-quick">
            <button v-for="c in quick" :key="c" class="cli-chip" @click="run(c)">{{ c }}</button>
          </div>
          <div class="cli-input-row">
            <span class="cli-prompt">gduu&nbsp;❯</span>
            <input v-model="text" class="cli-input" spellcheck="false" placeholder="输入命令，回车执行（help）" @keyup.enter="submit" />
          </div>
        </div>

        <div class="cli-side">
          <div class="cli-side-title">快捷操作</div>
          <button v-for="s in localShortcuts" :key="s.cmd" class="cli-side-btn" @click="run(s.cmd)">
            <span class="cli-side-dot" :class="{ on: localConnected }" />
            {{ s.label }}
          </button>
          <div class="cli-side-hint">连接本地电脑后，主 AI 可读写本地文件、调用本地应用、执行命令（每次需授权）。</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useCli, localShortcuts } from '@/composables/useCli'

const { visible, tab, cloudApps, lines, localConnected, installCloud, run, close } = useCli()

const text = ref('')
const quick = ['connect', 'ls', 'status', 'help']
const logRef = ref<HTMLElement | null>(null)

function submit() {
  if (!text.value.trim()) return
  run(text.value)
  text.value = ''
}
function scrollToBottom() {
  const el = logRef.value
  if (el) el.scrollTop = el.scrollHeight
}
watch(lines, () => nextTick(scrollToBottom), { deep: true })

function onKey(e: KeyboardEvent) { if (e.key === 'Escape' && visible.value) close() }
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<style scoped>
.cli-overlay {
  position: fixed;
  inset: 0;
  z-index: 210;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: cli-fade 0.14s ease;
}
@keyframes cli-fade { from { opacity: 0 } to { opacity: 1 } }

.cli-modal {
  width: min(960px, 94vw);
  height: min(620px, 88vh);
  display: flex;
  flex-direction: column;
  background: #1b2027;
  border-radius: 14px;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.4);
  overflow: hidden;
  animation: cli-pop 0.16s ease;
}
@keyframes cli-pop { from { opacity: 0; transform: translateY(10px) scale(0.985) } to { opacity: 1; transform: none } }

.cli-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #232a33;
  border-bottom: 1px solid #2f3742;
}
.cli-dot { width: 11px; height: 11px; border-radius: 50%; }
.cli-dot.r { background: #ec6a5e; }
.cli-dot.y { background: #f4be4f; }
.cli-dot.g { background: #61c554; }
.cli-title { margin-left: 8px; color: #e7ecf2; font-weight: 700; font-family: var(--font-mono); font-size: 14px; }
.cli-tabs { display: flex; gap: 4px; margin-left: 16px; }
.cli-tab {
  border: none;
  background: transparent;
  color: #8a97a6;
  font-size: 13px;
  padding: 5px 12px;
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}
.cli-tab:hover { color: #e7ecf2; }
.cli-tab.active { background: #2f3742; color: #fff; }
.cli-close {
  margin-left: auto;
  width: 28px; height: 28px;
  border: none; background: transparent;
  color: #8a97a6; font-size: 20px; line-height: 1; cursor: pointer;
  border-radius: 6px;
}
.cli-close:hover { background: #2f3742; color: #e7ecf2; }

/* ── 云端应用 ── */
.cli-cloud { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 18px 20px; }
.cli-cloud-hint { color: #8a97a6; font-size: 12px; line-height: 1.6; margin-bottom: 16px; }
.cli-cloud-hint b { color: #c9d4e0; }
.cli-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 12px;
}
.cli-app-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: #232a33;
  border: 1px solid #2f3742;
  border-radius: 12px;
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}
.cli-app-card:hover { border-color: #5aa9e6; background: #262f39; }
.cli-app-tile {
  width: 44px; height: 44px;
  border-radius: 11px;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 16px;
  font-family: var(--font-heading);
  flex-shrink: 0;
}
.cli-app-info { flex: 1; min-width: 0; }
.cli-app-nm { color: #e7ecf2; font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
.cli-app-bridge { font-size: 10px; color: #61c554; border: 1px solid #2f5a36; border-radius: 6px; padding: 0 5px; font-weight: 400; }
.cli-install {
  margin-top: 7px;
  border: 1px solid #3a444f;
  background: #5aa9e6;
  color: #fff;
  font-size: 12px;
  padding: 3px 14px;
  border-radius: 7px;
  cursor: pointer;
  transition: filter 0.12s ease, background 0.12s ease, color 0.12s ease;
}
.cli-install:hover { filter: brightness(1.06); }
.cli-install.installing { background: transparent; color: #f4be4f; border-color: #5a4f2a; cursor: default; }
.cli-install.done { background: transparent; color: #61c554; border-color: #2f5a36; }

/* ── 本地连接（终端 + 右侧快捷操作）── */
.cli-local { flex: 1; min-height: 0; display: flex; }
.cli-term { flex: 1; min-width: 0; display: flex; flex-direction: column; padding: 14px 16px; }
.cli-side {
  width: 232px;
  flex-shrink: 0;
  background: #20262e;
  border-left: 1px solid #2f3742;
  padding: 14px;
  overflow-y: auto;
}
.cli-side-title { color: #8a97a6; font-size: 11px; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 10px; font-family: var(--font-mono); }
.cli-side-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 9px;
  text-align: left;
  border: 1px solid #2f3742;
  background: #232a33;
  color: #d6dee7;
  font-size: 13px;
  padding: 9px 11px;
  border-radius: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}
.cli-side-btn:hover { background: #2b333d; border-color: #5aa9e6; color: #fff; }
.cli-side-dot { width: 7px; height: 7px; border-radius: 50%; background: #5d6976; flex-shrink: 0; }
.cli-side-dot.on { background: #61c554; box-shadow: 0 0 0 3px rgba(97, 197, 84, 0.18); }
.cli-side-hint { color: #6f7d8c; font-size: 11px; line-height: 1.6; margin-top: 12px; }
.cli-log {
  flex: 1; min-height: 0; overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 13px; line-height: 1.7; color: #c9d4e0;
}
.cli-line { white-space: pre-wrap; word-break: break-word; }
.cli-line.in { color: #e7ecf2; }
.cli-line.ok { color: #61c554; }
.cli-line.sys { color: #8a97a6; }
.cli-line.err { color: #ec6a5e; }
.cli-prompt { color: #5aa9e6; margin-right: 8px; font-weight: 700; }
.cli-quick { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 8px; }
.cli-chip {
  font-family: var(--font-mono); font-size: 12px; color: #c9d4e0;
  background: #232a33; border: 1px solid #2f3742; border-radius: 6px;
  padding: 4px 9px; cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}
.cli-chip:hover { background: #2f3742; border-color: #5aa9e6; color: #fff; }
.cli-input-row { display: flex; align-items: center; border-top: 1px solid #2f3742; padding-top: 10px; }
.cli-input { flex: 1; border: none; background: transparent; outline: none; color: #e7ecf2; font-family: var(--font-mono); font-size: 13px; }
.cli-input::placeholder { color: #5d6976; }
</style>
