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
          <!-- 绑定全局智能体：选了就用它的人设/技能（覆盖下面的自定义人设）-->
          <div v-if="isLive" class="cam-field">
            <label class="cam-field-label">本群智能体</label>
            <select v-model="state.persona.agentSlug" class="cam-select">
              <option value="">不绑定（用下面的自定义人设）</option>
              <option v-for="a in globalAgents" :key="a.slug" :value="a.slug">
                {{ a.name || a.slug }}{{ a.enabled ? '' : '（已停用）' }}
              </option>
            </select>
            <div class="cam-help">
              绑定后，主 AI 在本群以该智能体的人设回应，并自动启用它绑定的技能（在「管理后台 → 智能体」里维护）。
            </div>
          </div>
          <div class="cam-field">
            <label class="cam-field-label">AI 名称</label>
            <input v-model="state.persona.aiName" class="cam-input" placeholder="如 CosMac Star" />
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
          <!-- 真实频道：人设已存进房间，多端同步；显示保存状态 -->
          <div v-if="isLive" class="cam-help" :style="saveHintStyle">{{ saveHint }}</div>
        </template>

        <!-- 人员（真实 Matrix 成员：有真后端时走这支）-->
        <template v-else-if="tab === 'members' && isLive">
          <div v-if="liveErr" class="cam-help cam-help-top" style="color:#b94a4a">{{ liveErr }}</div>
          <div v-for="m in liveMembers" :key="m.id" class="cam-member">
            <div class="cam-row">
              <div class="cam-ava" :class="{ bot: m.isBot }">
                <img v-if="m.avatar" :src="m.avatar" alt="" class="cam-ava-img" />
                <template v-else>{{ m.isBot ? '智' : [...m.name][0] }}</template>
              </div>
              <div class="cam-row-main">
                <div class="cam-row-label">
                  {{ m.name }}
                  <span v-if="m.isBot" class="cam-tag">APP</span>
                  <!-- 频道管理员标识:群主(power=100)/管理员(≥50)给醒目徽章,一眼看清谁是管理员。
                       bot 是内置 AI、不算"人类管理员",只挂 APP 标不给这个徽章(修「群主都标给中枢AI」)。-->
                  <span v-else-if="m.role === 'owner'" class="cam-tag cam-tag-owner">👑 群主</span>
                  <span v-else-if="m.role === 'admin'" class="cam-tag cam-tag-admin">管理员</span>
                  <span v-if="m.pending" class="cam-tag" style="background:#e8dcc4;color:#8a6a3a">待接受</span>
                </div>
                <!-- 角色文字:bot 的 roleLabel 已在 listChannelMembers 里归一成「副频道主」(不叫群主),
                     真人则是 群主/管理员/成员。真正的人类管理员另有上面的醒目徽章。 -->
                <div class="cam-row-desc">{{ m.roleLabel }} · {{ m.id }}</div>
              </div>
              <button class="cam-del" title="移出频道" :disabled="liveBusy" @click="doRemoveLive(m)">×</button>
            </div>
          </div>
          <p v-if="!liveMembers.length" class="cam-row-desc" style="padding:8px 2px">还没有成员（或正在加载…）</p>
          <div class="cam-add">
            <input v-model="liveInvite" class="cam-input" placeholder="邀请已有用户：用户名 或 @用户:cosmac.cc" @keyup.enter="doInviteLive" />
            <button class="cam-add-btn" :disabled="!liveInvite.trim() || liveBusy" @click="doInviteLive">{{ liveBusy ? '邀请中…' : '＋ 邀请成员' }}</button>
          </div>
          <div class="cam-help">频道真实成员。邀请 = 把已有用户拉进频道；移出 = 移出频道（需你在本频道有管理员权限）。新建账号需走后台。</div>
        </template>

        <!-- 人员（demo：无真后端时的 mock 展示）-->
        <template v-else-if="tab === 'members'">
          <div v-for="(m, i) in state.members" :key="'m' + i" class="cam-member">
            <div class="cam-row" :class="{ clickable: m.data.length }" @click="m.data.length && toggleExpand(i)">
              <div class="cam-ava" :class="{ bot: m.bot }" :style="m.color ? { background: m.color } : undefined">{{ m.avatar }}</div>
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
            <input v-model="mRole" class="cam-input" placeholder="角色（如 剪辑）" @keyup.enter="doAddMember" />
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
          <p v-if="isLive && !state.skills.length" class="cam-row-desc" style="padding:8px 2px">还没有技能 —— 在下方添加，会自动保存到本频道。</p>
          <div class="cam-add">
            <input v-model="sLabel" class="cam-input" placeholder="技能名称" @keyup.enter="doAddSkill" />
            <input v-model="sTag" class="cam-input cam-input-sm" placeholder="/命令（可选）" @keyup.enter="doAddSkill" />
            <input v-model="sDesc" class="cam-input" placeholder="说明（可选）" @keyup.enter="doAddSkill" />
            <button class="cam-add-btn" :disabled="!sLabel.trim()" @click="doAddSkill">＋ 添加技能</button>
          </div>
          <div v-if="isLive" class="cam-help" :style="saveHintStyle">{{ saveHint }}</div>
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
          <p v-if="isLive && !state.knowledge.length" class="cam-row-desc" style="padding:8px 2px">还没有知识库 —— 在下方添加，会自动保存到本频道。</p>
          <div class="cam-add">
            <input v-model="kLabel" class="cam-input" placeholder="知识库名称" @keyup.enter="doAddKnowledge" />
            <input v-model="kDesc" class="cam-input" placeholder="说明（如 1,240 篇）" @keyup.enter="doAddKnowledge" />
            <button class="cam-add-btn" :disabled="!kLabel.trim()" @click="doAddKnowledge">＋ 添加来源</button>
          </div>
          <div v-if="isLive" class="cam-help" :style="saveHintStyle">{{ saveHint }}</div>

          <!-- 真实上传：把文本文件切块入库，本频道 AI 检索时自动命中（区别于上面的“来源”标签占位）-->
          <template v-if="isLive">
            <div class="cam-kb-divider">上传文档到本频道知识库（AI 自动检索）</div>
            <div v-if="kbErr" class="cam-help cam-help-top" style="color:#b94a4a">{{ kbErr }}</div>
            <div v-for="d in kbDocs" :key="'kbd' + d.id" class="cam-row">
              <div class="cam-row-main">
                <div class="cam-row-label">📄 {{ d.title }}</div>
                <div class="cam-row-desc">已切块入库 · 本频道 AI 可检索</div>
              </div>
              <button class="cam-del" title="从知识库删除" @click="deleteRoomDoc(d.id)">×</button>
            </div>
            <p v-if="!kbDocs.length" class="cam-row-desc" style="padding:8px 2px">还没有上传文档。点下方「上传文件」把资料喂给本频道 AI。</p>
            <div class="cam-add">
              <button class="cam-add-btn" :disabled="kbUploading" @click="pickKbFile">{{ kbUploading ? '上传中…' : '⬆ 上传文件' }}</button>
              <input ref="kbFileInput" type="file" multiple accept=".txt,.md,.markdown,.csv,.tsv,.json,.log,.text,.rst,.yaml,.yml,.xml,.html,.htm,text/*" style="display:none" @change="onKbFilePicked" />
            </div>
            <div class="cam-help">支持文本文件（.txt / .md / .csv / .json 等），单篇上限 2 万字。需你在本频道有管理员权限。PDF / Word 解析稍后支持。</div>
          </template>
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
          <p v-if="isLive && !state.dataScopes.length" class="cam-row-desc" style="padding:8px 2px">还没有配置数据源 —— 在下方添加，会自动保存到本频道。</p>
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
          <div v-if="isLive" class="cam-help" :style="saveHintStyle">{{ saveHint }}</div>
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
          <p v-if="isLive && !state.rules.length" class="cam-row-desc" style="padding:8px 2px">还没有规则 —— 在下方添加，会自动保存到本频道。</p>
          <div class="cam-add">
            <input v-model="rLabel" class="cam-input" placeholder="规则名称" @keyup.enter="doAddRule" />
            <input v-model="rDesc" class="cam-input" placeholder="说明（可选）" @keyup.enter="doAddRule" />
            <button class="cam-add-btn" :disabled="!rLabel.trim()" @click="doAddRule">＋ 添加规则</button>
          </div>
          <div v-if="isLive" class="cam-help" :style="saveHintStyle">{{ saveHint }}</div>
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
          <div v-if="isLive" class="cam-help" :style="saveHintStyle">{{ saveHint }}</div>
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
          <div v-if="isLive" class="cam-help" :style="saveHintStyle">{{ saveHint }}</div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
