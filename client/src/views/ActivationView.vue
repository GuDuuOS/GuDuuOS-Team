<script setup lang="ts">
/** OEM 节点受限态的首次管理员激活页。KEY 只在服务器环境变量中，前端仅发本人 token。 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { activateNode } from '@/matrix/client'
import { defaultHsUrl } from '@/config/hs'

const router = useRouter()
const busy = ref(false)
const error = ref('')
const nexusPortal = 'https://dev-nexus.guduu.co/portal/'
const deploymentDomain = window.location.hostname
const portalQuery = computed(() => `deployment_domain=${encodeURIComponent(deploymentDomain)}`)
const loginUrl = computed(() => `${nexusPortal}?${portalQuery.value}#oem-licenses`)
const registerUrl = computed(() => `${nexusPortal}?register=1&${portalQuery.value}#oem-licenses`)

async function activate() {
  busy.value = true
  error.value = ''
  try {
    await activateNode(defaultHsUrl())
    // 授权和业务配置是两个独立阶段。激活成功后直接进入
    // 首次配置向导，避免管理员在工作台里再寻找 Logo/AI/邮箱入口。
    router.replace({ path: '/setup', query: { activated: '1' } })
  } catch (err: any) {
    error.value = err?.message || '激活失败，请稍后重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="activation-page">
    <section class="activation-card">
      <p class="eyebrow">OEM 授权激活</p>
      <h1>第 1 步：激活此节点</h1>
      <p class="domain">当前部署域名：<b>{{ deploymentDomain }}</b></p>
      <p>系统会由服务器安全地向 GuDuu Nexus 验证授权、域名与来源 IP；长期授权码不会显示或发送到浏览器。</p>
      <p class="phase">本页只完成授权。成功后会自动进入第 2 步，配置品牌、邮箱与主 AI。</p>
      <p v-if="error" class="error">{{ error }}</p>
      <button :disabled="busy" @click="activate">{{ busy ? '正在激活…' : '重新验证并激活' }}</button>
      <div class="divider"><span>还没有可用授权？</span></div>
      <div class="actions">
        <a class="secondary" :href="loginUrl" target="_blank" rel="noopener">登录 OEM 并申请授权</a>
        <a class="secondary" :href="registerUrl" target="_blank" rel="noopener">注册成为 OEM</a>
      </div>
      <ol>
        <li>在 Nexus 完成 OEM 注册、授权申请与付款或审批。</li>
        <li>领取授权后，把 KEY 写入服务器安装配置。</li>
        <li>回到此页点击“重新验证并激活”。</li>
      </ol>
      <p class="support">网页发行版不提供免授权本地模式；授权未完成前，仅首次管理员可进入本页。</p>
    </section>
  </main>
</template>

<style scoped>
.activation-page{min-height:100vh;display:grid;place-items:center;padding:24px;background:var(--bg,#f7f6f2)}
.activation-card{max-width:520px;padding:32px;border-radius:18px;background:var(--panel,#fff);box-shadow:0 12px 40px #0001;color:var(--text,#24211c)}
.eyebrow{color:#9b6a2f;font-size:13px;font-weight:700}.domain{padding:10px 12px;border-radius:9px;background:#f5efe5}.phase{padding:10px 12px;border-left:3px solid #d98b3f;background:#fff7eb;color:#6b4c2d}.error{color:#b42318}button,.secondary{box-sizing:border-box;border:0;border-radius:9px;padding:11px 18px;font:inherit;cursor:pointer;text-align:center;text-decoration:none}button{width:100%;background:#1f6f54;color:#fff}button:disabled{opacity:.6;cursor:wait}.divider{display:flex;align-items:center;gap:10px;margin:22px 0 14px;color:#776f64;font-size:13px}.divider::before,.divider::after{content:"";height:1px;flex:1;background:#e5ded3}.actions{display:grid;grid-template-columns:1fr 1fr;gap:10px}.secondary{border:1px solid #d8cdbc;color:#5d4429;background:#fff}ol{padding-left:22px;color:#5e594f;line-height:1.7}.support{font-size:13px;color:#776f64}@media(max-width:520px){.actions{grid-template-columns:1fr}}
</style>
