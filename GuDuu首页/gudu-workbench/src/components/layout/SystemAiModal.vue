<template>
  <div v-if="visible" class="cam-overlay" @click.self="close">
    <div class="cam-modal" role="dialog" aria-modal="true">
      <div class="cam-head">
        <span class="cam-title">系统 AI 设置</span>
        <span class="cam-sub">主 AI · 总控大脑全局配置</span>
        <button class="cam-close" title="关闭" @click="close">×</button>
      </div>

      <div class="cam-tabs">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="cam-tab"
          :class="{ active: tab === t.key }"
          @click="tab = t.key"
        >
          {{ t.label }}
          <span v-if="t.countKey" class="cam-count">{{ countOf(t.countKey) }}</span>
        </button>
      </div>

      <div class="cam-body">
        <!-- 人格 -->
        <template v-if="tab === 'persona'">
          <div class="cam-field">
            <label class="cam-field-label">AI 名称</label>
            <input v-model="state.persona.aiName" class="cam-input" placeholder="如 GuDuu 系统 AI" />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">语气 / 风格</label>
            <input v-model="state.persona.tone" class="cam-input" placeholder="如 统筹 · 稳健 · 可追溯" />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">人格设定 / System Prompt</label>
            <textarea v-model="state.persona.prompt" class="cam-textarea" rows="5" placeholder="定义主 AI 的身份、统筹职责与边界…" />
            <div class="cam-help">主 AI 统筹各部门子智能体，这段提示词决定其总控行为与口吻。</div>
          </div>
        </template>

        <!-- 技能 -->
        <template v-else-if="tab === 'skills'">
          <div v-for="(s, i) in state.skills" :key="'s' + i" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">{{ s.label }}<span v-if="s.tag" class="cam-tag">{{ s.tag }}</span></div>
              <div v-if="s.desc" class="cam-row-desc">{{ s.desc }}</div>
            </div>
            <button class="cam-del" title="移除" @click="removeItem('skills', i)">×</button>
          </div>
          <div class="cam-add">
            <input v-model="sLabel" class="cam-input" placeholder="技能名称" @keyup.enter="doAddSkill" />
            <input v-model="sTag" class="cam-input cam-input-sm" placeholder="/命令（可选）" @keyup.enter="doAddSkill" />
            <input v-model="sDesc" class="cam-input" placeholder="说明（可选）" @keyup.enter="doAddSkill" />
            <button class="cam-add-btn" :disabled="!sLabel.trim()" @click="doAddSkill">＋ 添加技能</button>
          </div>
        </template>

        <!-- 知识库 -->
        <template v-else-if="tab === 'knowledge'">
          <div v-for="(k, i) in state.knowledge" :key="'k' + i" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">{{ k.label }}</div>
              <div v-if="k.desc" class="cam-row-desc">{{ k.desc }}</div>
            </div>
            <button class="cam-del" title="移除" @click="removeItem('knowledge', i)">×</button>
          </div>
          <div class="cam-add">
            <input v-model="kLabel" class="cam-input" placeholder="知识库名称" @keyup.enter="doAddKnowledge" />
            <input v-model="kDesc" class="cam-input" placeholder="说明（如 1,240 篇）" @keyup.enter="doAddKnowledge" />
            <button class="cam-add-btn" :disabled="!kLabel.trim()" @click="doAddKnowledge">＋ 添加来源</button>
          </div>
        </template>

        <!-- 子智能体 -->
        <template v-else-if="tab === 'subAgents'">
          <div class="cam-help cam-help-top">主 AI 统筹的部门子智能体——请求会按部门路由到对应的群级 AI。</div>
          <div v-for="(a, i) in state.subAgents" :key="'a' + i" class="cam-row">
            <div class="cam-ava bot">{{ [...a.label][0] }}</div>
            <div class="cam-row-main">
              <div class="cam-row-label">{{ a.label }}</div>
              <div v-if="a.desc" class="cam-row-desc">{{ a.desc }}</div>
            </div>
            <button class="cam-del" title="移除" @click="removeItem('subAgents', i)">×</button>
          </div>
          <div class="cam-add">
            <input v-model="aLabel" class="cam-input" placeholder="子智能体名称（如 物流大脑）" @keyup.enter="doAddAgent" />
            <input v-model="aDesc" class="cam-input" placeholder="归属 / 状态（如 物流部 · 在线）" @keyup.enter="doAddAgent" />
            <button class="cam-add-btn" :disabled="!aLabel.trim()" @click="doAddAgent">＋ 添加子智能体</button>
          </div>
        </template>

        <!-- 数据接入 -->
        <template v-else-if="tab === 'dataSources'">
          <div class="cam-help cam-help-top">主 AI 对接的全公司系统及其密级 / 访问级。</div>
          <div v-for="(d, i) in state.dataSources" :key="'d' + i" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">
                {{ d.label }}
                <span class="cam-level" :class="'lv-' + d.level">{{ d.level }}</span>
              </div>
            </div>
            <select v-model="d.access" class="cam-select cam-select-sm" :class="{ off: d.access === '禁用' }">
              <option v-for="ac in accessOptions" :key="ac" :value="ac">{{ ac }}</option>
            </select>
            <button class="cam-del" title="移除" @click="removeSource(i)">×</button>
          </div>
          <div class="cam-add">
            <input v-model="dLabel" class="cam-input" placeholder="系统 / 数据源名称" @keyup.enter="doAddSource" />
            <select v-model="dLevel" class="cam-select cam-select-sm">
              <option v-for="l in levelOptions" :key="l" :value="l">{{ l }}</option>
            </select>
            <select v-model="dAccess" class="cam-select cam-select-sm">
              <option v-for="ac in accessOptions" :key="ac" :value="ac">{{ ac }}</option>
            </select>
            <button class="cam-add-btn" :disabled="!dLabel.trim()" @click="doAddSource">＋ 添加</button>
          </div>
        </template>

        <!-- 模型 & 配额 -->
        <template v-else-if="tab === 'model'">
          <div class="cam-field">
            <label class="cam-field-label">默认模型</label>
            <select v-model="state.model.model" class="cam-select">
              <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
          <div class="cam-field">
            <label class="cam-field-label">月度 Token 预算（万）</label>
            <input v-model.number="state.model.tokenBudget" type="number" min="0" class="cam-input" />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">速率限制（次 / 分）</label>
            <input v-model.number="state.model.rateLimit" type="number" min="0" class="cam-input" />
          </div>
          <div class="cam-help">主 AI 的总额度，会向各部门子智能体按需分配。</div>
        </template>

        <!-- 记忆 & 审计 -->
        <template v-else>
          <div class="cam-field cam-field-row">
            <label class="cam-field-label">长期记忆</label>
            <button class="cam-switch" :class="{ on: state.memory.longTerm }" @click="state.memory.longTerm = !state.memory.longTerm">
              <span class="cam-switch-dot" />
            </button>
          </div>
          <div class="cam-field">
            <label class="cam-field-label">上下文范围</label>
            <select v-model="state.memory.scope" class="cam-select">
              <option v-for="s in scopeOptions" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <div class="cam-field">
            <label class="cam-field-label">数据留存（天）</label>
            <input v-model.number="state.memory.retentionDays" type="number" min="0" class="cam-input" />
          </div>
          <div class="cam-field cam-field-row">
            <label class="cam-field-label">审计日志</label>
            <button class="cam-switch" :class="{ on: state.memory.audit }" @click="state.memory.audit = !state.memory.audit">
              <span class="cam-switch-dot" />
            </button>
          </div>
          <div class="cam-help">主 AI 的全局记忆与审计；跨部门访问与动作全程留痕，便于追溯。</div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  useSystemAi,
  MODEL_OPTIONS,
  type Confidential,
  type AccessLevel
} from '@/composables/useSystemAi'