// 弹窗样式（.cam-*）来自全局 admin-modal.css。真实客户端（main.ts）只加载 tokens/reset、
// 不加载整包 styles/index.css，所以组件自带这份样式，保证在任何宿主里（DEMO / 真实端）都成型。
import '@/styles/admin-modal.css'
import {
  useChannelAdmin,
  MODEL_OPTIONS,
  type Confidential,
  type AccessLevel
} from '@/composables/useChannelAdmin'
import {
  getGlobalAgents, kbRoomList, kbRoomAdd, kbRoomDelete,
  normalizeUserId, userExists, checkUserDeactivated, currentUserId,
  type GlobalAgent,
} from '@/matrix/client'

type TabKey = 'persona' | 'members' | 'skills' | 'knowledge' | 'dataScopes' | 'rules' | 'model' | 'memory'
type CountKey = 'members' | 'skills' | 'knowledge' | 'rules' | 'dataScopes'

const {
  visible, state, groupName, close, addMember, removeMember, addItem, removeItem, addScope, removeScope,
  // 真实成员 + 配置持久化（有真后端时走这套）
  roomId, isLive, saveState, liveMembers, refreshLiveMembers, inviteLiveMember, removeLiveMember
} = useChannelAdmin()

// 人设保存状态提示（存进房间 state event，多端同步）
const saveHint = computed(() => ({
  idle: '已存入本频道 · 编辑后自动保存、多端同步',
  saving: '保存中…',
  saved: '✓ 已保存到本频道 · 多端同步',
  error: '保存失败：你可能没有本群修改配置的权限（需管理员）',
}[saveState.value]))
const saveHintStyle = computed(() => saveState.value === 'error' ? 'color:#b94a4a' : '')

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

