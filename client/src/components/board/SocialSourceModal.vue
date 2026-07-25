<template>
  <!-- 社媒数据源配置弹窗：配各平台账号 + 取数模式（官方 API / AI 爬取）。
       存 cosmac.social_sources（按工作区、多端同步）。凭据只填「名字」，真值在服务端 env。 -->
  <div v-if="modalOpen" class="ssm-mask" @click.self="closeModal">
    <div class="ssm">
      <div class="ssm-head">
        <div class="ssm-title"><Icon name="plug" :size="16" /> 接入社媒数据源</div>
        <button class="ssm-x" title="关闭" @click="closeModal">×</button>
      </div>

      <div class="ssm-body">
        <p class="ssm-intro">
          配置各平台账号后，中枢 AI 采集器会按设定周期取「粉丝 / 播放 / 互动」回填到数据看板。
          <b>官方 API</b> 准确稳定（需平台开发者资质）；<b>AI 爬取</b> 走 N8N / Coze 工作流抓公开主页（无需授权，稳定性较弱）。
        </p>
        <p class="ssm-intro ssm-intro-tip">
          🔗 <b>用 N8N / Coze 对接爬取</b>：先去 <b>管理后台 · 工作流面板</b> 新建连接器（N8N 选「Webhook」类型、填 webhook URL；Coze 选「Coze」），
          URL 和密钥都存在服务端、安全。回到这里「AI 爬取」模式只需填那个连接器的 <b>slug</b> 即可。
        </p>

        <!-- 已配置列表 -->
        <div v-if="sources.length" class="ssm-list">
          <div v-for="(s, i) in sources" :key="rowKey(s)" class="ssm-row">
            <div class="ssm-row-main">
              <span class="ssm-plat">{{ platformIcon(s.platform) }} {{ platformLabel(s.platform) }}</span>
              <span class="ssm-acc">{{ s.account || '—' }}</span>
              <span class="ssm-mode" :class="s.mode">{{ s.mode === 'api' ? '官方 API' : 'AI 爬取' }}</span>
              <span class="ssm-status" :class="s.lastStatus || 'never'">{{ statusText(s) }}</span>
            </div>
            <div class="ssm-row-sub">
              <label class="ssm-sw">
                <input type="checkbox" v-model="s.enabled" /> 启用
              </label>
              <span v-if="s.mode === 'api' && paramsSummary(s)" class="ssm-meta">{{ paramsSummary(s) }}</span>
              <span v-if="s.mode === 'crawl' && s.workflow" class="ssm-meta">工作流 {{ s.workflow }}</span>
              <span class="ssm-meta">每 {{ s.intervalH ?? 6 }}h</span>
              <span class="ssm-spacer" />
              <button class="ssm-mini" title="后端采集器上线后生效（P2）" @click="syncNow(i)">立即同步</button>
              <button class="ssm-mini del" title="移除" @click="removeSource(i)">移除</button>
            </div>
          </div>
        </div>
        <p v-else class="ssm-empty">还没有数据源 —— 在下面添加一个。</p>

        <!-- 添加表单 -->
        <div class="ssm-add">
          <div class="ssm-add-h">＋ 添加数据源</div>
          <div class="ssm-grid">
            <label class="ssm-field">
              <span>平台</span>
              <select v-model="nPlatform">
                <option v-for="p in SOCIAL_PLATFORMS" :key="p.key" :value="p.key">{{ p.icon }} {{ p.label }}</option>
              </select>
            </label>
            <label class="ssm-field">
              <span>备注名（人看的标签）</span>
              <input v-model="nAccount" placeholder="如 安其影视 · YouTube" @keyup.enter="doAdd" />
            </label>
            <label class="ssm-field">
              <span>取数模式</span>
              <select v-model="nMode">
                <option value="api" :disabled="!spec.supported">官方 API{{ spec.supported ? '' : '（本平台不可用）' }}</option>
                <option value="crawl">AI 爬取（N8N / Coze 工作流）</option>
              </select>
            </label>
            <label class="ssm-field">
              <span>同步间隔（小时）</span>
              <input v-model.number="nInterval" type="number" min="1" max="168" />
            </label>
          </div>

          <!-- 官方 API 模式：按所选平台显示**对应**的认证要求（每个平台都不同）-->
          <template v-if="nMode === 'api'">
            <div v-if="!spec.supported" class="ssm-warn">
              ⚠️ <b>{{ platformLabel(nPlatform) }}</b> 没有可用的官方公开指标 API。{{ spec.note }}
              请把「取数模式」切到 <b>AI 爬取</b>。
            </div>
            <div v-else class="ssm-spec">
              <div class="ssm-spec-h"><Icon name="key" :size="14" /> {{ platformLabel(nPlatform) }} 官方 API · 接入要求</div>
              <div class="ssm-spec-diff">门槛：{{ spec.difficulty }}<span v-if="spec.note"> · {{ spec.note }}</span></div>
              <!-- 1) 服务端密钥：只提示该配哪个 env 名，前端不填值 -->
              <div class="ssm-spec-block">
                <div class="ssm-spec-cap">① 服务端 env 配密钥（运维做，前端不碰真值）</div>
                <div v-for="ev in spec.envVars" :key="ev.name" class="ssm-env">
                  <code>{{ ev.name }}</code><span class="ssm-env-lbl">{{ ev.label }}</span>
                </div>
              </div>
              <!-- 2) 非密参数：因平台而异，存进配置 -->
              <div class="ssm-spec-block">
                <div class="ssm-spec-cap">② 账号定位参数（存配置）</div>
                <label v-for="f in spec.params" :key="f.key" class="ssm-field">
                  <span>{{ f.label }}</span>
                  <input v-model="nParams[f.key]" :placeholder="f.placeholder" @keyup.enter="doAdd" />
                </label>
              </div>
              <a v-if="spec.docUrl" class="ssm-doc" :href="spec.docUrl" target="_blank" rel="noopener"><Icon name="pages" :size="13" /> 官方文档</a>
            </div>
          </template>

          <!-- AI 爬取模式：引用工作流连接器 slug -->
          <template v-else>
            <div class="ssm-spec">
              <label class="ssm-field">
                <span>工作流连接器 slug（N8N / Coze）</span>
                <input v-model="nWorkflow" placeholder="管理后台·工作流面板里建好的连接器 slug" @keyup.enter="doAdd" />
              </label>
              <div class="ssm-spec-diff">
                先在 <b>管理后台 · 工作流面板</b> 建连接器（N8N 选 Webhook、Coze 选 Coze；URL+密钥进 env），这里填它的 slug。
              </div>
            </div>
          </template>

          <button class="ssm-addbtn" :disabled="!canAdd" @click="doAdd">添加数据源</button>
        </div>

        <div class="ssm-foot">
          <span class="ssm-save" :class="saveState">{{ saveHint }}</span>
          <span class="ssm-note">
            密钥 key/token 永不存这里——官方 API 的密钥按平台固定的 env 名配在服务端 <code>COSMAC_SOCIAL_*</code>，
            爬取的 URL/密钥进工作流面板。真实采集为后端 P2 项。
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { ref, reactive, computed, watch } from 'vue'
import { rowKey } from '@/utils/rowKey'
import {
  useSocialSources,
  SOCIAL_PLATFORMS,
  platformLabel,
  platformIcon,
  apiSpecOf,
  type SocialMode,
  type SocialSource,
} from '@/composables/useSocialSources'

