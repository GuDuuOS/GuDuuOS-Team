<template>
  <div v-if="visible" class="cam-overlay" @click.self="close">
    <div class="cam-modal" role="dialog" aria-modal="true">
      <div class="cam-head">
        <span class="cam-title">频道管理</span>
        <span class="cam-sub">{{ groupName }} · 群级 AI 隔离配置</span>
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
        <!-- 角色设定 -->
        <template v-if="tab === 'persona'">
          <div class="cam-field">
            <label class="cam-field-label">AI 名称</label>
            <input v-model="state.persona.aiName" class="cam-input" placeholder="如 GuDuu" />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">语气 / 风格</label>
            <input v-model="state.persona.tone" class="cam-input" placeholder="如 严谨 · 数据优先" />
          </div>
          <div class="cam-field">
            <label class="cam-field-label">角色设定 / System Prompt</label>
            <textarea v-model="state.persona.prompt" class="cam-textarea" rows="5" placeholder="定义该群 AI 的身份、职责与边界…" />
            <div class="cam-help">这段提示词决定本群 AI 的行为与口吻，是行为隔离的核心。</div>
          </div>
        </template>

        <!-- 人员 -->
        <template v-else-if="tab === 'members'">
          <div v-for="(m, i) in state.members" :key="'m' + i" class="cam-member">
            <div class="cam-row" :class="{ clickable: m.data.length }" @click="m.data.length && toggleExpand(i)">
              <div class="cam-ava" :class="{ bot: m.bot }" :data-avatar="m.avatar" :style="m.color ? `background:${m.color}` : undefined">{{ m.avatar }}</div>
              <div class="cam-row-main">
                <div class="cam-row-label">{{ m.name }}</div>
                <div class="cam-row-desc">{{ m.role }}<template v-if="m.data.length"> · 可调取 {{ pickedCount(m) }}/{{ m.data.length }}</template></div>
              </div>
              <span
                v-if="m.data.length"
                class="cam-expand"
                :class="{ open: expanded[i] }"
                :title="expanded[i] ? '收起' : '展开设置可调取数据'"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
              </span>
              <button class="cam-del" title="移除" @click.stop="removeMember(i)">×</button>
            </div>
            <div v-if="expanded[i] && m.data.length" class="cam-data">
              <div class="cam-data-tip">勾选该成员可被「{{ groupName }}」调取的数据</div>
              <label v-for="d in m.data" :key="d.label" class="cam-data-item" :class="{ off: !d.selected }">
                <input type="checkbox" v-model="d.selected" />
                <span class="cam-data-v">{{ d.value }}</span>
                <span class="cam-data-l">{{ d.label }}</span>
              </label>
            </div>
          </div>
          <div class="cam-add">
            <input v-model="mName" class="cam-input" placeholder="姓名" @keyup.enter="doAddMember" />
            <input v-model="mRole" class="cam-input" placeholder="角色（如 运营组）" @keyup.enter="doAddMember" />
            <button class="cam-add-btn" :disabled="!mName.trim()" @click="doAddMember">＋ 添加成员</button>
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

        <!-- 数据权限 -->
        <template v-else-if="tab === 'dataScopes'">
          <div class="cam-help cam-help-top">控制本群 AI 能访问哪些系统及其密级 / 访问级——数据隔离的核心边界。</div>
          <div v-for="(d, i) in state.dataScopes" :key="'d' + i" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">
                {{ d.label }}
                <span class="cam-level" :class="'lv-' + d.level">{{ d.level }}</span>
              </div>
            </div>
            <select v-model="d.access" class="cam-select cam-select-sm" :class="{ off: d.access === '禁用' }">
              <option v-for="a in accessOptions" :key="a" :value="a">{{ a }}</option>
            </select>
            <button class="cam-del" title="移除" @click="removeScope(i)">×</button>
          </div>
          <div class="cam-add">
            <input v-model="dLabel" class="cam-input" placeholder="系统 / 数据源名称" @keyup.enter="doAddScope" />
            <select v-model="dLevel" class="cam-select cam-select-sm">
              <option v-for="l in levelOptions" :key="l" :value="l">{{ l }}</option>
            </select>
            <select v-model="dAccess" class="cam-select cam-select-sm">
              <option v-for="a in accessOptions" :key="a" :value="a">{{ a }}</option>
            </select>
            <button class="cam-add-btn" :disabled="!dLabel.trim()" @click="doAddScope">＋ 添加</button>
          </div>
        </template>

        <!-- 规则 -->
        <template v-else-if="tab === 'rules'">
          <div v-for="(r, i) in state.rules" :key="'r' + i" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">{{ r.label }}</div>
              <div v-if="r.desc" class="cam-row-desc">{{ r.desc }}</div>
            </div>
            <button class="cam-del" title="移除" @click="removeItem('rules', i)">×</button>
          </div>
          <div class="cam-add">
            <input v-model="rLabel" class="cam-input" placeholder="规则名称" @keyup.enter="doAddRule" />
            <input v-model="rDesc" class="cam-input" placeholder="说明（可选）" @keyup.enter="doAddRule" />
            <button class="cam-add-btn" :disabled="!rLabel.trim()" @click="doAddRule">＋ 添加规则</button>
          </div>
        </template>

        <!-- 模型 & 配额 -->
        <template v-else-if="tab === 'model'">
          <div class="cam-field">
            <label class="cam-field-label">模型</label>
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
          <div class="cam-help">为本群独立分配模型与额度，便于成本归集与防滥用。</div>
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
          <div class="cam-help">记忆与上下文按群隔离，A 群对话不会泄漏到 B 群；审计日志用于事后追溯。</div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  useChannelAdmin,
  MODEL_OPTIONS,
  type Confidential,
  type AccessLevel
} from '@/composables/useChannelAdmin'