type TabKey = 'persona' | 'skills' | 'knowledge' | 'subAgents' | 'dataSources' | 'model' | 'memory'
type CountKey = 'skills' | 'knowledge' | 'subAgents' | 'dataSources'

const { visible, state, close, addItem, removeItem, addSource, removeSource } = useSystemAi()

const tabs: { key: TabKey; label: string; countKey?: CountKey }[] = [
  { key: 'persona', label: '人格' },
  { key: 'skills', label: '技能', countKey: 'skills' },
  { key: 'knowledge', label: '知识库', countKey: 'knowledge' },
  { key: 'subAgents', label: '子智能体', countKey: 'subAgents' },
  { key: 'dataSources', label: '数据接入', countKey: 'dataSources' },
  { key: 'model', label: '模型' },
  { key: 'memory', label: '记忆审计' }
]
const tab = ref<TabKey>('persona')

function countOf(k?: CountKey) { return k ? state[k].length : 0 }

const modelOptions = MODEL_OPTIONS
const levelOptions: Confidential[] = ['公开', '内部', '机密']
const accessOptions: AccessLevel[] = ['禁用', '只读', '读写']
const scopeOptions = ['仅本群', '本部门', '全公司']

const sLabel = ref(''); const sTag = ref(''); const sDesc = ref('')
const kLabel = ref(''); const kDesc = ref('')
const aLabel = ref(''); const aDesc = ref('')
const dLabel = ref(''); const dLevel = ref<Confidential>('内部'); const dAccess = ref<AccessLevel>('只读')

function doAddSkill() { addItem('skills', sLabel.value, sDesc.value, sTag.value); sLabel.value = ''; sTag.value = ''; sDesc.value = '' }
function doAddKnowledge() { addItem('knowledge', kLabel.value, kDesc.value); kLabel.value = ''; kDesc.value = '' }
function doAddAgent() { addItem('subAgents', aLabel.value, aDesc.value); aLabel.value = ''; aDesc.value = '' }
function doAddSource() { addSource(dLabel.value, dLevel.value, dAccess.value); dLabel.value = '' }

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value) close()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<!-- 弹窗样式见全局 src/styles/admin-modal.css（与频道管理弹窗共用 .cam-*）-->
