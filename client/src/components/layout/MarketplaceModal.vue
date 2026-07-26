<template>
  <div v-if="visible" class="mkt-overlay" @click.self="close">
    <div class="mkt-modal" role="dialog" aria-modal="true">
      <div class="mkt-head">
        <!-- 从工坊等入口带回调打开时显示返回(负责人报:跳过来后回不去) -->
        <button v-if="hasBack" class="mkt-back" title="返回" @click="goBack">←</button>
        <div class="mkt-title-wrap">
          <span class="mkt-title">AI Agent 商城</span>
          <span class="mkt-sub">AI 同事 · 技能 · 工作流 · 知识库，平台真实资源、获取即用</span>
        </div>
        <div class="mkt-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
          <input v-model="q" placeholder="搜索 AI 同事 / 技能…" />
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
        <!-- 获取失败（如达上限）的醒目警告条：橙红底 + ⚠️，一眼看到「点了为何没获取」（负责人实报）-->
        <div v-if="errMsg" class="mkt-err">
          <span class="mkt-err-ic">⚠️</span>
          <span class="mkt-err-t">{{ errMsg }}</span>
          <button class="mkt-err-x" title="知道了" @click="errMsg = ''">×</button>
        </div>
        <!-- 使用指引条：点「获取/已获取」后告诉用户这东西在聊天里怎么用 -->
        <div v-if="hint" class="mkt-hint">💡 {{ hint }}</div>

        <div v-if="loading" class="mkt-empty">正在加载平台资源…</div>
        <div v-else-if="loadError" class="mkt-empty">
          加载失败，请检查网络后
          <a class="mkt-retry" @click="load">重试</a>
        </div>
        <div v-else-if="filtered.length" class="mkt-grid">
          <div v-for="it in filtered" :key="itemId(it)" class="mkt-card">
            <div class="mkt-card-top">
              <span class="mkt-badge" :style="{ background: CAT_META[it.kind].color }">{{ CAT_META[it.kind].label }}</span>
              <span v-if="it.division" class="mkt-tag">{{ it.division }}</span>
              <span v-else-if="it.kind === 'workflow' && it.platform" class="mkt-tag">{{ it.platform }}</span>
            </div>
            <div class="mkt-name">{{ it.name }}</div>
            <div class="mkt-desc">{{ it.description || descFallback(it) }}</div>
            <div class="mkt-foot">
              <span class="mkt-price" :class="badgeOf(it).cls">{{ badgeOf(it).label }}</span>
              <!-- 三态：可用→获取/已获取；等级不够→升级解锁(弹会员)；模板/管理员专属→只标注不可点 -->
              <button
                v-if="it.unlocked"
                class="mkt-btn"
                :class="{ on: isAcquired(it) }"
                @click="acquire(it)"
              >{{ isAcquired(it) ? '已获取' : '免费获取' }}</button>
              <button
                v-else-if="badgeOf(it).cls === 'tier'"
                class="mkt-btn upgrade"
                @click="emit('upgrade')"
              >升级解锁</button>
              <button v-else class="mkt-btn locked" disabled>专属资源</button>
            </div>
            <div class="mkt-meta">
              <template v-if="it.kind === 'cagent'">创作者 {{ shortUser(it.creator || '') }}<template v-if="it.uses">· 已被使用 {{ it.uses }} 次</template></template>
              <template v-else>{{ it.official ? 'GuDuu OS 官方' : '平台运营' }}</template>
              <template v-if="it.kind === 'agent' && it.skill_count">· 内置 {{ it.skill_count }} 项技能</template>
              <template v-if="it.kind === 'skill' && it.agents?.length">· 随【{{ it.agents.join('/') }}】激活</template>
            </div>
          </div>
        </div>
        <div v-else class="mkt-empty">没有匹配的内容</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMarketplace } from '@/composables/useMarketplace'
