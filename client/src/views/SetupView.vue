<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { instanceBrand, loadInstanceConfig } from '@/config/instance'
import { approvePendingNodeUpdate, getNodeAdminSettings, getPendingNodeUpdate, saveNodeAdminSettings, type PendingNodeUpdate } from '@/matrix/client'

const router = useRouter()
const step = ref(0)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const updateBusy = ref(false)
const pendingUpdate = ref<PendingNodeUpdate | null>(null)
const editing = computed(() => instanceBrand.setupCompleted)

const form = reactive({
  brand: { product_name: 'GuDuu OS', company_name: '', logo_data_url: '' },
  email: { host: '', port: 465, user: '', password: '', from_address: '', from_name: 'GuDuu OS', security: 'ssl', password_configured: false },
  ai: { provider: 'echo', model: '', base_url: '', api_key: '', api_key_configured: false },
  payment: { provider: 'none', mode: 'sandbox', merchant_id: '', secret_key: '', webhook_secret: '', secret_configured: false, webhook_configured: false, adapter_ready: false },
})

const steps = ['品牌', '发信邮箱', '主 AI', '支付', '确认']

onMounted(async () => {
  try {
    const value = await getNodeAdminSettings()
    Object.assign(form.brand, value.brand || {})
    Object.assign(form.email, value.email || {})
    Object.assign(form.ai, value.ai || {})
    Object.assign(form.payment, value.payment || {})
    pendingUpdate.value = await getPendingNodeUpdate()
  } catch (e: any) {
    error.value = e?.message || '只有服务器管理员可以完成首次配置'
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
      <div class="steps"><span v-for="(item, i) in steps" :key="item" :class="{ active: i === step, done: i < step }">{{ i + 1 }}. {{ item }}</span></div>
      <div v-if="loading" class="state">正在读取节点设置…</div>
      <div v-else class="body">
        <p v-if="error" class="error">{{ error }}</p>
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
          <h2>主 AI 与 API</h2><p class="hint">API Key 加密保存在本节点数据库，不会写入聊天配置或返回浏览器。</p>
          <label>提供方<select v-model="form.ai.provider"><option value="echo">暂不接入（Echo）</option><option value="claude">Anthropic Claude</option><option value="openai">OpenAI</option><option value="deepseek">DeepSeek / 方舟</option><option value="gemini">Google Gemini</option></select></label>
          <label>模型 ID<input v-model.trim="form.ai.model" placeholder="例如 deepseek-v3.2" /></label>
          <label>API Base URL（官方接口可留空）<input v-model.trim="form.ai.base_url" placeholder="https://api.example.com/v1" /></label>
          <label>API Key<input v-model="form.ai.api_key" type="password" :placeholder="form.ai.api_key_configured ? '已配置；留空保持不变' : 'sk-…'" /></label>
        </template>

        <template v-else-if="step === 3">
          <h2>支付方式</h2><p class="warn">当前节点支付适配器尚未完成真实下单与回调联调。这里可以预存配置，但系统会保持“待接入”，不会对客户开放收款。</p>
          <label>渠道<select v-model="form.payment.provider"><option value="none">暂不接入</option><option value="stripe">Stripe（待接入）</option><option value="paypal">PayPal（待接入）</option><option value="alipay">支付宝（待接入）</option><option value="wechat">微信支付（待接入）</option><option value="nowpayments">USDT / NOWPayments（待接入）</option></select></label>
          <div class="grid"><label>环境<select v-model="form.payment.mode"><option value="sandbox">沙箱/测试</option><option value="live">正式</option></select></label><label>商户号 / Client ID<input v-model.trim="form.payment.merchant_id" /></label></div>
          <label>渠道密钥<input v-model="form.payment.secret_key" type="password" :placeholder="form.payment.secret_configured ? '已配置；留空保持不变' : '请输入渠道密钥'" /></label>
          <label>Webhook 密钥<input v-model="form.payment.webhook_secret" type="password" :placeholder="form.payment.webhook_configured ? '已配置；留空保持不变' : '请输入回调验签密钥'" /></label>
        </template>

        <template v-else>
          <h2>确认配置</h2>
          <div class="summary"><b>{{ form.brand.product_name }}</b><span>邮箱：{{ form.email.host ? '已填写' : '稍后配置' }}</span><span>主 AI：{{ form.ai.provider }}</span><span>支付：{{ form.payment.provider === 'none' ? '暂不接入' : `${form.payment.provider}（待接入）` }}</span></div>
          <p class="hint">保存后进入工作台。以后可从管理后台“系统设置”再次修改。</p>
        </template>

        <footer><button v-if="step > 0" class="ghost" @click="step--">上一步</button><span /><button v-if="editing" class="ghost" @click="router.push('/')">取消</button><button v-if="step < steps.length - 1" @click="next">下一步</button><button v-else :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存并进入系统' }}</button></footer>
      </div>
    </section>
  </main>
</template>

<style scoped>
.setup-shell{min-height:100vh;padding:28px;background:linear-gradient(145deg,#fffaf2,#f6eadc);color:#2d2925;display:grid;place-items:center}.setup-card{width:min(820px,100%);min-height:620px;background:#fffdf9;border:1px solid #e7d9c9;border-radius:20px;box-shadow:0 20px 60px #68401b1c;overflow:hidden}.setup-head{display:flex;align-items:center;gap:14px;padding:24px 30px 18px}.setup-head img{width:48px;height:48px;object-fit:contain;border-radius:12px}.setup-head small{color:#a06b3d}.setup-head h1{font-size:24px;margin:3px 0 0}.steps{display:flex;gap:8px;padding:0 30px 18px;border-bottom:1px solid #eee1d3;overflow:auto}.steps span{white-space:nowrap;font-size:13px;color:#9b8e82;padding:7px 10px;border-radius:999px}.steps .active{background:#ef7d25;color:#fff}.steps .done{color:#c3611b}.body{padding:28px 30px}.body h2{font-size:20px;margin:0 0 6px}.hint{color:#8b7d70;font-size:14px;margin:0 0 22px}.body label{display:flex;flex-direction:column;gap:7px;font-size:13px;font-weight:650;margin:0 0 16px}.body input,.body select{width:100%;box-sizing:border-box;border:1px solid #d9cabb;border-radius:9px;background:#fff;padding:11px 12px;font:inherit;color:inherit}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.preview{width:72px;height:72px;object-fit:contain;border:1px solid #e3d5c7;border-radius:14px;padding:6px}.warn,.error{border-radius:10px;padding:11px 13px;font-size:13px;line-height:1.55}.warn{background:#fff3df;color:#9a551c}.error{background:#fff0ed;color:#b63f2e}.update-notice{display:flex;align-items:center;gap:16px;margin:0 0 20px;padding:13px;border:1px solid #e8c69f;background:#fff7eb;border-radius:11px}.update-notice div{display:grid;gap:3px;flex:1}.update-notice small{color:#8b6b4d}.summary{display:grid;gap:12px;padding:20px;border:1px solid #e7d8c9;border-radius:12px}.summary span{color:#75695e}footer{display:flex;gap:10px;align-items:center;margin-top:26px}footer span{flex:1}button{border:0;border-radius:9px;background:#e97822;color:#fff;padding:10px 17px;font-weight:700;cursor:pointer}button.ghost{background:#f2e8de;color:#6f6257}button:disabled{opacity:.55}.state{padding:40px 30px;color:#8b7d70}@media(max-width:640px){.setup-shell{padding:0}.setup-card{min-height:100vh;border-radius:0;border:0}.setup-head,.steps,.body{padding-left:18px;padding-right:18px}.grid{grid-template-columns:1fr}.steps{gap:2px}.steps span{font-size:12px;padding:6px}.update-notice{align-items:flex-start;flex-direction:column}}
</style>