type TabKey = 'persona' | 'members' | 'skills' | 'knowledge' | 'dataScopes' | 'rules' | 'model' | 'memory'
type CountKey = 'members' | 'skills' | 'knowledge' | 'rules' | 'dataScopes'

const { visible, state, groupName, close, addMember, removeMember, addItem, removeItem, addScope, removeScope } = useChannelAdmin()

const tabs: { key: TabKey; label: string; countKey?: CountKey }[] = [
  { key: 'persona', label: '角色' },
  { key: 'members', label: '人员', countKey: 'members' },
  { key: 'skills', label: '技能', countKey: 'skills' },
  { key: 'knowledge', label: '知识库', countKey: 'knowledge' },
  { key: 'dataScopes', label: '数据权限', countKey: 'dataScopes' },
  { key: 'rules', label: '规则', countKey: 'rules' },
  { key: 'model', label: '模型' },
  { key: 'memory', label: '记忆审计' }
]
const tab = ref<TabKey>('members')

function countOf(k?: CountKey) { return k ? state[k].length : 0 }

/* 人员：展开后勾选其要在大脑展示的数据 */
const expanded = reactive<Record<number, boolean>>({})
function toggleExpand(i: number) { expanded[i] = !expanded[i] }
function pickedCount(m: { data: { selected: boolean }[] }) { return m.data.filter((d) => d.selected).length }

const modelOptions = MODEL_OPTIONS
const levelOptions: Confidential[] = ['公开', '内部', '机密']
const accessOptions: AccessLevel[] = ['禁用', '只读', '读写']
const scopeOptions = ['仅本群', '本部门', '全公司']

/* —— 列表型 tab 的添加表单 —— */
const mName = ref(''); const mRole = ref('')
const sLabel = ref(''); const sTag = ref(''); const sDesc = ref('')
const kLabel = ref(''); const kDesc = ref('')
const rLabel = ref(''); const rDesc = ref('')
const dLabel = ref(''); const dLevel = ref<Confidential>('内部'); const dAccess = ref<AccessLevel>('只读')

function doAddMember() { addMember(mName.value, mRole.value); mName.value = ''; mRole.value = '' }
function doAddSkill() { addItem('skills', sLabel.value, sDesc.value, sTag.value); sLabel.value = ''; sTag.value = ''; sDesc.value = '' }
function doAddKnowledge() { addItem('knowledge', kLabel.value, kDesc.value); kLabel.value = ''; kDesc.value = '' }
function doAddRule() { addItem('rules', rLabel.value, rDesc.value); rLabel.value = ''; rDesc.value = '' }
function doAddScope() { addScope(dLabel.value, dLevel.value, dAccess.value); dLabel.value = '' }

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value) close()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<!-- 弹窗样式见全局 src/styles/admin-modal.css（与系统 AI 设置弹窗共用 .cam-*）-->