const {
  sources, saveState, modalOpen, closeModal, addSource, removeSource,
} = useSocialSources()

// 添加表单字段
const nPlatform = ref(SOCIAL_PLATFORMS[0].key)
const nAccount = ref('')
const nMode = ref<SocialMode>('api')
const nWorkflow = ref('')
const nInterval = ref(6)
// 官方 API 模式的各平台「非密参数」临时输入（键 = spec.params[].key，因平台而异）
const nParams = reactive<Record<string, string>>({})

// 当前所选平台的 API 规格（决定显示哪些字段 / 是否可用官方 API）
const spec = computed(() => apiSpecOf(nPlatform.value))

// 切平台/切模式时清空残留的参数输入，避免上一个平台的字段串味
watch([nPlatform, nMode], () => { for (const k of Object.keys(nParams)) delete nParams[k] })
// 平台不支持官方 API 时，自动把模式切到爬取（避免停在不可用状态）
watch(spec, (s) => { if (nMode.value === 'api' && !s.supported) nMode.value = 'crawl' })

// 能否添加：要有备注名；API 模式平台须支持；爬取模式须填了连接器 slug
const canAdd = computed(() => {
  if (!nAccount.value.trim()) return false
  if (nMode.value === 'api') return spec.value.supported
  return !!nWorkflow.value.trim()
})

