<template>
  <div v-if="visible" class="mkt-overlay" @click.self="close">
    <div class="mkt-modal" role="dialog" aria-modal="true">
      <div class="mkt-head">
        <div class="mkt-title-wrap">
          <span class="mkt-title">AI Agent 商城</span>
          <span class="mkt-sub">Agent · 技能 · Prompt · 工作流 · 知识库 · 连接器</span>
        </div>
        <div class="mkt-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
          <input v-model="q" placeholder="搜索 Agent / 技能 / Prompt…" />
        </div>
        <button class="mkt-close" title="关闭" @click="close">×</button>
      </div>

      <div class="mkt-cats">
        <button
          v-for="c in cats"
          :key="c.key"
          class="mkt-cat"
          :class="{ active: active === c.key }"
          @click="active = c.key"
        >
          {{ c.label }}
          <span class="mkt-cat-n">{{ countOf(c.key) }}</span>
        </button>
      </div>

      <div class="mkt-body">
        <div v-if="filtered.length" class="mkt-grid">
          <div v-for="it in filtered" :key="it.id" class="mkt-card">
            <div class="mkt-card-top">
              <span class="mkt-badge" :style="{ background: CAT_META[it.cat].color }">{{ CAT_META[it.cat].label }}</span>
              <span v-if="it.tag" class="mkt-tag">{{ it.tag }}</span>
            </div>
            <div class="mkt-name">{{ it.name }}</div>
            <div class="mkt-desc">{{ it.desc }}</div>
            <div class="mkt-foot">
              <span class="mkt-price" :class="{ free: !it.price }">{{ it.price ? '¥' + it.price : '免费' }}</span>
              <button class="mkt-btn" :class="{ on: it.installed }" @click="it.installed = !it.installed">
                {{ it.installed ? '已获取' : (it.price ? '获取' : '免费获取') }}
              </button>
            </div>
            <div class="mkt-meta">{{ it.author }} · ↧ {{ it.installs }}</div>
          </div>
        </div>
        <div v-else class="mkt-empty">没有匹配的内容</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useMarketplace } from '@/composables/useMarketplace'
import { marketItems, CAT_META, type MarketCat } from '@/data/marketplace'

const { visible, close } = useMarketplace()

type CatKey = MarketCat | 'all'
const cats: { key: CatKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'agent', label: 'AI Agent' },
  { key: 'skill', label: 'Skill' },
  { key: 'prompt', label: 'Prompt' },
  { key: 'workflow', label: '工作流' },
  { key: 'knowledge', label: '知识库' },
  { key: 'mcp', label: 'MCP 连接器' }
]
const active = ref<CatKey>('all')
const q = ref('')

/** 可安装状态可切换，故用响应式副本 */
const items = reactive(marketItems.map((i) => ({ ...i })))

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
.mkt-overlay {
  position: fixed;
  inset: 0;
  z-index: 210;
  background: rgba(0, 0, 0, 0.34);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: mkt-fade 0.14s ease;
}
@keyframes mkt-fade { from { opacity: 0 } to { opacity: 1 } }

.mkt-modal {
  width: min(1040px, 94vw);
  height: min(720px, 90vh);
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-radius: 16px;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.24), 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  animation: mkt-pop 0.16s ease;
}
@keyframes mkt-pop { from { opacity: 0; transform: translateY(10px) scale(0.985) } to { opacity: 1; transform: none } }

.mkt-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.mkt-title-wrap { display: flex; flex-direction: column; gap: 2px; flex-shrink: 0; }
.mkt-title { font-family: var(--font-heading); font-weight: var(--fw-bold); font-size: var(--fs-400); color: var(--text); }
.mkt-sub { font-size: var(--fs-75); color: var(--text-3); }
.mkt-search {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 280px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-soft);
  color: var(--text-3);
}
.mkt-search input { flex: 1; border: none; background: transparent; outline: none; font-size: var(--fs-100); color: var(--text); }
.mkt-search input::placeholder { color: var(--text-3); }
.mkt-close {
  width: 30px; height: 30px;
  border: none; background: transparent;
  font-size: 22px; line-height: 1;
  color: var(--text-3); cursor: pointer;
  border-radius: 6px;
  transition: background 0.12s ease, color 0.12s ease;
}
.mkt-close:hover { background: var(--bg-hover); color: var(--text); }

.mkt-cats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
}
.mkt-cat {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  cursor: pointer;
  font-size: var(--fs-75);
  color: var(--text-2);
  transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}
.mkt-cat:hover { background: var(--bg-soft); }
.mkt-cat.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.mkt-cat-n { font-family: var(--mono); font-size: 10px; opacity: 0.7; }

.mkt-body { flex: 1; min-height: 0; overflow-y: auto; padding: 18px 20px 22px; }
.mkt-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}
.mkt-card {
  display: flex;
  flex-direction: column;
  gap: 7px;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
  background: var(--bg-panel);
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}
.mkt-card:hover { border-color: var(--text-dim); box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06); }
.mkt-card-top { display: flex; align-items: center; gap: 8px; }
.mkt-badge { font-size: 10px; color: #fff; padding: 2px 8px; border-radius: 999px; font-weight: var(--fw-bold); }
.mkt-tag { font-family: var(--mono); font-size: 11px; color: var(--accent); background: var(--accent-soft); padding: 1px 6px; border-radius: 4px; }
.mkt-name { font-family: var(--font-heading); font-weight: var(--fw-bold); font-size: var(--fs-200); color: var(--text); }
.mkt-desc { font-size: var(--fs-75); color: var(--text-3); line-height: 1.5; flex: 1; }
.mkt-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 4px; }
.mkt-price { font-family: var(--font-heading); font-weight: var(--fw-bold); font-size: var(--fs-200); color: var(--accent); }
.mkt-price.free { color: var(--ok); }
.mkt-meta { font-size: var(--fs-50); color: var(--text-3); font-family: var(--font-mono); margin-top: 6px; }
.mkt-btn {
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #fff;
  font-size: var(--fs-75);
  font-weight: var(--fw-bold);
  padding: 4px 14px;
  border-radius: 8px;
  cursor: pointer;
  transition: filter 0.12s ease, background 0.12s ease, color 0.12s ease;
}
.mkt-btn:hover { filter: brightness(1.05); }
.mkt-btn.on { background: transparent; color: var(--text-3); border-color: var(--border); }

.mkt-empty { text-align: center; color: var(--text-3); padding: 60px 0; font-size: var(--fs-100); }
</style>