// 人员标签的数字：有真后端用真实成员数，否则用 mock
function countOf(k?: CountKey) {
  if (k === 'members' && isLive.value) return liveMembers.value.length
  return k ? state[k].length : 0
}

/* —— 真实成员：邀请 / 移除 —— */
const liveInvite = ref('')
const liveBusy = ref(false)
const liveErr = ref('')
async function doInviteLive() {
  if (!liveInvite.value.trim() || liveBusy.value) return
  liveBusy.value = true; liveErr.value = ''
  try {
    // 邀请前先校验：①账号不存在 ②账号已停用——停用用户能收到邀请却永远接受不了,
    // 只会在成员列表里挂着「待接受」,不给提示的话邀请人一直以为拉进来了。
    const uid = normalizeUserId(liveInvite.value)
    // ③重复添加:已在成员列表(含待接受)——分"自己/待接受/他人"给明确提示,
    //   别让 Matrix 的「403 already in the room」裸奔出来(负责人报的)。
    const hit = liveMembers.value.find((m) => m.id === uid)
    if (hit) {
      liveErr.value = uid === currentUserId()
        ? '您已是本频道成员，无需重复添加自己。'
        : hit.pending
          ? '已邀请过该成员，正等待对方接受，无需重复邀请。'
          : '该成员已是本频道成员，无需重复添加。'
      return
    }
    if (!(await userExists(uid))) {
      liveErr.value = '该用户不存在，请检查用户名是否正确。'
      return
    }
    if (await checkUserDeactivated(uid)) {
      liveErr.value = '该用户账号当前处于停用状态，无法加入频道。请联系系统管理员恢复账号状态。'
      return
    }
    await inviteLiveMember(liveInvite.value)
    liveInvite.value = ''
  } catch (e: any) {
    // 兜底:本地成员列表没刷到、Synapse 仍报"已在房" → 同样转成友好文案
    const msg = String(e?.message || e)
    liveErr.value = /already in the room/i.test(msg)
      ? '该成员已是本频道成员，无需重复添加。'
      : `邀请失败：${msg}`
  } finally { liveBusy.value = false }
}
async function doRemoveLive(m: { id: string; name: string }) {
  if (liveBusy.value) return  // 防连点对同一/多个成员并发 kick
  liveBusy.value = true; liveErr.value = ''
  try {
    await removeLiveMember(m.id)
  } catch (e: any) {
    liveErr.value = `移出失败：${e?.message || e}`
  } finally { liveBusy.value = false }
}