function doAdd() {
  if (!canAdd.value) return
  const apiParams: Record<string, string> = {}
  if (nMode.value === 'api') {
    for (const f of spec.value.params) {
      const v = (nParams[f.key] || '').trim()
      if (v) apiParams[f.key] = v
    }
  }
  addSource({
    platform: nPlatform.value,
    account: nAccount.value,
    mode: nMode.value,
    apiParams: nMode.value === 'api' ? apiParams : undefined,
    workflow: nMode.value === 'crawl' ? nWorkflow.value : undefined,
    intervalH: nInterval.value,
  })
  nAccount.value = ''
  nWorkflow.value = ''
  for (const k of Object.keys(nParams)) delete nParams[k]
}

/** 列表行：把 api 参数压成一行摘要（如 channelId=UCxxx · username=foo）*/
function paramsSummary(s: SocialSource): string {
  const p = s.apiParams || {}
  const parts = Object.entries(p).map(([k, v]) => `${k}=${v}`)
  return parts.join(' · ')
}

// P1：采集器未接，点「立即同步」先提示。P2 改成调后端触发一次采集。
function syncNow(_i: number) {
  // 仅占位反馈，避免误以为已取数
  alert('社媒采集器为后端 P2 项，尚未接入。配置已保存，待采集器上线后将按此自动取数。')
}

function statusText(s: SocialSource): string {
  if (!s.enabled) return '已停用'
  switch (s.lastStatus) {
    case 'ok': return s.lastSync ? '已同步' : '待同步'
    case 'error': return '同步失败'
    default: return '待同步'
  }
}

const saveHint = computed(() => ({
  idle: '编辑后自动保存到本工作区 · 多端同步',
  saving: '保存中…',
  saved: '✓ 已保存 · 多端同步',
  error: '保存失败：你可能没有本工作区改配置的权限',
}[saveState.value]))
</script>

