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
              <textarea v-model="agForm.system_prompt" class="cam-input ms-ta" rows="4" maxlength="4000" placeholder="人设:你是…擅长…工作方式…输出…" />
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
        <template v-else>
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
  type MyAgent, type MySkill,
} from '@/matrix/client'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()
function close() { emit('close') }

const tab = ref<'agents' | 'skills'>('agents')
const agents = ref<MyAgent[]>([])
const skills = ref<MySkill[]>([])
const editing = ref(false)
const busy = ref(false)
const errText = ref('')
const agForm = reactive<MyAgent & { _edit: boolean }>({ slug: '', name: '', description: '', system_prompt: '', model: '', enabled: true, _edit: false })
const skForm = reactive<MySkill & { _edit: boolean }>({ slug: '', name: '', description: '', instructions: '', enabled: true, _edit: false })

async function load() {
  errText.value = ''
  ;[agents.value, skills.value] = await Promise.all([myAgentsList(), mySkillsList()])
}
watch(() => props.visible, (v) => { if (v) { editing.value = false; load() } })

function newAgent() { Object.assign(agForm, { slug: '', name: '', description: '', system_prompt: '', model: '', enabled: true, _edit: false }); editing.value = true; errText.value = '' }
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
.ms-form { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; padding: 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-soft); }
.ms-ta { resize: vertical; font-family: inherit; }
.ms-check { font-size: 13px; color: var(--text-2); display: inline-flex; gap: 6px; align-items: center; }
.ms-actions { display: flex; justify-content: flex-end; gap: 8px; }
.cam-mini { border: 1px solid var(--border); background: var(--bg-panel); border-radius: 7px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.cam-mini:hover { background: var(--bg-hover); }
</style>