import { CAT_META, accessBadge, type MarketCat } from '@/data/marketplace'
import {
  fetchMarketCatalog,
  migrateLegacyAcquired,
  setMarketItemAcquired,
  type MarketCatalogItem,
} from '@/matrix/client'

const emit = defineEmits<{ (e: 'upgrade'): void }>()
const { visible, close, hasBack, goBack } = useMarketplace()

type CatKey = MarketCat | 'all'
const cats: { key: CatKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'agent', label: 'AI 同事' },
  { key: 'cagent', label: '创作者 Agent' },
  { key: 'skill', label: '技能' },
  { key: 'workflow', label: '工作流' },
  { key: 'knowledge', label: '知识库' }
]
const active = ref<CatKey>('all')
const q = ref('')

/* —— 真数据：打开弹窗时从 bot 拉平台资源目录（含按本人算好的 解锁/已获取 状态）—— */
const items = ref<MarketCatalogItem[]>([])
const loading = ref(false)
const loadError = ref(false)
const hint = ref('')
const errMsg = ref('')   // 获取失败(如达上限)的醒目警告，与 💡 使用指引分开展示

const itemId = (it: MarketCatalogItem) => `${it.kind}:${it.slug}`
const isAcquired = (it: MarketCatalogItem) => it.acquired
/** 徽标：创作者 Agent 标**按次价**（获取免费、用的时候扣 token）；其余按 access 等级标。 */
const badgeOf = (it: MarketCatalogItem) => {
  if (it.kind === 'cagent') {
    const p = Number(it.price_tokens || 0)
    return p > 0
      ? { label: `${p.toLocaleString()} token/次`, cls: 'tier' as const }
      : { label: '免费用', cls: 'free' as const }
  }
  return accessBadge(it.access)
}

async function load() {
  loading.value = true
  loadError.value = false
  await migrateLegacyAcquired() // 旧版 account data 里的获取记录搬进服务端(幂等,一次性)
  const cat = await fetchMarketCatalog()
  loading.value = false
  if (!cat) { loadError.value = true; return }
  items.value = cat.items
}
// 每次打开都回到干净状态(负责人报:再次进商城还留着上次的搜索词)——
// q/active/hint 都是模块级单例(弹窗常驻不销毁),不显式重置就会带着上次的筛选进来。
watch(visible, (v) => {
  if (!v) return
  q.value = ''
  active.value = 'all'
  hint.value = ''
  errMsg.value = ''
  load()
})

/** 「获取」：记入服务端(cosmac DB)——主 AI 名册立刻优先这些同事，我的AI工坊也能看到；
 *  随后给出在聊天里怎么用的指引。已获取的再点只重放指引。 */
async function acquire(it: MarketCatalogItem) {
  if (!it.acquired) {
    const err = await setMarketItemAcquired(it.kind, it.slug, true)
    // 失败(如达上限)走**醒目警告条**而非不起眼的 💡 提示条——负责人实报:达上限时提醒不够明显,
    // 用户以为点了没反应。errMsg 用橙红警告样式,并把 💡 提示清掉免得两条混淆。
    if (err) { errMsg.value = err; hint.value = ''; return }
    it.acquired = true
  }
  errMsg.value = ''
  hint.value = usageHint(it)
}

/** 各类资源的使用指引（获取后展示；这些资源都在聊天里用，无需额外安装）。 */
function usageHint(it: MarketCatalogItem): string {
  if (it.kind === 'cagent') {
    const p = Number(it.price_tokens || 0)
    const cost = p > 0 ? `每次使用扣 ${p.toLocaleString()} token（余额不足会提示充值）` : '免费使用'
    return `已获取「${it.name}」：在频道里 @${it.name} 即由它应答；${cost}。可在「我的AI工坊 · 已获取」管理。`
  }
  if (it.kind === 'agent') return `已获取「${it.name}」：在频道里 @${it.name}；主 AI 派单会优先考虑你获取的同事。可在「我的AI工坊 · 已获取」管理。`
  if (it.kind === 'skill') {
    if (it.agents?.length) return `已获取「${it.name}」：随 AI 同事【${it.agents.join('/')}】自动激活，@ 它们即可。`
    return it.inject === 'agent'
      ? `已获取「${it.name}」：绑定到智能体后随其激活（后台或我的AI工坊可绑）。`
      : `已获取「${it.name}」：已全局生效，直接和 AI 对话即可。`
  }
  if (it.kind === 'workflow') return `已获取「${it.name}」：对主 AI 说「工作流 跑 ${it.slug}」，或直接描述需求让它自动调用。${it.input_hint ? `输入提示：${it.input_hint}` : ''}`
  return `已获取「${it.name}」：向 AI 提问相关内容时会自动检索这篇知识。`
}