<style scoped>
.ssm-mask { position: fixed; inset: 0; background: rgba(0,0,0,.38); display: flex; align-items: center; justify-content: center; z-index: 2000; padding: 24px; }
.ssm { width: 100%; max-width: 720px; max-height: 86vh; display: flex; flex-direction: column; background: var(--bg-panel); border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 18px 50px rgba(0,0,0,.22); overflow: hidden; }
.ssm-head { display: flex; align-items: center; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.ssm-title { font-weight: var(--fw-bold); font-size: var(--fs-150, 16px); color: var(--text); }
.ssm-x { margin-left: auto; border: none; background: transparent; color: var(--text-3); font-size: 22px; line-height: 1; cursor: pointer; border-radius: 6px; width: 28px; height: 28px; }
.ssm-x:hover { background: var(--bg-hover); color: var(--text); }
.ssm-body { padding: 16px 18px; overflow-y: auto; }
.ssm-intro { font-size: 12px; color: var(--text-2); line-height: 1.7; margin: 0 0 10px; }
.ssm-intro-tip { background: var(--bg); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 8px; padding: 9px 11px; margin-bottom: 14px; }

.ssm-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.ssm-row { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; background: var(--bg); }
.ssm-row-main { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ssm-plat { font-weight: var(--fw-bold); color: var(--text); font-size: 13px; }
.ssm-acc { font-size: 12px; color: var(--text-2); font-family: var(--font-mono, monospace); }
.ssm-mode { font-size: 11px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border); color: var(--text-dim, #888); }
.ssm-mode.api { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
.ssm-status { margin-left: auto; font-size: 11px; color: var(--text-3); }
.ssm-status.ok { color: var(--ok, #6b8e4e); }
.ssm-status.error { color: #b94a4a; }
.ssm-row-sub { display: flex; align-items: center; gap: 12px; margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); flex-wrap: wrap; }
.ssm-sw { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-2); cursor: pointer; }
.ssm-meta { font-size: 11px; color: var(--text-3); }
.ssm-spacer { flex: 1; }
.ssm-mini { border: 1px solid var(--border); background: var(--bg-panel); color: var(--text-2); font-size: 11px; padding: 3px 10px; border-radius: 6px; cursor: pointer; }
.ssm-mini:hover { border-color: var(--accent); color: var(--accent); }
.ssm-mini.del:hover { border-color: #b94a4a; color: #b94a4a; }
.ssm-empty { font-size: 12px; color: var(--text-3); padding: 6px 0 16px; }

.ssm-add { border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; background: var(--bg); }
.ssm-add-h { font-size: 13px; font-weight: var(--fw-bold); color: var(--text); margin-bottom: 10px; }
.ssm-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ssm-field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.ssm-field > span { font-size: 11px; color: var(--text-3); }
.ssm-field input, .ssm-field select { width: 100%; box-sizing: border-box; padding: 7px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--bg-input, var(--bg-panel)); color: var(--text); font-size: 13px; }
.ssm-field input:focus, .ssm-field select:focus { outline: none; border-color: var(--accent); }
/* 官方 API 规格区 / 爬取区 */
.ssm-spec { margin-top: 12px; border: 1px solid var(--border); border-radius: 9px; padding: 11px 12px; background: var(--bg-panel); }
.ssm-spec-h { font-size: 12px; font-weight: var(--fw-bold); color: var(--text); margin-bottom: 4px; }
.ssm-spec-diff { font-size: 11px; color: var(--text-3); line-height: 1.6; margin-bottom: 8px; }
.ssm-spec-block { margin-top: 8px; }
.ssm-spec-cap { font-size: 11px; color: var(--text-2); font-weight: var(--fw-bold); margin-bottom: 6px; }
.ssm-spec-block .ssm-field { margin-top: 8px; }
.ssm-env { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
.ssm-env code { font-family: var(--font-mono, monospace); font-size: 11px; background: var(--bg-hover); border: 1px solid var(--border); padding: 1px 6px; border-radius: 5px; color: var(--text); }
.ssm-env-lbl { font-size: 11px; color: var(--text-3); }
.ssm-doc { display: inline-block; margin-top: 8px; font-size: 11px; color: var(--accent); text-decoration: none; }
.ssm-doc:hover { text-decoration: underline; }
/* 平台无官方 API 的警示 */
.ssm-warn { margin-top: 12px; border: 1px solid color-mix(in srgb, #b58932 45%, transparent); background: color-mix(in srgb, #b58932 10%, transparent); border-radius: 9px; padding: 10px 12px; font-size: 12px; color: var(--text-2); line-height: 1.6; }
.ssm-addbtn { width: 100%; margin-top: 12px; padding: 9px; border: none; border-radius: 8px; background: var(--accent); color: #fff; font-size: 13px; font-weight: var(--fw-bold); cursor: pointer; }
.ssm-addbtn:disabled { opacity: .5; cursor: not-allowed; }

.ssm-foot { margin-top: 14px; display: flex; flex-direction: column; gap: 4px; }
.ssm-save { font-size: 11px; color: var(--text-3); }
.ssm-save.saved { color: var(--ok, #6b8e4e); }
.ssm-save.error { color: #b94a4a; }
.ssm-note { font-size: 11px; color: var(--text-3); line-height: 1.5; }
.ssm-note code { font-family: var(--font-mono, monospace); background: var(--bg-hover); padding: 0 4px; border-radius: 4px; }
</style>