/* 人员：展开后勾选其要在大脑展示的数据 */
const expanded = reactive<Record<number, boolean>>({})
function toggleExpand(i: number) { expanded[i] = !expanded[i] }
function pickedCount(m: { data: { selected: boolean }[] }) { return m.data.filter((d) => d.selected).length }

const modelOptions = MODEL_OPTIONS
const levelOptions: Confidential[] = ['公开', '内部', '机密']
const accessOptions: AccessLevel[] = ['禁用', '只读', '读写']
const scopeOptions = ['仅本群', '本工作室', '全平台']

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

// 可绑定的全局智能体（管理后台维护，存控制室 state event）
const globalAgents = ref<GlobalAgent[]>([])
async function loadGlobalAgents() {
  try { globalAgents.value = await getGlobalAgents() } catch { globalAgents.value = [] }
}

/* —— 频道知识库：上传真实文档进本频道 RAG（区别于上面的“来源”标签是占位）—— */
const kbDocs = ref<{ id: number; title: string; source: string }[]>([])
const kbUploading = ref(false)
const kbErr = ref('')
const kbFileInput = ref<HTMLInputElement>()
// 可读为文本的类型：文本/markdown/csv/json/日志等。PDF/Word 需服务端解析，暂不支持。
const KB_TEXT_RE = /\.(txt|md|markdown|csv|tsv|json|log|text|rst|yaml|yml|xml|html?)$/i
const KB_MAX_CHARS = 20000  // 与后端 MAX_DOC_CHARS 对齐，本地先拦、提示更友好
async function loadRoomDocs() {
  if (!isLive.value || !roomId.value) { kbDocs.value = []; return }
  kbDocs.value = await kbRoomList(roomId.value)
}
function pickKbFile() { if (!kbUploading.value) kbFileInput.value?.click() }
async function onKbFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length || !roomId.value) return
  kbUploading.value = true; kbErr.value = ''
  try {
    for (const f of files) {
      if (!KB_TEXT_RE.test(f.name)) { kbErr.value = `${f.name}：暂只支持文本文件（.txt/.md/.csv/.json 等），PDF/Word 稍后支持`; continue }
      const text = (await f.text()).trim()
      if (!text) { kbErr.value = `${f.name}：内容为空，跳过`; continue }
      if (text.length > KB_MAX_CHARS) { kbErr.value = `${f.name}：太长（${text.length} 字 > ${KB_MAX_CHARS}），请拆分后再传`; continue }
      await kbRoomAdd(roomId.value, f.name, text)
    }
    await loadRoomDocs()
  } catch (err: any) {
    kbErr.value = err?.message || String(err)
  } finally {
    kbUploading.value = false
  }
}
async function deleteRoomDoc(id: number) {
  if (!roomId.value) return
  kbErr.value = ''
  try {
    await kbRoomDelete(roomId.value, id)
    await loadRoomDocs()
  } catch (err: any) {
    kbErr.value = err?.message || String(err)
  }
}
// 切到「知识库」标签时拉一次真实已上传文档
watch(tab, (t) => { if (t === 'knowledge') loadRoomDocs() })

// 每次打开弹窗时，从 Matrix 重新拉一遍真实成员（防 sync 期间有进出群没反映）+ 全局智能体列表
watch(visible, (v) => {
  if (!v) return
  // 清掉上次遗留的报错(如上次「移出失败」)——否则关掉再开,旧红字还粘在新弹窗顶上(本次修复)。
  liveErr.value = ''
  liveInvite.value = ''
  kbErr.value = ''
  if (isLive.value) { refreshLiveMembers(); loadGlobalAgents(); loadRoomDocs() }
})

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value) close()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<!-- 弹窗样式见全局 src/styles/admin-modal.css（与安其中枢 AI 设置弹窗共用 .cam-*）-->
