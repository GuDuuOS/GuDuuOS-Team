<template>
  <div v-if="visible" class="ps-overlay" @click.self="close">
    <div class="ps-modal" role="dialog" aria-modal="true">
      <div class="ps-head">
        <div class="ps-title-wrap">
          <span class="ps-title">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2H2v10h10V2Z" /><path d="M22 12h-10v10h10V12Z" /><path d="M12 12H2v10h10V12Z" /><path d="M22 2h-10v10h10V2Z" /></svg>
            插件商城
          </span>
          <span class="ps-sub">停靠在右侧插件栏的工具 / 应用 · 获取即用</span>
        </div>
        <div class="ps-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
          <input v-model="q" placeholder="搜索插件…" />
        </div>
        <button class="ps-close" title="关闭" @click="close">×</button>
      </div>

      <div class="ps-cats">
        <button
          v-for="c in cats"
          :key="c.key"
          class="ps-cat"
          :class="{ active: active === c.key }"
          @click="active = c.key"
        >
          {{ c.label }}
          <span class="ps-cat-n">{{ countOf(c.key) }}</span>
        </button>
      </div>

      <div class="ps-body">
        <div v-if="filtered.length" class="ps-grid">
          <div v-for="it in filtered" :key="it.id" class="ps-card">
            <div class="ps-card-top">
              <span class="ps-tile" :style="{ background: it.color }">{{ it.icon }}</span>
              <div class="ps-card-id">
                <div class="ps-name">
                  {{ it.name }}
                  <span v-if="it.tag" class="ps-flag">{{ it.tag }}</span>
                </div>
                <span class="ps-badge" :style="{ color: catColor(it.cat) }">{{ catLabel(it.cat) }}</span>
              </div>
            </div>
            <div class="ps-desc">{{ it.desc }}</div>
            <div class="ps-foot">
              <span class="ps-price" :class="{ free: !it.price }">{{ it.price ? '¥' + it.price : '免费' }}</span>
              <button
                class="ps-btn"
                :class="{ on: it.installed, locked: !!it.builtinPluginId }"
                @click="toggle(it)"
              >
                {{ it.builtinPluginId ? '已内置' : it.installed ? '卸载' : (it.price ? '获取' : '免费获取') }}
              </button>
            </div>
            <div class="ps-meta">{{ it.author }} · ↧ {{ it.installs }}</div>
          </div>
        </div>
        <div v-else class="ps-empty">没有匹配的插件</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { usePluginStore } from '@/composables/usePluginStore'
import { PLUGIN_CAT_META, type PluginCat } from '@/data/pluginStore'

const { visible, items, close, toggle } = usePluginStore()

type CatKey = PluginCat | 'all'
const cats: { key: CatKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'ai', label: 'AI 工具' },
  { key: 'monitor', label: '监控' },
  { key: 'board', label: '看板' },
  { key: 'collab', label: '协作' },
  { key: 'flow', label: '流程' }
]
const active = ref<CatKey>('all')
const q = ref('')

const catLabel = (c: PluginCat) => PLUGIN_CAT_META[c].label
const catColor = (c: PluginCat) => PLUGIN_CAT_META[c].color

const filtered = computed(() =>
  items.filter((i) => {
    if (active.value !== 'all' && i.cat !== active.value) return false
    const k = q.value.trim()
    if (k && !(i.name.includes(k) || i.desc.includes(k))) return false
    return true
  })
)
function countOf(key: CatKey) {
  return key === 'all' ? items.length : items.filter((i) => i.cat === key).length
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value) close()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<style scoped>
.ps-overlay {
  position: fixed;
  inset: 0;
  z-index: 212;
  background: rgba(0, 0, 0, 0.34);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: ps-fade 0.14s ease;
}
@keyframes ps-fade { from { opacity: 0 } to { opacity: 1 } }

.ps-modal {
  width: min(960px, 94vw);
  height: min(680px, 90vh);
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-radius: 16px;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.24), 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  animation: ps-pop 0.16s ease;
}
@keyframes ps-pop { from { opacity: 0; transform: translateY(10px) scale(0.985) } to { opacity: 1; transform: none } }

