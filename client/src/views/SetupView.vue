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
const brandPolicy = reactive({
  instance_id: null as number | null,
  reserved_brand_allowed: false,
  reserved_brand: 'GuDuu OS',
  requires_custom_brand: true,
})

const form = reactive({
  brand: { product_name: '', company_name: '', logo_data_url: '' },
  website: {
    headline: '', description: '', contact_email: '', contact_phone: '',
    contact_address: '', support_url: '', privacy_url: '', footer_text: '',
  },
  email: { host: '', port: 465, user: '', password: '', from_address: '', from_name: '', security: 'ssl', password_configured: false },
  ai: { connection_mode: 'nexus', provider: 'deepseek', model: '', base_url: '', api_key: '', api_key_configured: false },
  payment: {
    alipay: { enabled: false, mode: 'sandbox', app_id: '', notify_url: '', private_key: '', alipay_public_key: '', private_key_configured: false, alipay_public_key_configured: false, adapter_ready: false },
    wechat: { enabled: false, mode: 'sandbox', mch_id: '', app_id: '', merchant_serial_no: '', platform_public_key_id: '', notify_url: '', api_v3_key: '', merchant_private_key: '', platform_public_key: '', api_v3_key_configured: false, merchant_private_key_configured: false, platform_public_key_configured: false, adapter_ready: false },
  },
})

const steps = ['品牌', '官网', '发信邮箱', '主 AI', '支付', '确认']
const paymentConfigured = computed(() => ({
  alipay: Boolean(form.payment.alipay.app_id && (form.payment.alipay.private_key_configured || form.payment.alipay.private_key)),
  wechat: Boolean(form.payment.wechat.mch_id && (form.payment.wechat.api_v3_key_configured || form.payment.wechat.api_v3_key)),
}))

