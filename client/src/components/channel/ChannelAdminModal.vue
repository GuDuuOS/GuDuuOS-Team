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

      <!-- AI 一键写:补充要求小弹窗(产品风格,替代原生 prompt) -->
      <div v-if="aiDlgOpen" class="cam-ai-mask" @click.self="aiDlgOpen = false">
        <div class="cam-ai-dlg">
          <div class="cam-ai-t">✨ AI 一键写规则文档</div>
          <p class="cam-ai-d">AI 将按本频道的人设、规则、智能体与知识库现状生成工作规范草稿，生成后可继续修改。</p>
          <textarea v-model="aiNotes" class="cam-textarea" rows="3" maxlength="1000" placeholder="补充要求（可留空，直接按频道现状生成）&#10;例如：侧重内容审核流程；输出必须带数据依据" />
          <p v-if="state.ruleDoc.trim()" class="cam-ai-warn">⚠️ 编辑区已有内容：AI 会在其基础上改写并覆盖显示（原文已作为参考喂给 AI）。</p>
          <div class="cam-ai-f">
            <button class="cam-add-btn ghost" @click="aiDlgOpen = false">取消</button>
            <button class="cam-add-btn" @click="confirmAiRuleDoc">开始生成</button>
          </div>
        </div>
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
            <input v-model="state.persona.aiName" class="cam-input" placeholder="如 GuDuu OS" />
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
          <!-- 单条规则(轻量):列表保留;添加行默认折叠成小链接——「规则文档」才是本页主角
               (负责人拍板:两个输入区叠着显重,条目弱化、保留能力与数据链路)。 -->
          <p class="cam-row-desc" style="margin:0 0 4px">单条铁律（如「对外报价须负责人确认」）——快速添加、可单独删除；完整工作规范请写下方「规则文档」。</p>
          <div v-for="(r, i) in state.rules" :key="'r' + i" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">{{ r.label }}</div>
              <div v-if="r.desc" class="cam-row-desc">{{ r.desc }}</div>
            </div>
            <button class="cam-del" title="移除" @click="removeItem('rules', i)">×</button>
          </div>
          <button v-if="!ruleAddOpen" class="cam-rule-add-link" @click="ruleAddOpen = true">＋ 添加单条规则</button>
          <div v-else class="cam-add">
            <input v-model="rLabel" class="cam-input" placeholder="规则名称" @keyup.enter="doAddRule" />
            <input v-model="rDesc" class="cam-input" placeholder="说明（可选）" @keyup.enter="doAddRule" />
            <button class="cam-add-btn" :disabled="!rLabel.trim()" @click="doAddRule">＋ 添加</button>
            <button class="cam-add-btn ghost" @click="ruleAddOpen = false">收起</button>
          </div>

          <!-- 频道规则文档(Markdown,负责人需求):像 CLAUDE.md 的整篇工作规范——每轮全文注入本频道 AI。
               两种编辑方式:直接在下方编辑 / 上传 .md 填入。与知识库分工:文档=每轮必读的硬约束,
               大量背景资料请放「知识库」(按需检索),别塞这里(全文注入,超长又贵又挤)。 -->
          <div class="cam-ruledoc">
            <div class="cam-ruledoc-h">
              <span class="cam-field-label">📜 频道规则文档（Markdown）</span>
              <span class="cam-ruledoc-n" :class="{ over: state.ruleDoc.length >= RULEDOC_MAX }">{{ state.ruleDoc.length }} / {{ RULEDOC_MAX }}</span>
              <button class="cam-add-btn" :disabled="ruleDocAi || !isLive" title="AI 按频道上下文(人设/规则/知识库)生成工作规范草稿,可再修改" @click="doAiRuleDoc">{{ ruleDocAi ? '✨ 生成中…' : '✨ AI 一键写' }}</button>
              <button class="cam-add-btn" :disabled="ruleDocUploading" @click="pickRuleDocFile">{{ ruleDocUploading ? '读取中…' : '⬆ 上传 .md' }}</button>
              <input ref="ruleDocFileInput" type="file" accept=".md,.markdown,.txt" hidden @change="onRuleDocFilePicked" />
            </div>
            <p class="cam-row-desc" style="margin:2px 0 6px">
              写"AI 在本频道怎么干活"：身份、流程、输出规范、禁区——每轮对话全文注入。大量背景资料请放「知识库」标签（按需检索），别贴在这里。
            </p>
            <textarea
              v-model="state.ruleDoc"
              class="cam-textarea cam-ruledoc-ta"
              :maxlength="RULEDOC_MAX"
              rows="12"
              placeholder="# 本频道工作规范&#10;&#10;## 身份&#10;你是……&#10;&#10;## 流程&#10;1. ……&#10;&#10;## 禁区&#10;- 不得……"
            />
            <p v-if="ruleDocErr" class="cam-err">{{ ruleDocErr }}</p>
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
  getGlobalAgents, kbRoomAdd, kbRoomDelete, fetchRuleDocDraft,
  normalizeUserId, userExists, checkUserDeactivated, currentUserId,
  type GlobalAgent,
} from '@/matrix/client'