.ps-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.ps-title-wrap { display: flex; flex-direction: column; gap: 2px; flex-shrink: 0; }
.ps-title {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--font-heading); font-weight: var(--fw-bold);
  font-size: var(--fs-400); color: var(--text);
}
.ps-title svg { color: #5b6fb8; }
.ps-sub { font-size: var(--fs-75); color: var(--text-3); }
.ps-search {
  margin-left: auto;
  display: flex; align-items: center; gap: 8px;
  width: 240px; height: 36px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg-soft); color: var(--text-3);
}
.ps-search input { flex: 1; border: none; background: transparent; outline: none; font-size: var(--fs-100); color: var(--text); }
.ps-search input::placeholder { color: var(--text-3); }
.ps-close {
  width: 30px; height: 30px;
  border: none; background: transparent;
  font-size: 22px; line-height: 1; color: var(--text-3); cursor: pointer;
  border-radius: 6px; transition: background 0.12s ease, color 0.12s ease;
}
.ps-close:hover { background: var(--bg-hover); color: var(--text); }

.ps-cats {
  display: flex; flex-wrap: wrap; gap: 8px;
  padding: 12px 20px; border-bottom: 1px solid var(--border);
}
.ps-cat {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; border: 1px solid var(--border); border-radius: 999px;
  background: transparent; cursor: pointer;
  font-size: var(--fs-75); color: var(--text-2);
  transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}
.ps-cat:hover { background: var(--bg-soft); }
.ps-cat.active { background: #5b6fb8; border-color: #5b6fb8; color: #fff; }
.ps-cat-n { font-family: var(--mono); font-size: 10px; opacity: 0.7; }

.ps-body { flex: 1; min-height: 0; overflow-y: auto; padding: 18px 20px 22px; }
.ps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.ps-card {
  display: flex; flex-direction: column; gap: 9px;
  border: 1px solid var(--border); border-radius: 12px;
  padding: 14px; background: var(--bg-panel);
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}
.ps-card:hover { border-color: var(--text-dim); box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06); }
.ps-card-top { display: flex; align-items: center; gap: 11px; }
.ps-tile {
  width: 40px; height: 40px; border-radius: 10px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: var(--fw-bold); font-size: 14px;
  font-family: var(--font-heading); letter-spacing: -0.5px;
}
.ps-card-id { min-width: 0; }
.ps-name {
  font-family: var(--font-heading); font-weight: var(--fw-bold);
  font-size: var(--fs-200); color: var(--text);
  display: flex; align-items: center; gap: 6px;
}
.ps-flag { font-size: 10px; color: #5b6fb8; background: #eef0fb; border-radius: 5px; padding: 1px 6px; font-weight: var(--fw-regular); }
.ps-badge { font-size: var(--fs-50); font-weight: var(--fw-bold); }
.ps-desc { font-size: var(--fs-75); color: var(--text-3); line-height: 1.5; flex: 1; }
.ps-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 2px; }
.ps-price { font-family: var(--font-heading); font-weight: var(--fw-bold); font-size: var(--fs-200); color: #5b6fb8; }
.ps-price.free { color: var(--ok); }
.ps-meta { font-size: var(--fs-50); color: var(--text-3); font-family: var(--font-mono); }
.ps-btn {
  border: 1px solid #5b6fb8; background: #5b6fb8; color: #fff;
  font-size: var(--fs-75); font-weight: var(--fw-bold);
  padding: 4px 14px; border-radius: 8px; cursor: pointer;
  transition: filter 0.12s ease, background 0.12s ease, color 0.12s ease;
}
.ps-btn:hover { filter: brightness(1.06); }
.ps-btn.on { background: transparent; color: var(--text-3); border-color: var(--border); }
.ps-btn.locked { background: transparent; color: var(--ok); border-color: #cdebd6; cursor: default; }
.ps-btn.locked:hover { filter: none; }

.ps-empty { text-align: center; color: var(--text-3); padding: 60px 0; font-size: var(--fs-100); }
</style>