function containsReservedBrand(value: string) {
  return value.normalize('NFKC').toLowerCase().replace(/[^a-z0-9]+/g, '').includes('guduuos')
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
    Object.assign(brandPolicy, value.brand_policy || {})
    Object.assign(form.brand, value.brand || {})
    Object.assign(form.website, value.website || {})
    Object.assign(form.email, value.email || {})
    Object.assign(form.ai, value.ai || {})
    Object.assign(form.payment.alipay, value.payment?.alipay || {})
    Object.assign(form.payment.wechat, value.payment?.wechat || {})
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
  if (step.value === 0 && brandPolicy.requires_custom_brand && [
    form.brand.product_name,
    form.brand.company_name,
  ].some(containsReservedBrand)) {
    error.value = '当前 OEM 节点必须使用自有品牌，不得使用 GuDuu OS 保留字样。'
    return
  }
  if (step.value === 1 && !form.website.headline.trim()) {
    error.value = '请先填写官网主标题'
    return
  }
  if (step.value === 1 && brandPolicy.requires_custom_brand && [
    form.website.headline,
    form.website.description,
    form.website.contact_email,
    form.website.contact_address,
    form.website.support_url,
    form.website.privacy_url,
    form.website.footer_text,
  ].some(containsReservedBrand)) {
    error.value = '当前 OEM 官网不得使用 GuDuu OS 保留字样。'
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
    await router.replace('/app')
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
        <img v-if="form.brand.logo_data_url || (brandPolicy.reserved_brand_allowed && instanceBrand.logoUrl)" :src="form.brand.logo_data_url || instanceBrand.logoUrl" alt="" />
        <div><small>{{ brandPolicy.reserved_brand_allowed ? 'GuDuu OS · 官方节点' : 'OEM 节点配置' }}</small><h1>{{ editing ? '系统设置' : '完成首次部署' }}</h1></div>
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
        <p v-if="route.query.activated === '1'" class="success">授权激活已完成。下面继续配置品牌官网、邮箱、主 AI 与支付渠道。</p>
        <div v-if="pendingUpdate" class="update-notice">
          <div><b>发现可选更新 {{ pendingUpdate.current_version }} → {{ pendingUpdate.version }}</b><small>{{ pendingUpdate.title }}</small></div>
          <button :disabled="updateBusy" @click="approveUpdate">{{ updateBusy ? '确认中…' : '确认安装' }}</button>
        </div>

        <template v-if="step === 0">
          <h2>品牌名称与 Logo</h2><p class="hint">登录页、工作台和管理后台会使用这里的品牌。</p>
          <p v-if="brandPolicy.requires_custom_brand" class="warn">当前为外部 OEM 节点，必须填写您自己的产品名称。“GuDuu OS”及空格、连字符等变体为保留品牌，仅节点 #1、#2、#3 可使用。</p>
          <label>产品名称<input v-model.trim="form.brand.product_name" placeholder="例如：星海协作 OS" /></label>
          <label>企业/组织名称<input v-model.trim="form.brand.company_name" placeholder="例如：星海科技有限公司" /></label>
          <label>Logo（最大 512KB）<input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" @change="chooseLogo" /></label>
          <img v-if="form.brand.logo_data_url" class="preview" :src="form.brand.logo_data_url" alt="Logo 预览" />
        </template>

        <template v-else-if="step === 1">
          <h2>官网内容与联系方式</h2><p class="hint">官网已包含在同一个 Web 镜像中，访问部署域名根路径即可看到。名称与 Logo 直接使用上一步的品牌配置。</p>
          <p v-if="brandPolicy.requires_custom_brand" class="warn">官网主标题、介绍和页脚文案同样不得使用 GuDuu OS 保留品牌。</p>
          <label>官网主标题<input v-model.trim="form.website.headline" placeholder="例如：让团队协作更简单" /></label>
          <label>官网介绍<textarea v-model.trim="form.website.description" rows="3" placeholder="简要介绍产品定位与服务能力" /></label>
          <div class="grid"><label>联系邮箱<input v-model.trim="form.website.contact_email" type="email" placeholder="service@example.com" /></label><label>联系电话<input v-model.trim="form.website.contact_phone" placeholder="+86 10 8888 8888" /></label></div>
          <label>联系地址<input v-model.trim="form.website.contact_address" placeholder="企业办公或服务地址" /></label>
          <div class="grid"><label>帮助中心链接<input v-model.trim="form.website.support_url" placeholder="https://support.example.com" /></label><label>隐私政策链接<input v-model.trim="form.website.privacy_url" placeholder="https://example.com/privacy" /></label></div>
          <label>页脚版权文案<input v-model.trim="form.website.footer_text" :placeholder="`留空则自动显示 © 年份 ${form.brand.company_name || form.brand.product_name}`" /></label>
        </template>

        <template v-else-if="step === 2">
          <h2>发信邮箱</h2><p class="hint">用于注册、登录验证和找回密码。暂时不启用可以留空。</p>
          <div class="grid"><label>SMTP 主机<input v-model.trim="form.email.host" placeholder="smtp.example.com" /></label><label>端口<input v-model.number="form.email.port" type="number" /></label></div>
          <div class="grid"><label>SMTP 用户<input v-model.trim="form.email.user" /></label><label>发件地址<input v-model.trim="form.email.from_address" placeholder="noreply@example.com" /></label></div>
          <label>SMTP 密码<input v-model="form.email.password" type="password" :placeholder="form.email.password_configured ? '已配置；留空保持不变' : '请输入 SMTP 密码'" /></label>
          <div class="grid"><label>发件人名称<input v-model.trim="form.email.from_name" /></label><label>连接安全<select v-model="form.email.security"><option value="ssl">SSL/TLS</option><option value="starttls">STARTTLS</option></select></label></div>
        </template>

        <template v-else-if="step === 3">
          <h2>主 AI 与 API</h2><p class="hint">可直接使用我们提供的官方 AI，也可接入您自己购买的模型 API；以后可随时切换。</p>
          <div class="ai-mode-grid">
            <label class="ai-mode-card" :class="{ selected: form.ai.connection_mode === 'nexus' }">
              <input v-model="form.ai.connection_mode" type="radio" value="nexus" />
              <span><b>使用{{ brandPolicy.reserved_brand_allowed ? ' GuDuu Nexus' : '平台' }}官方 AI</b><small>无需填写 API Key，使用 OEM 授权与平台 Token 结算。</small></span>
            </label>
            <label class="ai-mode-card" :class="{ selected: form.ai.connection_mode === 'direct' }">
              <input v-model="form.ai.connection_mode" type="radio" value="direct" />
              <span><b>使用企业自有 API</b><small>自选 OpenAI、Claude、DeepSeek 或 Gemini，费用由企业直接承担。</small></span>
            </label>
          </div>
          <p v-if="form.ai.connection_mode === 'nexus'" class="mode-note">无需在浏览器输入 API Key；节点使用服务器内的 OEM 授权连接 Nexus，用量按平台 Token 结算。</p>
          <p v-else class="mode-note">您的 API Key 仅加密保存在本节点数据库，不写入聊天配置或返回浏览器。</p>
          <label>提供方<select v-model="form.ai.provider"><option v-if="form.ai.connection_mode === 'direct'" value="echo">暂不接入（Echo）</option><option value="claude">Anthropic Claude</option><option value="openai">OpenAI</option><option value="deepseek">DeepSeek / 方舟</option><option v-if="form.ai.connection_mode === 'direct'" value="gemini">Google Gemini</option></select></label>
          <label>模型 ID<input v-model.trim="form.ai.model" placeholder="例如 deepseek-v3.2" /></label>
          <label v-if="form.ai.connection_mode === 'direct'">API Base URL（官方接口可留空）<input v-model.trim="form.ai.base_url" placeholder="https://api.example.com/v1" /></label>
          <label v-if="form.ai.connection_mode === 'direct'">API Key<input v-model="form.ai.api_key" type="password" :placeholder="form.ai.api_key_configured ? '已配置；留空保持不变' : 'sk-…'" /></label>
        </template>

        <template v-else-if="step === 4">
          <h2>支付 API 对接</h2>
          <p class="hint">填写 OEM 企业自己的支付宝与微信支付凭据。密钥只加密保存在当前节点，页面不会回显原文。</p>
          <p class="warn">当前页面用于提前完成凭据配置。各渠道在适配器完成、回调验签与沙箱交易验收前，不会被标记为正式收款上线。</p>

          <section class="payment-card">
            <div class="payment-title">
              <div><b>支付宝开放平台</b><small>RSA2 应用私钥 + 支付宝公钥</small></div>
              <label class="switch-row"><input v-model="form.payment.alipay.enabled" type="checkbox" /> 凭据齐全后计划启用</label>
            </div>
            <div class="grid"><label>环境<select v-model="form.payment.alipay.mode"><option value="sandbox">沙箱</option><option value="live">生产</option></select></label><label>APPID<input v-model.trim="form.payment.alipay.app_id" placeholder="2021…" /></label></div>
            <label>异步通知地址<input v-model.trim="form.payment.alipay.notify_url" placeholder="https://pay.example.com/cosmac/pay/callback/alipay" /></label>
            <label>应用私钥<textarea v-model="form.payment.alipay.private_key" rows="4" :placeholder="form.payment.alipay.private_key_configured ? '已加密配置；留空保持不变' : '粘贴 PEM 私钥'" /></label>
            <label>支付宝公钥<textarea v-model="form.payment.alipay.alipay_public_key" rows="4" :placeholder="form.payment.alipay.alipay_public_key_configured ? '已加密配置；留空保持不变' : '粘贴支付宝公钥'" /></label>
            <p class="credential-state">{{ form.payment.alipay.adapter_ready ? '适配器已就绪' : '待适配器与沙箱交易验收' }} · {{ paymentConfigured.alipay ? '凭据已配置' : '凭据未配齐' }}</p>
          </section>

          <section class="payment-card">
            <div class="payment-title">
              <div><b>微信支付 API v3</b><small>商户 APIv3 密钥 + 商户私钥 + 平台公钥</small></div>
              <label class="switch-row"><input v-model="form.payment.wechat.enabled" type="checkbox" /> 凭据齐全后计划启用</label>
            </div>
            <div class="grid"><label>环境<select v-model="form.payment.wechat.mode"><option value="sandbox">沙箱/联调</option><option value="live">生产</option></select></label><label>商户号 mchid<input v-model.trim="form.payment.wechat.mch_id" /></label></div>
            <div class="grid"><label>AppID<input v-model.trim="form.payment.wechat.app_id" /></label><label>商户证书序列号<input v-model.trim="form.payment.wechat.merchant_serial_no" /></label></div>
            <label>微信支付公钥 ID<input v-model.trim="form.payment.wechat.platform_public_key_id" placeholder="PUB_KEY_ID_…" /></label>
            <label>异步通知地址<input v-model.trim="form.payment.wechat.notify_url" placeholder="https://pay.example.com/cosmac/pay/callback/wechat" /></label>
            <label>APIv3 密钥（正好 32 字节）<input v-model="form.payment.wechat.api_v3_key" type="password" :placeholder="form.payment.wechat.api_v3_key_configured ? '已加密配置；留空保持不变' : '输入 32 字节 APIv3 密钥'" /></label>
            <label>商户私钥<textarea v-model="form.payment.wechat.merchant_private_key" rows="4" :placeholder="form.payment.wechat.merchant_private_key_configured ? '已加密配置；留空保持不变' : '粘贴 PEM 私钥'" /></label>
            <label>微信支付平台公钥<textarea v-model="form.payment.wechat.platform_public_key" rows="4" :placeholder="form.payment.wechat.platform_public_key_configured ? '已加密配置；留空保持不变' : '粘贴平台公钥'" /></label>
            <p class="credential-state">{{ form.payment.wechat.adapter_ready ? '适配器已就绪' : '待适配器与沙箱交易验收' }} · {{ paymentConfigured.wechat ? '凭据已配置' : '凭据未配齐' }}</p>
          </section>
        </template>

        <template v-else>
          <h2>确认配置</h2>
          <div class="summary"><b>{{ form.brand.product_name }}</b><span>官网：已包含 · {{ form.website.contact_email || form.website.contact_phone || '联系方式稍后补充' }}</span><span>邮箱：{{ form.email.host ? '已填写' : '稍后配置' }}</span><span>主 AI：{{ form.ai.connection_mode === 'nexus' ? '平台官方 AI' : '企业自有 API' }} · {{ form.ai.provider }}</span><span>支付 API：支付宝 {{ paymentConfigured.alipay ? '已配置' : '稍后配置' }} · 微信支付 {{ paymentConfigured.wechat ? '已配置' : '稍后配置' }}</span></div>
          <p class="hint">保存后进入工作台。以后可从管理后台“系统设置”再次修改。</p>
        </template>

        <footer><button v-if="step > 0" class="ghost" @click="step--">上一步</button><span /><button v-if="editing" class="ghost" @click="router.push('/app')">取消</button><button v-if="step < steps.length - 1" @click="next">下一步</button><button v-else :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存并进入系统' }}</button></footer>
      </div>
    </section>
  </main>
</template>

<style scoped>
.setup-shell{min-height:100vh;padding:28px;background:linear-gradient(145deg,#fffaf2,#f6eadc);color:#2d2925;display:grid;place-items:center}.setup-card{width:min(820px,100%);min-height:620px;background:#fffdf9;border:1px solid #e7d9c9;border-radius:20px;box-shadow:0 20px 60px #68401b1c;overflow:hidden}.setup-head{display:flex;align-items:center;gap:14px;padding:24px 30px 18px}.setup-head img{width:48px;height:48px;object-fit:contain;border-radius:12px}.setup-head small{color:#a06b3d}.setup-head h1{font-size:24px;margin:3px 0 0}.steps{display:flex;gap:8px;padding:0 30px 18px;border-bottom:1px solid #eee1d3;overflow:auto}.steps span{white-space:nowrap;font-size:13px;color:#9b8e82;padding:7px 10px;border-radius:999px}.steps .active{background:#ef7d25;color:#fff}.steps .done{color:#c3611b}.body{padding:28px 30px}.body h2{font-size:20px;margin:0 0 6px}.hint{color:#8b7d70;font-size:14px;margin:0 0 22px}.body label{display:flex;flex-direction:column;gap:7px;font-size:13px;font-weight:650;margin:0 0 16px}.body input,.body select,.body textarea{width:100%;box-sizing:border-box;border:1px solid #d9cabb;border-radius:9px;background:#fff;padding:11px 12px;font:inherit;color:inherit}.body textarea{resize:vertical;line-height:1.45}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.preview{width:72px;height:72px;object-fit:contain;border:1px solid #e3d5c7;border-radius:14px;padding:6px}.warn,.error,.success{border-radius:10px;padding:11px 13px;font-size:13px;line-height:1.55}.warn{background:#fff3df;color:#9a551c}.error{background:#fff0ed;color:#b63f2e}.success{background:#edf9f1;color:#237444}.load-failed{max-width:620px}.update-notice{display:flex;align-items:center;gap:16px;margin:0 0 20px;padding:13px;border:1px solid #e8c69f;background:#fff7eb;border-radius:11px}.update-notice div{display:grid;gap:3px;flex:1}.update-notice small{color:#8b6b4d}.payment-card{margin:16px 0;padding:18px;border:1px solid #e7d8c9;border-radius:13px;background:#fffaf4}.payment-title{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:15px}.payment-title>div{display:grid;gap:4px}.payment-title small,.credential-state{color:#8b7d70;font-size:12px}.switch-row{flex-direction:row!important;align-items:center;white-space:nowrap;margin:0!important}.switch-row input{width:auto}.credential-state{margin:2px 0 0}.summary{display:grid;gap:12px;padding:20px;border:1px solid #e7d8c9;border-radius:12px}.summary span{color:#75695e}footer{display:flex;gap:10px;align-items:center;margin-top:26px}footer span{flex:1}button{border:0;border-radius:9px;background:#e97822;color:#fff;padding:10px 17px;font-weight:700;cursor:pointer}button.ghost{background:#f2e8de;color:#6f6257}button:disabled{opacity:.55}.state{padding:40px 30px;color:#8b7d70}@media(max-width:640px){.setup-shell{padding:0}.setup-card{min-height:100vh;border-radius:0;border:0}.setup-head,.steps,.body{padding-left:18px;padding-right:18px}.grid{grid-template-columns:1fr}.steps{gap:2px}.steps span{font-size:12px;padding:6px}.update-notice,.payment-title{align-items:flex-start;flex-direction:column}}
.mode-note{margin:-8px 0 18px;padding:10px 12px;border-left:3px solid #dc8a3c;background:#fff8ef;color:#765332;font-size:13px;line-height:1.55}
.ai-mode-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:0 0 18px}.body .ai-mode-card{display:flex;flex-direction:row;align-items:flex-start;gap:11px;margin:0;padding:15px;border:1px solid #decdbc;border-radius:12px;background:#fff;cursor:pointer}.body .ai-mode-card.selected{border-color:#e97822;background:#fff7ed;box-shadow:0 0 0 2px #e978221c}.body .ai-mode-card input{width:auto;margin:3px 0 0}.ai-mode-card span{display:grid;gap:5px}.ai-mode-card small{color:#7f7165;font-weight:400;line-height:1.45}@media(max-width:640px){.ai-mode-grid{grid-template-columns:1fr}.payment-card{padding:14px}}
</style>
