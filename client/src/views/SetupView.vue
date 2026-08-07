<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { instanceBrand, loadInstanceConfig } from '@/config/instance'
import { approvePendingNodeUpdate, currentUserId, getClient, getNodeAdminSettings, getPendingNodeUpdate, restoreSession, saveNodeAdminSettings, type PendingNodeUpdate } from '@/matrix/client'

const router = useRouter()
const route = useRoute()
const step = ref(0)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const loadFailed = ref(false)
const updateBusy = ref(false)
const pendingUpdate = ref<PendingNodeUpdate | null>(null)
const editing = computed(() => instanceBrand.setupCompleted)

const form = reactive({
  brand: { product_name: 'GuDuu OS', company_name: '', logo_data_url: '' },
  email: { host: '', port: 465, user: '', password: '', from_address: '', from_name: 'GuDuu OS', security: 'ssl', password_configured: false },
  ai: { connection_mode: 'nexus', provider: 'deepseek', model: '', base_url: '', api_key: '', api_key_configured: false },
  payment: {
    alipay: { enabled: false, mode: 'sandbox', app_id: '', notify_url: '', private_key: '', alipay_public_key: '', private_key_configured: false, alipay_public_key_configured: false, adapter_ready: false },
    wechat: { enabled: false, mode: 'sandbox', mch_id: '', app_id: '', merchant_serial_no: '', platform_public_key_id: '', notify_url: '', api_v3_key: '', merchant_private_key: '', platform_public_key: '', api_v3_key_configured: false, merchant_private_key_configured: false, platform_public_key_configured: false, adapter_ready: false },
  },
})

const steps = ['品牌', '发信邮箱', '主 AI', '支付', '确认']

function paymentCallback(provider: 'alipay' | 'wechat') {
  // Electron/Capacitor 的页面 origin 不是 OEM 公网域名；回调必须取当前
  // Matrix homeserver，才能让支付平台真正访问到该节点。
  const client = getClient() as any
  const base = String(client?.getHomeserverUrl?.() || client?.baseUrl || window.location.origin)
  return `${base.replace(/\/$/, '')}/cosmac/pay/callback/${provider}`
}

watch(() => form.ai.connection_mode, (mode) => {
  // Nexus 网关尚未开放 Echo/Gemini 路由；切换模式时立即收敛为
  // 已支持的默认提供方，避免下拉框隐藏了当前值却在保存时才报错。
  if (mode === 'nexus' && !['claude', 'openai', 'deepseek', 'ark'].includes(form.ai.provider)) {
    form.ai.provider = 'deepseek'
  }
})

onMounted(async () => {
  try {
    // SetupView 不经过 LiveView，刷新 /setup 时 Matrix client 仍是空。
    // 必须先从 Web 会话或 Electron safeStorage 恢复真实会话，
    // 再调用管理员 API，不能只相信可篡改的用户 ID 元数据。
    const uid = getClient() ? currentUserId() : await restoreSession()
    if (!uid) {
      await router.replace({ path: '/login', query: { redirect: route.fullPath } })
      return
    }
    const value = await getNodeAdminSettings()
    Object.assign(form.brand, value.brand || {})
    Object.assign(form.email, value.email || {})
    Object.assign(form.ai, value.ai || {})
    Object.assign(form.payment.alipay, value.payment?.alipay || {})
    Object.assign(form.payment.wechat, value.payment?.wechat || {})
    if (!form.payment.alipay.notify_url) form.payment.alipay.notify_url = paymentCallback('alipay')
    if (!form.payment.wechat.notify_url) form.payment.wechat.notify_url = paymentCallback('wechat')
    pendingUpdate.value = await getPendingNodeUpdate()
  } catch (e: any) {
    loadFailed.value = true
    const message = String(e?.message || '')
    error.value = message === '尚未连接服务器'
      ? '登录状态尚未恢复，请重新登录管理员账号后再完成配置。'
      : message || '无法读取节点设置，请确认使用的是服务器管理员账号。'
  } finally {
    loading.value = false
  }
})

function chooseLogo(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/') || file.size > 512 * 1024) {
    error.value = '请选择 512KB 以内的 PNG、JPG、WebP 或 SVG 图片'
    return
  }
  const reader = new FileReader()
  reader.onload = () => { form.brand.logo_data_url = String(reader.result || '') }
  reader.readAsDataURL(file)
}