type TabKey = 'persona' | 'members' | 'skills' | 'knowledge' | 'dataScopes' | 'rules' | 'model' | 'memory'
type CountKey = 'members' | 'skills' | 'knowledge' | 'rules' | 'dataScopes'

const {
  visible, state, groupName, close, addMember, removeMember, addItem, removeItem, addScope, removeScope,
  // 真实成员 + 配置持久化（有真后端时走这套）
  roomId, isLive, saveState, liveMembers, refreshLiveMembers, inviteLiveMember, removeLiveMember,
  // 频道知识库真实文档:与右侧「关于此频道」共享同一份(负责人报的"维护后右侧未同步")
  roomKbDocs: kbDocs, loadRoomKbDocs,
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

// 标签页的数字：有真后端时用真实数据——人员数真实成员;知识库=「来源」条目+真实
// 上传的文档(上传入库后数字不动、与实际不符是负责人报的 bug)。其余用本地 state。
function countOf(k?: CountKey) {
  if (k === 'members' && isLive.value) return liveMembers.value.length
  if (k === 'knowledge' && isLive.value) return state.knowledge.length + kbDocs.value.length
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
function doAddSkill() {
  if (!addItem('skills', sLabel.value, sDesc.value, sTag.value)) return  // 同名拦截:输入保留,用户可改名
  sLabel.value = ''; sTag.value = ''; sDesc.value = ''
}
function doAddKnowledge() {
  kbErr.value = ''
  if (!addItem('knowledge', kLabel.value, kDesc.value)) {
    kbErr.value = `「${kLabel.value.trim()}」已存在，无需重复添加（可先删除旧条目再加）`
    return
  }
  kLabel.value = ''; kDesc.value = ''
}
const ruleAddOpen = ref(false)   // 单条规则添加行默认折叠(文档区是主角)
function doAddRule() {
  if (!addItem('rules', rLabel.value, rDesc.value)) return  // 同名拦截:输入保留
  rLabel.value = ''; rDesc.value = ''; ruleAddOpen.value = false
}
// 频道规则文档:上传 .md 填入(编辑区 v-model 直接绑 state.ruleDoc,自动保存走 composable watch)
const RULEDOC_MAX = 4000  // 每轮全文注入,给上限防挤占对话空间(后端注入同样截断兜底)
const ruleDocFileInput = ref<HTMLInputElement>()
const ruleDocUploading = ref(false)
const ruleDocErr = ref('')
function pickRuleDocFile() { if (!ruleDocUploading.value) ruleDocFileInput.value?.click() }
// AI 一键写:按频道上下文生成规范草稿填入编辑区(不直接落库,用户可改,保存走自动保存)。
// 交互走产品风格的自定义小弹窗(负责人:原生 prompt 不符设计风格),覆盖提示也收在弹窗里。
const ruleDocAi = ref(false)
const aiDlgOpen = ref(false)
const aiNotes = ref('')
function doAiRuleDoc() {
  if (!roomId.value || ruleDocAi.value) return
  aiNotes.value = ''
  aiDlgOpen.value = true
}
async function confirmAiRuleDoc() {
  if (!roomId.value || ruleDocAi.value) return
  aiDlgOpen.value = false
  ruleDocAi.value = true; ruleDocErr.value = ''
  try {
    const md = await fetchRuleDocDraft(roomId.value, aiNotes.value.trim(), state.ruleDoc)
    state.ruleDoc = md.slice(0, RULEDOC_MAX)   // 填入即自动保存;可继续手改
  } catch (e: any) {
    ruleDocErr.value = e?.message || String(e)
  } finally {
    ruleDocAi.value = false
  }
}
async function onRuleDocFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const f = (input.files || [])[0]
  input.value = ''
  if (!f) return
  ruleDocUploading.value = true; ruleDocErr.value = ''
  try {
    const text = (await f.text()).trim()
    if (!text) { ruleDocErr.value = `${f.name}:内容为空`; return }
    if (text.length > RULEDOC_MAX) {
      ruleDocErr.value = `${f.name}:${text.length} 字超过上限 ${RULEDOC_MAX}——规则文档写"怎么干活",大段资料请上传到「知识库」标签`
      return
    }
    state.ruleDoc = text   // 覆盖现有内容;自动保存到本频道
  } catch (err: any) {
    ruleDocErr.value = err?.message || String(err)
  } finally {
    ruleDocUploading.value = false
  }
}
function doAddScope() { addScope(dLabel.value, dLevel.value, dAccess.value); dLabel.value = '' }

// 可绑定的全局智能体（管理后台维护，存控制室 state event）
const globalAgents = ref<GlobalAgent[]>([])
async function loadGlobalAgents() {
  try { globalAgents.value = await getGlobalAgents() } catch { globalAgents.value = [] }
}

/* —— 频道知识库：上传真实文档进本频道 RAG（区别于上面的“来源”标签是占位）—— */
const kbUploading = ref(false)
const kbErr = ref('')
const kbFileInput = ref<HTMLInputElement>()
// 可读为文本的类型：文本/markdown/csv/json/日志等。PDF/Word 需服务端解析，暂不支持。
const KB_TEXT_RE = /\.(txt|md|markdown|csv|tsv|json|log|text|rst|yaml|yml|xml|html?)$/i
const KB_MAX_CHARS = 50000  // 与后端 MAX_DOC_CHARS 对齐(2万→5万,产品手册轻松超2万),本地先拦、提示更友好
/** 上传前内容清洗(与后端 kb_cmd.clean_upload_text 同口径,改一处必须同步另一处)。
 *  修「空 CSV 报太长」:Excel 把空表另存 CSV 会导出上万行纯逗号,视觉空文件按原文
 *  计数就误报超限。CSV/TSV 剔除纯分隔符行;所有文件去行尾空白、压缩连续空行。 */
function cleanUploadText(text: string, filename: string): string {
  let lines = text.split(/\r?\n/).map((ln) => ln.replace(/\s+$/, ''))
  if (/\.(csv|tsv)$/i.test(filename)) {
    lines = lines.filter((ln) => ln.replace(/[,;\t"' ]/g, '').trim() !== '')
  }
  const out: string[] = []
  let blank = 0
  for (const ln of lines) {
    if (ln === '') { blank++; if (blank > 1) continue } else { blank = 0 }
    out.push(ln)
  }
  return out.join('\n').trim()
}
async function loadRoomDocs() { await loadRoomKbDocs() }
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
      const text = cleanUploadText((await f.text()), f.name)
      if (!text) { kbErr.value = `${f.name}：内容为空（清洗掉空单元格/空行后没有实际内容），跳过`; continue }
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
  // 清掉上次遗留的报错(如上次「移出失败」)——否则关掉再开,旧红字还粘在新弹窗顶上。
  liveErr.value = ''
  liveInvite.value = ''
  kbErr.value = ''
  ruleDocErr.value = ''   // 规则文档上传/AI一键写的报错(负责人报:关了重开旧红字还在)
  // 清掉所有 tab 的「添加」草稿输入——填了没点添加就关弹窗,再打开不该还挂着上次的
  // 半截内容(负责人报的:技能三个框残留)。已点添加的,add 函数本来就即时清。
  mName.value = ''; mRole.value = ''
  sLabel.value = ''; sTag.value = ''; sDesc.value = ''
  kLabel.value = ''; kDesc.value = ''
  rLabel.value = ''; rDesc.value = ''
  dLabel.value = ''
  if (isLive.value) { refreshLiveMembers(); loadGlobalAgents(); loadRoomDocs() }
  // 存量频道兜底(负责人:每个频道都要有可见 RULE):打开弹窗发现规则为空 → 自动补默认
  // 「频道资源边界」。bot 端另有启动 backfill 覆盖它有权限的房;这里覆盖用户能管的房。
  // 稍等配置从房间加载完再判(loadConfigFromRoom 异步),已有规则的不动(幂等)。
  if (isLive.value) {
    setTimeout(() => {
      if (visible.value && !state.rules.length) {
        addItem('rules', '频道资源边界',
          '本频道 AI 仅使用本频道的技能、智能体、规则与知识库(含管理员显式绑定进本频道的知识源)作答,不引用频道外内容。')
      }
    }, 1200)
  }
})

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value) close()
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<!-- 弹窗样式见全局 src/styles/admin-modal.css（与安其中枢 AI 设置弹窗共用 .cam-*）-->
