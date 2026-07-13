<!--
  「我的AI工坊」——用户自建 智能体 / 技能(归属本人账号、计入存储空间;负责人需求)。
  · 智能体:私人 AI 同事——出现在你的派单名册(标「我的·」),任意频道输入它的名字即由它应答。
  · 技能:随你每轮对话自动生效的方法论(精简为宜,占每轮注入预算)。
  数据走 bot 端点(/cosmac/my/*),服务端按 owner 隔离 + 存储配额硬管控。
-->
<template>
  <div v-if="visible" class="cam-overlay" @click.self="close">
    <div class="cam-modal" role="dialog" aria-modal="true">
      <div class="cam-head">
        <div>
          <div class="cam-title">我的AI工坊</div>
          <div class="cam-sub">自建你的专属 智能体 与 技能 · 归属你的账号 · 计入存储空间</div>
        </div>
        <button class="cam-x" @click="close">×</button>
      </div>

      <div class="cam-tabs">
        <button class="cam-tab" :class="{ active: tab === 'agents' }" @click="tab = 'agents'">我的智能体 <i>{{ agents.length }}</i></button>
        <button class="cam-tab" :class="{ active: tab === 'skills' }" @click="tab = 'skills'">我的技能 <i>{{ skills.length }}</i></button>
        <button class="cam-tab" :class="{ active: tab === 'acquired' }" @click="tab = 'acquired'">已获取 <i>{{ acquired.length }}</i></button>
      </div>

      <div class="cam-body">
        <div v-if="errText" class="cam-help cam-help-top" style="color:#b94a4a">{{ errText }}</div>

        <!-- ═══ 智能体 ═══ -->
        <template v-if="tab === 'agents'">
          <div class="cam-help cam-help-top">它会出现在主 AI 的派单名册里（标「我的·」）；在任意频道输入它的名字，就由它来应答。</div>
          <div v-for="a in agents" :key="a.slug" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">我的·{{ a.name }} <code class="ms-slug">{{ a.slug }}</code>
                <span v-if="!a.enabled" class="cam-tag" style="background:#eee;color:#888">停用</span>
              </div>
              <div class="cam-row-desc">{{ a.description }}</div>
            </div>
            <button class="cam-mini" @click="editAgent(a)">编辑</button>
            <button class="cam-del" title="删除" @click="delAgent(a.slug)">×</button>
          </div>
          <p v-if="!agents.length && !editing" class="cam-row-desc" style="padding:8px 2px">还没有自建智能体。点下方「＋ 新建智能体」造一个专属 AI 同事。</p>

          <template v-if="editing && tab === 'agents'">
            <div class="ms-form">
              <input v-model.trim="agForm.slug" class="cam-input" :disabled="agForm._edit" placeholder="标识 slug(小写字母/数字/中划线,如 my-writer)" />
              <input v-model.trim="agForm.name" class="cam-input" placeholder="名称(如 小说写手)" />
              <input v-model.trim="agForm.description" class="cam-input" placeholder="备注:它是干嘛的、什么时候找它(主 AI 派单就看这句)" />
              <div class="ms-persona-h">
                <span class="ms-persona-label">人设（system prompt）</span>
                <button type="button" class="cam-mini" @click="applyPersonaTemplate">套用结构模板</button>
              </div>
              <textarea v-model="agForm.system_prompt" class="cam-input ms-ta ms-persona" rows="12" maxlength="4000" placeholder="你是…擅长…工作方式…输出…（可点上方「套用结构模板」按推荐结构写）" />
              <span class="ms-hint">按 角色定位 / 擅长 / 工作方式 / 输出要求 / 注意事项 五段写更专业；智能体只在被 @/点名时激活、不占日常上下文，可以写详细些（上限 4000 字）。</span>
              <input v-model.trim="agForm.model" class="cam-input" placeholder="模型(可选,留空跟随全局)" />
              <label class="ms-check"><input v-model="agForm.enabled" type="checkbox" /> 启用</label>
              <div class="ms-actions">
                <button class="cam-mini" @click="editing = false">取消</button>
                <button class="cam-add-btn" :disabled="busy" @click="saveAgent">{{ busy ? '保存中…' : '保存' }}</button>
              </div>
            </div>
          </template>
          <div v-else class="cam-add"><button class="cam-add-btn" @click="newAgent">＋ 新建智能体</button></div>
        </template>

        <!-- ═══ 技能 ═══ -->
        <template v-else-if="tab === 'skills'">
          <div class="cam-help cam-help-top">技能随你的每轮对话自动生效（也可在私聊里用「技能」命令管理，同一份数据）。精简为宜，太长会占对话预算。</div>
          <div v-for="s in skills" :key="s.slug" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">{{ s.name || s.slug }} <code class="ms-slug">{{ s.slug }}</code>
                <span v-if="!s.enabled" class="cam-tag" style="background:#eee;color:#888">停用</span>
              </div>
              <div class="cam-row-desc">{{ s.description || (s.instructions || '').slice(0, 60) }}</div>
            </div>
            <button class="cam-mini" @click="editSkill(s)">编辑</button>
            <button class="cam-del" title="删除" @click="delSkill(s.slug)">×</button>
          </div>
          <p v-if="!skills.length && !editing" class="cam-row-desc" style="padding:8px 2px">还没有自建技能。</p>

          <template v-if="editing && tab === 'skills'">
            <div class="ms-form">
              <input v-model.trim="skForm.slug" class="cam-input" :disabled="skForm._edit" placeholder="标识 slug(如 daily-recap)" />
              <input v-model.trim="skForm.name" class="cam-input" placeholder="名称(如 每日复盘)" />
              <input v-model.trim="skForm.description" class="cam-input" placeholder="备注(一句话说明,可选)" />
              <textarea v-model="skForm.instructions" class="cam-input ms-ta" rows="4" maxlength="2000" placeholder="技能正文:方法论/格式/清单,喂给 AI 的指令" />
              <label class="ms-check"><input v-model="skForm.enabled" type="checkbox" /> 启用</label>
              <div class="ms-actions">
                <button class="cam-mini" @click="editing = false">取消</button>
                <button class="cam-add-btn" :disabled="busy" @click="saveSkill">{{ busy ? '保存中…' : '保存' }}</button>
              </div>
            </div>
          </template>
          <div v-else class="cam-add"><button class="cam-add-btn" @click="newSkill">＋ 新建技能</button></div>
        </template>

        <!-- ═══ 已获取（AI Agent 商城）═══ -->
        <template v-else>
          <div class="cam-help cam-help-top">你从「AI Agent 商城」获取的资源。主 AI 派单时会优先考虑你获取的 AI 同事（名册里标 ★）。</div>
          <div v-for="it in acquired" :key="it.kind + ':' + it.slug" class="cam-row">
            <div class="cam-row-main">
              <div class="cam-row-label">
                <span class="ms-kind" :style="{ background: CAT_META[it.kind]?.color || '#888' }">{{ CAT_META[it.kind]?.label || it.kind }}</span>
                {{ it.name }}
                <span v-if="it.stale" class="cam-tag" style="background:#f6e3e3;color:#b94a4a">已下架</span>
                <span v-else-if="!it.unlocked" class="cam-tag" style="background:#f4ead9;color:#9a6b1f">需升级会员</span>
              </div>
              <div class="cam-row-desc">
                {{ it.description || '（该资源已不在商城货架上，可移除）' }}
                <template v-if="it.kind === 'skill' && it.agents.length"> · 随【{{ it.agents.join('/') }}】激活</template>
              </div>
            </div>
            <button class="cam-del" title="移除（不影响使用权限，只是不再优先派单）" @click="removeAcquired(it)">×</button>
          </div>
          <p v-if="!acquired.length" class="cam-row-desc" style="padding:8px 2px">还没有获取过商城资源。</p>
          <div class="cam-add"><button class="cam-add-btn" @click="goMarket">🛒 去 AI Agent 商城逛逛</button></div>
        </template>

        <div class="cam-help">自建内容计入你的存储空间（见「我的额度」）。每类上限 50 个。</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import '@/styles/admin-modal.css'
import {
  myAgentsList, myAgentSave, myAgentDelete,
  mySkillsList, mySkillSave, mySkillDelete,
  fetchMarketAcquired, setMarketItemAcquired,
  type MyAgent, type MySkill, type AcquiredItem,
} from '@/matrix/client'
import { CAT_META } from '@/data/marketplace'
import { useMarketplace } from '@/composables/useMarketplace'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()
function close() { emit('close') }

const tab = ref<'agents' | 'skills' | 'acquired'>('agents')
const agents = ref<MyAgent[]>([])
const skills = ref<MySkill[]>([])
const acquired = ref<AcquiredItem[]>([])
const editing = ref(false)
const busy = ref(false)
const errText = ref('')
const agForm = reactive<MyAgent & { _edit: boolean }>({ slug: '', name: '', description: '', system_prompt: '', model: '', enabled: true, _edit: false })
const skForm = reactive<MySkill & { _edit: boolean }>({ slug: '', name: '', description: '', instructions: '', enabled: true, _edit: false })

async function load() {
  errText.value = ''
  const [a, s, g] = await Promise.all([myAgentsList(), mySkillsList(), fetchMarketAcquired()])
  agents.value = a
  skills.value = s
  acquired.value = g || []
}

/** 移除一条「已获取」——只是不再优先派单/收藏,不影响资源本身的使用权限。 */
async function removeAcquired(it: AcquiredItem) {
  errText.value = ''
  const err = await setMarketItemAcquired(it.kind, it.slug, false)
  if (err) { errText.value = err; return }
  acquired.value = acquired.value.filter((x) => !(x.kind === it.kind && x.slug === it.slug))
}

/** 「去商城逛逛」:关掉工坊、打开 AI Agent 商城(全局单例弹窗)。 */
const { open: openMarketplace } = useMarketplace()
function goMarket() { close(); openMarketplace() }
watch(() => props.visible, (v) => { if (v) { editing.value = false; load() } })

function newAgent() { Object.assign(agForm, { slug: '', name: '', description: '', system_prompt: '', model: '', enabled: true, _edit: false }); editing.value = true; errText.value = '' }

// 结构化人设模板(与后台建智能体同一套五要素骨架)：引导用户写出更专业的自建智能体人设。
const PERSONA_TEMPLATE = `【角色定位】你是……（一句话说清身份与核心职责）
【擅长】
- ……（列 3~5 项具体能力，越具体越好）
- ……
【工作方式】拿到任务先……，再……，最后……（你的思考与执行步骤）
【输出要求】……（输出的格式、结构，必须包含什么；举例更好）
【注意事项】……（红线/禁忌，如：不编造数据、信息不足先追问）`

function applyPersonaTemplate() {
  if (agForm.system_prompt.trim()
      && !confirm('人设框已有内容，套用模板会替换掉它，确定吗？')) return
  agForm.system_prompt = PERSONA_TEMPLATE
}
function editAgent(a: MyAgent) { Object.assign(agForm, { ...a, model: a.model || '', _edit: true }); editing.value = true; errText.value = '' }
async function saveAgent() {
  busy.value = true; errText.value = ''
  try { await myAgentSave({ ...agForm }); editing.value = false; await load() }
  catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}
async function delAgent(slug: string) {
  errText.value = ''
  try { await myAgentDelete(slug); await load() } catch (e: any) { errText.value = e?.message || String(e) }
}
function newSkill() { Object.assign(skForm, { slug: '', name: '', description: '', instructions: '', enabled: true, _edit: false }); editing.value = true; errText.value = '' }
function editSkill(s: MySkill) { Object.assign(skForm, { ...s, _edit: true }); editing.value = true; errText.value = '' }
async function saveSkill() {
  busy.value = true; errText.value = ''
  try { await mySkillSave({ ...skForm }); editing.value = false; await load() }
  catch (e: any) { errText.value = e?.message || String(e) }
  finally { busy.value = false }
}
async function delSkill(slug: string) {
  errText.value = ''
  try { await mySkillDelete(slug); await load() } catch (e: any) { errText.value = e?.message || String(e) }
}
</script>

<style scoped>
.ms-slug { font-size: 11px; color: var(--text-3); background: var(--bg-hover); border-radius: 4px; padding: 1px 5px; margin-left: 6px; }
/* 「已获取」行的资源类型小徽章(颜色跟商城分类一致) */
.ms-kind { font-size: 10px; color: #fff; padding: 1px 7px; border-radius: 999px; margin-right: 4px; font-weight: 600; }
.ms-form { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; padding: 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-soft); }
.ms-ta { resize: vertical; font-family: inherit; }
/* 人设编辑器：更大、等宽，写结构化人设更顺手 */
.ms-persona-h { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ms-persona-label { font-size: 12px; color: var(--text-2, var(--text)); }
.ms-persona { min-height: 220px; font-family: var(--mono, ui-monospace, "SF Mono", Menlo, monospace); font-size: 13px; line-height: 1.6; tab-size: 2; }
.ms-hint { font-size: 12px; color: var(--text-3, var(--text-2)); line-height: 1.5; }
.ms-check { font-size: 13px; color: var(--text-2); display: inline-flex; gap: 6px; align-items: center; }
.ms-actions { display: flex; justify-content: flex-end; gap: 8px; }
.cam-mini { border: 1px solid var(--border); background: var(--bg-panel); border-radius: 7px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.cam-mini:hover { background: var(--bg-hover); }
</style>