function next() {
  error.value = ''
  if (step.value === 0 && !form.brand.product_name.trim()) {
    error.value = '请先填写产品名称'
    return
  }
  step.value = Math.min(steps.length - 1, step.value + 1)
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    await saveNodeAdminSettings({ ...form, setup_completed: true })
    await loadInstanceConfig(true)
    await router.replace('/')
  } catch (e: any) {
    error.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

async function approveUpdate() {
  if (!pendingUpdate.value || !confirm(`确认安装 ${pendingUpdate.value.version}？安装前会自动备份并在失败时回撤。`)) return
  updateBusy.value = true
  error.value = ''
  try {
    await approvePendingNodeUpdate(pendingUpdate.value.release_id)
    alert('已确认。宿主更新代理将在下一轮检查时主动拉取并安装；这不是平台强制推送。')
  } catch (e: any) {
    error.value = e?.message || '批准更新失败'
  } finally {
    updateBusy.value = false
  }
}
</script>

<template>
  <main class="setup-shell">
    <section class="setup-card">
      <header class="setup-head">
        <img :src="form.brand.logo_data_url || instanceBrand.logoUrl" alt="" />
        <div><small>GuDuu OS · OEM 节点</small><h1>{{ editing ? '系统设置' : '完成首次部署' }}</h1></div>
      </header>
      <div v-if="!loadFailed" class="steps"><span v-for="(item, i) in steps" :key="item" :class="{ active: i === step, done: i < step }">{{ i + 1 }}. {{ item }}</span></div>
      <div v-if="loading" class="state">正在读取节点设置…</div>
      <div v-else-if="loadFailed" class="body load-failed">
        <p class="error">{{ error }}</p>
        <p class="hint">当前未保存任何新配置，也不会默认跳过首次设置。</p>
        <div><button @click="router.replace({ path: '/login', query: { redirect: '/setup' } })">重新登录管理员</button></div>
      </div>
      <div v-else class="body">
        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="route.query.activated === '1'" class="success">授权激活已完成。下面继续配置品牌、邮箱、主 AI 与支付信息。</p>
        <div v-if="pendingUpdate" class="update-notice">
          <div><b>发现可选更新 {{ pendingUpdate.current_version }} → {{ pendingUpdate.version }}</b><small>{{ pendingUpdate.title }}</small></div>
          <button :disabled="updateBusy" @click="approveUpdate">{{ updateBusy ? '确认中…' : '确认安装' }}</button>
        </div>

        <template v-if="step === 0">
          <h2>品牌名称与 Logo</h2><p class="hint">登录页、工作台和管理后台会使用这里的品牌。</p>
          <label>产品名称<input v-model.trim="form.brand.product_name" placeholder="例如：星海协作 OS" /></label>
          <label>企业/组织名称<input v-model.trim="form.brand.company_name" placeholder="例如：星海科技有限公司" /></label>
          <label>Logo（最大 512KB）<input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" @change="chooseLogo" /></label>
          <img v-if="form.brand.logo_data_url" class="preview" :src="form.brand.logo_data_url" alt="Logo 预览" />
        </template>

        <template v-else-if="step === 1">
          <h2>发信邮箱</h2><p class="hint">用于注册、登录验证和找回密码。暂时不启用可以留空。</p>
          <div class="grid"><label>SMTP 主机<input v-model.trim="form.email.host" placeholder="smtp.example.com" /></label><label>端口<input v-model.number="form.email.port" type="number" /></label></div>
          <div class="grid"><label>SMTP 用户<input v-model.trim="form.email.user" /></label><label>发件地址<input v-model.trim="form.email.from_address" placeholder="noreply@example.com" /></label></div>
          <label>SMTP 密码<input v-model="form.email.password" type="password" :placeholder="form.email.password_configured ? '已配置；留空保持不变' : '请输入 SMTP 密码'" /></label>
          <div class="grid"><label>发件人名称<input v-model.trim="form.email.from_name" /></label><label>连接安全<select v-model="form.email.security"><option value="ssl">SSL/TLS</option><option value="starttls">STARTTLS</option></select></label></div>
        </template>

        <template v-else-if="step === 2">
          <h2>主 AI 与 API</h2><p class="hint">先选择使用平台网关还是自有 API。两种模式都可以以后在“系统设置”中切换。</p>
          <label>接入方式<select v-model="form.ai.connection_mode"><option value="nexus">GuDuu Nexus AI 网关（使用 OEM 授权）</option><option value="direct">自有 API（费用由本企业承担）</option></select></label>
          <p v-if="form.ai.connection_mode === 'nexus'" class="mode-note">无需在浏览器输入 API Key；节点使用服务器内的 OEM 授权连接 Nexus，用量按平台 Token 结算。</p>
          <p v-else class="mode-note">您的 API Key 仅加密保存在本节点数据库，不写入聊天配置或返回浏览器。</p>
          <label>提供方<select v-model="form.ai.provider"><option v-if="form.ai.connection_mode === 'direct'" value="echo">暂不接入（Echo）</option><option value="claude">Anthropic Claude</option><option value="openai">OpenAI</option><option value="deepseek">DeepSeek / 方舟</option><option v-if="form.ai.connection_mode === 'direct'" value="gemini">Google Gemini</option></select></label>
          <label>模型 ID<input v-model.trim="form.ai.model" placeholder="例如 deepseek-v3.2" /></label>
          <label v-if="form.ai.connection_mode === 'direct'">API Base URL（官方接口可留空）<input v-model.trim="form.ai.base_url" placeholder="https://api.example.com/v1" /></label>
          <label v-if="form.ai.connection_mode === 'direct'">API Key<input v-model="form.ai.api_key" type="password" :placeholder="form.ai.api_key_configured ? '已配置；留空保持不变' : 'sk-…'" /></label>
        </template>

        <template v-else-if="step === 3">
          <h2>支付宝与微信支付 API</h2>
          <p class="warn">凭据会加密保存在本节点数据库，保存后不再回显。当前先完成配置入口；只有真实下单、回调验签和沙箱交易全部验收后，渠道才会显示“可收款”。</p>

          <section class="payment-card">
            <div class="payment-title"><div><b>支付宝开放平台</b><small>RSA2 · 可与微信支付同时启用</small></div><label class="switch-row"><input v-model="form.payment.alipay.enabled" type="checkbox" /> 启用配置</label></div>
            <template v-if="form.payment.alipay.enabled">
              <div class="grid"><label>运行环境<select v-model="form.payment.alipay.mode"><option value="sandbox">沙箱/测试</option><option value="live">正式</option></select></label><label>支付宝 APPID<input v-model.trim="form.payment.alipay.app_id" placeholder="例如 202100xxxxxxxxxx" /></label></div>
              <label>异步通知地址<input v-model.trim="form.payment.alipay.notify_url" /></label>
              <label>RSA2 应用私钥<textarea v-model="form.payment.alipay.private_key" rows="4" :placeholder="form.payment.alipay.private_key_configured ? '已配置；留空保持不变' : '粘贴应用私钥（支持 PEM 或单行内容）'" /></label>
              <label>支付宝公钥<textarea v-model="form.payment.alipay.alipay_public_key" rows="4" :placeholder="form.payment.alipay.alipay_public_key_configured ? '已配置；留空保持不变' : '粘贴支付宝公钥，用于回调验签'" /></label>
              <p class="credential-state">应用私钥：{{ form.payment.alipay.private_key_configured ? '已保存' : '未保存' }} · 支付宝公钥：{{ form.payment.alipay.alipay_public_key_configured ? '已保存' : '未保存' }}</p>
            </template>
          </section>

          <section class="payment-card">
            <div class="payment-title"><div><b>微信支付 API v3</b><small>商户证书 + APIv3 回调验签</small></div><label class="switch-row"><input v-model="form.payment.wechat.enabled" type="checkbox" /> 启用配置</label></div>
            <template v-if="form.payment.wechat.enabled">
              <div class="grid"><label>运行环境<select v-model="form.payment.wechat.mode"><option value="sandbox">测试配置</option><option value="live">正式</option></select></label><label>商户号 mchid<input v-model.trim="form.payment.wechat.mch_id" /></label></div>
              <div class="grid"><label>应用 AppID<input v-model.trim="form.payment.wechat.app_id" /></label><label>商户证书序列号<input v-model.trim="form.payment.wechat.merchant_serial_no" /></label></div>
              <label>微信支付公钥 ID<input v-model.trim="form.payment.wechat.platform_public_key_id" placeholder="PUB_KEY_ID_…" /></label>
              <label>异步通知地址<input v-model.trim="form.payment.wechat.notify_url" /></label>
              <label>APIv3 密钥<input v-model="form.payment.wechat.api_v3_key" type="password" maxlength="32" :placeholder="form.payment.wechat.api_v3_key_configured ? '已配置；留空保持不变' : '必须为 32 字节'" /></label>
              <label>商户 API 私钥<textarea v-model="form.payment.wechat.merchant_private_key" rows="4" :placeholder="form.payment.wechat.merchant_private_key_configured ? '已配置；留空保持不变' : '粘贴 apiclient_key.pem 内容'" /></label>
              <label>微信支付平台公钥<textarea v-model="form.payment.wechat.platform_public_key" rows="4" :placeholder="form.payment.wechat.platform_public_key_configured ? '已配置；留空保持不变' : '粘贴与公钥 ID 对应的平台公钥'" /></label>
              <p class="credential-state">APIv3：{{ form.payment.wechat.api_v3_key_configured ? '已保存' : '未保存' }} · 商户私钥：{{ form.payment.wechat.merchant_private_key_configured ? '已保存' : '未保存' }} · 平台公钥：{{ form.payment.wechat.platform_public_key_configured ? '已保存' : '未保存' }}</p>
            </template>
          </section>
        </template>

        <template v-else>
          <h2>确认配置</h2>
          <div class="summary"><b>{{ form.brand.product_name }}</b><span>邮箱：{{ form.email.host ? '已填写' : '稍后配置' }}</span><span>主 AI：{{ form.ai.connection_mode === 'nexus' ? 'Nexus 网关' : '自有 API' }} · {{ form.ai.provider }}</span><span>支付：{{ [form.payment.alipay.enabled ? '支付宝' : '', form.payment.wechat.enabled ? '微信支付' : ''].filter(Boolean).join('、') || '暂不接入' }}{{ form.payment.alipay.enabled || form.payment.wechat.enabled ? '（待联调）' : '' }}</span></div>
          <p class="hint">保存后进入工作台。以后可从管理后台“系统设置”再次修改。</p>
        </template>

        <footer><button v-if="step > 0" class="ghost" @click="step--">上一步</button><span /><button v-if="editing" class="ghost" @click="router.push('/')">取消</button><button v-if="step < steps.length - 1" @click="next">下一步</button><button v-else :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存并进入系统' }}</button></footer>
      </div>
    </section>
  </main>
</template>

<style scoped>
.setup-shell{min-height:100vh;padding:28px;background:linear-gradient(145deg,#fffaf2,#f6eadc);color:#2d2925;display:grid;place-items:center}.setup-card{width:min(820px,100%);min-height:620px;background:#fffdf9;border:1px solid #e7d9c9;border-radius:20px;box-shadow:0 20px 60px #68401b1c;overflow:hidden}.setup-head{display:flex;align-items:center;gap:14px;padding:24px 30px 18px}.setup-head img{width:48px;height:48px;object-fit:contain;border-radius:12px}.setup-head small{color:#a06b3d}.setup-head h1{font-size:24px;margin:3px 0 0}.steps{display:flex;gap:8px;padding:0 30px 18px;border-bottom:1px solid #eee1d3;overflow:auto}.steps span{white-space:nowrap;font-size:13px;color:#9b8e82;padding:7px 10px;border-radius:999px}.steps .active{background:#ef7d25;color:#fff}.steps .done{color:#c3611b}.body{padding:28px 30px}.body h2{font-size:20px;margin:0 0 6px}.hint{color:#8b7d70;font-size:14px;margin:0 0 22px}.body label{display:flex;flex-direction:column;gap:7px;font-size:13px;font-weight:650;margin:0 0 16px}.body input,.body select,.body textarea{width:100%;box-sizing:border-box;border:1px solid #d9cabb;border-radius:9px;background:#fff;padding:11px 12px;font:inherit;color:inherit}.body textarea{resize:vertical;line-height:1.45}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.preview{width:72px;height:72px;object-fit:contain;border:1px solid #e3d5c7;border-radius:14px;padding:6px}.warn,.error,.success{border-radius:10px;padding:11px 13px;font-size:13px;line-height:1.55}.warn{background:#fff3df;color:#9a551c}.error{background:#fff0ed;color:#b63f2e}.success{background:#edf9f1;color:#237444}.load-failed{max-width:620px}.update-notice{display:flex;align-items:center;gap:16px;margin:0 0 20px;padding:13px;border:1px solid #e8c69f;background:#fff7eb;border-radius:11px}.update-notice div{display:grid;gap:3px;flex:1}.update-notice small{color:#8b6b4d}.payment-card{margin:16px 0;padding:18px;border:1px solid #e7d8c9;border-radius:13px;background:#fffaf4}.payment-title{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:15px}.payment-title>div{display:grid;gap:4px}.payment-title small,.credential-state{color:#8b7d70;font-size:12px}.switch-row{flex-direction:row!important;align-items:center;white-space:nowrap;margin:0!important}.switch-row input{width:auto}.credential-state{margin:2px 0 0}.summary{display:grid;gap:12px;padding:20px;border:1px solid #e7d8c9;border-radius:12px}.summary span{color:#75695e}footer{display:flex;gap:10px;align-items:center;margin-top:26px}footer span{flex:1}button{border:0;border-radius:9px;background:#e97822;color:#fff;padding:10px 17px;font-weight:700;cursor:pointer}button.ghost{background:#f2e8de;color:#6f6257}button:disabled{opacity:.55}.state{padding:40px 30px;color:#8b7d70}@media(max-width:640px){.setup-shell{padding:0}.setup-card{min-height:100vh;border-radius:0;border:0}.setup-head,.steps,.body{padding-left:18px;padding-right:18px}.grid{grid-template-columns:1fr}.steps{gap:2px}.steps span{font-size:12px;padding:6px}.update-notice,.payment-title{align-items:flex-start;flex-direction:column}}
.mode-note{margin:-8px 0 18px;padding:10px 12px;border-left:3px solid #dc8a3c;background:#fff8ef;color:#765332;font-size:13px;line-height:1.55}
</style>
