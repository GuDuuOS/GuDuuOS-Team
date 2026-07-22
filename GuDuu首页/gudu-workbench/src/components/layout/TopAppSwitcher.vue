<template>
  <div ref="root" class="tas-wrap">
    <!-- 品牌按键：九宫格 + logo + 产品名 -->
    <button class="top-brand-btn" :class="{ open }" :title="`GuDuu OS · ${brandName}`" @click="open = !open">
      <svg class="apps-ic" width="18" height="18" viewBox="0 0 18 18" fill="currentColor" aria-hidden="true">
        <circle cx="3" cy="3" r="1.6" /><circle cx="9" cy="3" r="1.6" /><circle cx="15" cy="3" r="1.6" />
        <circle cx="3" cy="9" r="1.6" /><circle cx="9" cy="9" r="1.6" /><circle cx="15" cy="9" r="1.6" />
        <circle cx="3" cy="15" r="1.6" /><circle cx="9" cy="15" r="1.6" /><circle cx="15" cy="15" r="1.6" />
      </svg>
      <img :src="logoUrl" alt="GuDuu" class="logo" />
      <span class="product-name">
        GuDuu OS<span class="product-x">X</span>{{ brandName }}
      </span>
    </button>

    <div v-if="open" class="tas-pop" @click.stop>
      <button class="tas-item active" @click="open = false">
        <span class="tas-ic accent">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z" /><path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1" /></svg>
        </span>
        <span class="tas-label">Channels</span>
        <svg class="tas-check" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
      </button>

      <div class="tas-sep" />

      <button class="tas-item" @click="goDataIntelligence">
        <span class="tas-ic di">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="8" ry="3" />
            <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
            <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
          </svg>
        </span>
        <span class="tas-label">GuDuu DI</span>
      </button>
      <button class="tas-item" @click="goMarket">
        <span class="tas-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z" /><path d="M3 6h18" /><path d="M16 10a4 4 0 0 1-8 0" /></svg>
        </span>
        <span class="tas-label">AI Agent 商城</span>
      </button>
      <button class="tas-item" @click="goCli">
        <span class="tas-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5" /><line x1="12" x2="20" y1="19" y2="19" /></svg>
        </span>
        <span class="tas-label">CLI</span>
      </button>
      <button class="tas-item" @click="open = false">
        <span class="tas-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="3" rx="2" /><line x1="8" x2="16" y1="21" y2="21" /><line x1="12" x2="12" y1="17" y2="21" /></svg>
        </span>
        <span class="tas-label">系统控制台</span>
      </button>
      <button class="tas-item" @click="open = false">
        <span class="tas-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22v-5" /><path d="M9 8V2" /><path d="M15 8V2" /><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z" /></svg>
        </span>
        <span class="tas-label">集成</span>
      </button>

      <div class="tas-sep" />

      <button class="tas-item" @click="goProfile">
        <span class="tas-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg>
        </span>
        <span class="tas-label">个人主页</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import logoUrl from '@/assets/gudu-logo.svg'
import { useMarketplace } from '@/composables/useMarketplace'
import { useCli } from '@/composables/useCli'
import { useProfileHome } from '@/composables/useProfileHome'
import { workspaceDataMap } from '@/data/channels'

/** 企业品牌名（搭建向导未选定行业前为「我的企业」）*/
const brandName = computed(() => workspaceDataMap.hq.name)

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const { open: openMarket } = useMarketplace()
const { open: openCli } = useCli()
const { open: openProfile } = useProfileHome()
const router = useRouter()

function goDataIntelligence() {
  open.value = false
  router.push({ name: 'data-canvas' })
}

function goMarket() {
  open.value = false
  openMarket()
}
function goCli() {
  open.value = false
  openCli()
}
function goProfile() {
  open.value = false
  openProfile()
}

function onDocClick(e: MouseEvent) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
.tas-wrap { position: relative; display: inline-flex; }

.tas-pop {
  position: absolute;
  top: calc(100% + 6px);
  left: 6px;
  z-index: 60;
  min-width: 240px;
  padding: 8px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.14), 0 1px 3px rgba(0, 0, 0, 0.08);
  animation: tas-in 0.12s ease;
}
@keyframes tas-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }

.tas-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 10px;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  font-size: var(--fs-200);
  color: var(--text);
  transition: background 0.1s ease;
}
.tas-item:hover { background: var(--bg-soft); }
.tas-ic { color: var(--text-3); display: inline-flex; flex-shrink: 0; }
.tas-ic.accent { color: var(--accent); }
.tas-ic.di { color: #e88533; }
.tas-label { flex: 1; }
.tas-item.active .tas-label { font-weight: var(--fw-bold); }
.tas-check { color: var(--accent); flex-shrink: 0; }
.tas-sep { height: 1px; background: var(--border-soft); margin: 6px 4px; }
</style>