/** 创作者账号展示：@carol:xx.com → carol（卡片上短一点，完整 ID 无需暴露域名噪音）。 */
function shortUser(uid: string): string {
  const m = /^@([^:]+):/.exec(uid || '')
  return m ? m[1] : (uid || '')
}

/** 后端没填描述时的兜底文案（知识库文档只有标题）。 */
function descFallback(it: MarketCatalogItem): string {
  if (it.kind === 'knowledge') return '平台共享知识库文档，问 AI 时自动检索引用'
  if (it.kind === 'workflow') return '平台预置的自动化工作流，可让主 AI 直接调用'
  return ''
}

const filtered = computed(() =>
  items.value.filter((i) => {
    if (active.value !== 'all' && i.kind !== active.value) return false
    const k = q.value.trim()
    if (k && !(i.name.includes(k) || i.description.includes(k))) return false
    return true
  })
)
function countOf(key: CatKey) {
  return key === 'all' ? items.value.length : items.value.filter((i) => i.kind === key).length
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
.mkt-back { width: 30px; height: 30px; border: 1px solid var(--border); background: transparent; font-size: 16px; color: var(--text-2); cursor: pointer; border-radius: 8px; flex-shrink: 0; }
.mkt-back:hover { background: var(--bg-hover); color: var(--text); }
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
.mkt-price.tier { color: var(--accent); }
.mkt-price.scoped { color: var(--text-3); font-size: var(--fs-100); }
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
.mkt-btn.upgrade { background: #b58932; border-color: #b58932; }
.mkt-btn.locked { background: transparent; color: var(--text-3); border-color: var(--border); cursor: default; }

/* 获取失败的醒目警告条:橙红底、加粗、左侧竖条 + ⚠️,和普通 💡 提示明显区分(负责人实报不够醒目) */
.mkt-err {
  display: flex; align-items: flex-start; gap: 8px;
  margin-bottom: 14px; padding: 11px 14px;
  border: 1px solid #e8b04b; border-left: 4px solid #d98a1e;
  border-radius: 10px;
  background: #fdf2df; color: #8a5a12;
  font-size: var(--fs-100); font-weight: var(--fw-bold);
}
:root[data-theme="dark"] .mkt-err { background: #3a2c12; color: #f0c674; border-color: #6b5220; }
.mkt-err-ic { flex-shrink: 0; line-height: 1.4; }
.mkt-err-t { flex: 1; line-height: 1.5; }
.mkt-err-x { flex-shrink: 0; border: none; background: transparent; color: inherit; font-size: 18px; line-height: 1; cursor: pointer; opacity: .6; padding: 0 2px; }
.mkt-err-x:hover { opacity: 1; }

.mkt-hint {
  margin-bottom: 14px;
  padding: 10px 14px;
  border: 1px solid var(--accent-soft, var(--border));
  border-radius: 10px;
  background: var(--accent-soft, var(--bg-soft));
  color: var(--text);
  font-size: var(--fs-75);
  line-height: 1.6;
}
.mkt-retry { color: var(--accent); cursor: pointer; text-decoration: underline; }

.mkt-empty { text-align: center; color: var(--text-3); padding: 60px 0; font-size: var(--fs-100); }
</style>
