<script setup lang="ts">
import Icon from '@/components/Icon.vue'
/**
 * 独立登录 / 注册 / 找回密码页（方案A：把认证从 199KB 的 LiveView 巨石里抽出来）。
 *
 * 为什么独立成页：
 *   - 之前认证是 LiveView 里一段 `v-if="!loggedIn"`，登录页必须等整个 app 加载完才显示，
 *     且已登录用户刷新会「闪一下登录框」。抽成独立路由后：登录页秒开、不闪、有自己的地址。
 * 交接机制（关键）：
 *   - 用「只认证不启动客户端」的 loginNoStart/loginWithEmailNoStart：认证成功只写会话到
 *     localStorage，然后 `router.push('/')` 进主应用，由 LiveView 挂载时 restoreSession
 *     做**唯一一次**同步。既不双同步、也无需整页 reload。
 *   - 视觉与原登录块保持一致（同一套 class + 样式），只改架构不改观感。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import logoUrl from '@/assets/cosmac-logo.png'
import {
  loginNoStart, loginWithEmailNoStart,
  registerRequestCode, registerVerify,
  resetRequestCode, resetVerify, getAuthConfig,
  fetchSitePage,
} from '@/matrix/client'
import { defaultHsUrl } from '@/config/hs'

// homeserver 基址（与 LiveView 保持一致）：主站/本地连 hs.cosmac.cc，
// OEM 自部实例（发行版）为同源——见 config/hs.ts
const HS = defaultHsUrl()

// ── 帮助 / 隐私政策 弹层（内容来自后台「页面内容」,未配置回落内置默认稿）──
const pageOpen = ref<'' | 'privacy' | 'help'>('')
const pageTitle = ref('')
const pageBody = ref('')
const pageLoading = ref(false)
async function openSitePage(key: 'privacy' | 'help') {
  pageOpen.value = key
  pageLoading.value = true
  pageTitle.value = key === 'privacy' ? '隐私政策' : '帮助中心'
  try {
    const p = await fetchSitePage(key, HS)   // 未登录页:显式传 homeserver 基址
    pageTitle.value = p.title || pageTitle.value
    pageBody.value = p.md
  } finally {
    pageLoading.value = false
  }
}

const route = useRoute()
const router = useRouter()

// —— 认证态（从 LiveView 原样搬来）——
const user = ref('')
const password = ref('')
const password2 = ref('')          // 注册/找回的「确认密码」
// 密码可见性切换(负责人建议:密码框右侧小眼睛,默认闭眼隐藏、点击睁眼明文)。
// showPwd 管主密码框(登录/注册/重置共用 v-model=password),showPwd2 管确认框。
const showPwd = ref(false)
const showPwd2 = ref(false)
// 眼睛图标:睁眼(明文态)/闭眼带斜杠(隐藏态)。内联 SVG,随主题 currentColor。
const EYE_OPEN = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>'
const EYE_OFF = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.9 4.24A9.1 9.1 0 0 1 12 4c6.5 0 10 7 10 7a13.2 13.2 0 0 1-1.67 2.5"/><path d="M6.6 6.6A13.1 13.1 0 0 0 2 11s3.5 7 10 7a9.1 9.1 0 0 0 3.4-.65"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/><path d="m2 2 20 20"/></svg>'
const email = ref('')
const emailCode = ref('')
const codeCooldown = ref(0)        // 「发送验证码」倒计时（秒）
const sendingCode = ref(false)
const authMode = ref<'login' | 'register' | 'reset'>('login')
const loginBy = ref<'account' | 'email'>('account')
/** 切换 账号登录↔邮箱登录:清掉两个输入框 + 共用的密码框——账号密码和邮箱对应的
 *  密码未必相同,残留会被误提交(QA:表单数据跨页残留)。报错提示也一并清。
 *
 *  ⚠️ 注意:清空**挡不住浏览器自动填充**。账号框带 autocomplete="username",而浏览器为本站
 *  保存的"用户名"往往就是用户的邮箱(他一直用邮箱 tab 登录),于是新元素一渲染就被填回邮箱,
 *  看起来像"没清干净"(负责人实报)。与其和自动填充对着干(那会连带弄坏密码管理器),
 *  不如让账号登录**也认邮箱**——见 doLogin 里的 @ 判断。 */
function switchLoginBy(by: 'account' | 'email') {
  if (loginBy.value === by) return
  loginBy.value = by
  user.value = ''
  email.value = ''
  password.value = ''
  error.value = ''
}

/** 本轮登录该走哪条路：账号 tab 里若填的是邮箱(含 @)，自动改走邮箱登录。
 *
 *  为什么这么做：浏览器会把保存的邮箱自动填进账号框(见 switchLoginBy 注释)，用户也常
 *  记不清自己当初注册的是用户名还是邮箱。与其让他撞一句语义模糊的"用户名或密码错误"，
 *  不如按内容自动判断——填什么都能登进去。返回 (是否走邮箱, 标识符)。 */
function loginIdentity(): { byEmail: boolean; id: string } {
  if (loginBy.value === 'email') return { byEmail: true, id: email.value.trim() }
  const id = user.value.trim()
  // ⚠️ 用 indexOf > 0 而不是 includes('@')：Matrix 用户 ID 本身就以 @ 开头
  // （@duxiuzhen01:cosmac.cc），用 includes 会把粘贴完整 MXID 的人误判成邮箱登录。
  return { byEmail: id.indexOf('@') > 0, id }
}
const error = ref('')
const info = ref('')               // 成功/提示的内联反馈（替代原 toast，保持自包含）
const loading = ref(false)

// 「添加账号」模式：从主应用点「添加账号」跳来时带 ?add=1，给个「返回当前账号」出口。
const isAdd = computed(() => route.query.add === '1')

// —— 异地登录二次验证(阶段2):登录密码对了但换了新地点 → 后端发邮箱码,这里输码完成验证 ——
const stepUp = ref(false)
const stepUpHint = ref('')          // 打码后的邮箱(g***@gmail.com),提示码发哪了
const stepUpCode = ref('')          // 用户输入的 6 位验证码

// —— Turnstile 人机验证（阶段1；env 可插拔:后端没配 secret 就整段跳过）——
const tsEnabled = ref(false)          // 后端是否启用了 Turnstile
const tsSiteKey = ref('')
const tsToken = ref('')               // 挂件回调拿到的一次性令牌;发码时带上
const tsBoxRef = ref<HTMLElement>()   // 挂件容器
let tsWidgetId: string | null = null
let tsScriptFailed = false            // 脚本加载失败标志:给用户明确提示,并允许重试
declare global { interface Window { turnstile?: any; onTurnstileLoad?: () => void } }

/** 按需注入 Cloudflare Turnstile 脚本（只注一次;失败移除标签、下次调用可重试）。 */
function loadTurnstileScript(): Promise<void> {
  return new Promise((resolve) => {
    if (window.turnstile) { tsScriptFailed = false; resolve(); return }
    const existing = document.querySelector('script[data-turnstile]')
    if (existing) {
      // 已在加载中:同时挂 load/error——只挂 load 的话,加载失败这个 Promise 永不 resolve(悬挂)
      existing.addEventListener('load', () => { tsScriptFailed = false; resolve() })
      existing.addEventListener('error', () => { tsScriptFailed = true; existing.remove(); resolve() })
      return
    }
    const s = document.createElement('script')
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js'
    s.async = true; s.defer = true; s.setAttribute('data-turnstile', '1')
    s.onload = () => { tsScriptFailed = false; resolve() }
    // 失败:移除标签(否则残留的死标签让后续 existing 分支永远等不到 load)+ 记标志给可见提示
    s.onerror = () => { tsScriptFailed = true; s.remove(); resolve() }
    document.head.appendChild(s)
  })
}

/** 在容器里渲染挂件（切到"需要发码"的注册/找回模式时调用）。 */
async function renderTurnstile() {
  if (!tsEnabled.value || !tsSiteKey.value) return
  await loadTurnstileScript()
  // 显式等一帧:watch(authMode) 是 pre 回调,容器 <div ref="tsBoxRef"> 的 v-if 分支此刻可能
  // 还没挂载。当前靠 await 垫微任务碰巧不踩坑,但那是隐式约定——nextTick 零成本、防回归。
  await nextTick()
  if (!window.turnstile || !tsBoxRef.value) return
  if (tsWidgetId !== null) { try { window.turnstile.remove(tsWidgetId) } catch { /* ignore */ } tsWidgetId = null }
  tsToken.value = ''
  tsWidgetId = window.turnstile.render(tsBoxRef.value, {
    sitekey: tsSiteKey.value,
    callback: (t: string) => { tsToken.value = t },
    'expired-callback': () => { tsToken.value = '' },
    'error-callback': () => { tsToken.value = '' },
  })
}

onMounted(async () => {
  const cfg = await getAuthConfig(HS)
  tsEnabled.value = cfg.turnstile
  tsSiteKey.value = cfg.siteKey
  // 若一进来就在需要验证码的模式(注册/找回),渲染挂件
  if (tsEnabled.value && authMode.value !== 'login') renderTurnstile()
})
onBeforeUnmount(() => {
  if (tsWidgetId !== null && window.turnstile) { try { window.turnstile.remove(tsWidgetId) } catch { /* ignore */ } }
  if (cdTimer) { clearInterval(cdTimer); cdTimer = null }   // 倒计时中离开页面,别让 interval 空转
})
// 切到注册/找回时渲染;切回登录时不需要
watch(authMode, (m) => { if (tsEnabled.value && m !== 'login') renderTurnstile() })

// —— 密码强度（与后端 registration.password_problem 同一套规则,即时提示;后端是真防线）——
const WEAK_SET = new Set([
  'password', 'password1', 'passw0rd', '12345678', '123456789', '1234567890',
  'qwerty123', 'qwertyuiop', '11111111', '88888888', '66666666', '00000000',
  'abc12345', 'a1234567', 'iloveyou', 'admin123', 'root1234', 'letmein1',
  'sunshine', 'princess', 'football', 'baseball', 'dragon123', 'monkey123',
  'qq123456', 'wang1234', 'zhang123', 'asdfghjkl', '1q2w3e4r', '1qaz2wsx',
])
/** 0=太短 1=弱(会被后端拒) 2=中 3=强;附带不合格原因文案 */
const pwStrength = computed(() => {
  const pw = password.value
  if (!pw) return { level: 0, label: '', warn: '' }
  if (pw.length < 8) return { level: 0, label: '太短', warn: '至少 8 位' }
  // 用 Unicode 类别对齐后端(Python isalpha/isdigit):否则含非 ASCII 字母的密码前后端分类相反,
  // 出现"强度条说合格、提交却被后端拒"的断裂(如 'abcdefg中' 前端算字母+符号,后端算全字母)。
  const kinds = (/\p{L}/u.test(pw) ? 1 : 0) + (/\p{N}/u.test(pw) ? 1 : 0) + (/[^\p{L}\p{N}]/u.test(pw) ? 1 : 0)
  if (kinds < 2) return { level: 1, label: '弱', warn: '请混用字母、数字或符号中的至少两类' }
  if (WEAK_SET.has(pw.toLowerCase())) return { level: 1, label: '弱', warn: '这个密码太常见、极易被猜中' }
  const u = user.value.trim().toLowerCase()
  if (u && u.length >= 4 && pw.toLowerCase().includes(u)) return { level: 1, label: '弱', warn: '密码不能包含你的用户名' }
  // 达标线以上再分档:12+ 且三类 = 强
  if (pw.length >= 12 && kinds === 3) return { level: 3, label: '强', warn: '' }
  return { level: 2, label: '中', warn: '' }
})

/** 认证成功后进入主应用：优先回到守卫记下的目标地址，否则首页。 */
function proceed() {
  const to = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')
    ? route.query.redirect
    : '/'
  router.push(to)
}

/** 启动"发送验证码"按钮的倒计时（秒）。成功发码用后端给的 cooldown；被限频时用后端剩余秒数。 */
let cdTimer: ReturnType<typeof setInterval> | null = null
function startCodeCooldown(sec: number) {
  if (cdTimer) clearInterval(cdTimer)   // 防叠加:任何时刻只有一个倒计时在跑
  codeCooldown.value = Math.max(1, Math.round(sec))
  cdTimer = setInterval(() => {
    codeCooldown.value -= 1
    if (codeCooldown.value <= 0 && cdTimer) { clearInterval(cdTimer); cdTimer = null }
  }, 1000)
}

/** 发送邮箱验证码（带 60s 倒计时防连点）。 */
async function sendCode() {
  error.value = ''; info.value = ''
  const e = email.value.trim()
  if (!e) { error.value = '请先填邮箱'; return }
  if (codeCooldown.value > 0 || sendingCode.value) return
  // 启用了 Turnstile 但用户还没过验证 → 先别发;脚本加载失败时给能行动的提示(而非无声卡死)
  if (tsEnabled.value && !tsToken.value) {
    if (tsScriptFailed) {
      error.value = '人机验证组件加载失败，请检查网络后刷新页面重试'
      renderTurnstile()   // 顺手重试一次(onerror 已移除死标签,可重新注入)
    } else {
      error.value = '请先完成下方人机验证'
    }
    return
  }
  sendingCode.value = true
  try {
    const cd = authMode.value === 'reset'
      ? await resetRequestCode(HS, e, tsToken.value)
      : await registerRequestCode(HS, e, tsToken.value)
    info.value = `验证码已发送，请查收 ${e}（含垃圾箱）`
    startCodeCooldown(cd || 60)
  } catch (err: any) {
    error.value = err?.message || '发送验证码失败'
    // 后端返回了剩余冷却秒数（如"发送太频繁，请 X 秒后再试"）→ 按钮也走倒计时，别让用户空点再撞
    if (typeof err?.cooldown === 'number' && err.cooldown > 0) startCodeCooldown(err.cooldown)
    // 后端说"人机验证未通过"但本地以为没启用(多半是挂载时拉 /cosmac/auth/config 失败) →
    // 重拉配置并渲染挂件,让用户有验证可做,而不是对着报错干瞪眼。
    if (!tsEnabled.value && /人机验证/.test(String(err?.message || ''))) {
      const cfg = await getAuthConfig(HS)
      tsEnabled.value = cfg.turnstile
      tsSiteKey.value = cfg.siteKey
      if (tsEnabled.value) renderTurnstile()
    }
  } finally {
    sendingCode.value = false
    // Turnstile token 是**一次性**的:后端 siteverify 校验过(无论成败)即作废。不重置挂件的话,
    // 用户 60s 后点"重发验证码"会带着废 token 被 400 拒、挂件还显示已通过、无从重验(高危体验断裂)。
    if (tsEnabled.value && tsWidgetId !== null && window.turnstile) {
      try { window.turnstile.reset(tsWidgetId) } catch { /* ignore */ }
      tsToken.value = ''
    }
  }
}

/** 把登录的原始报错(Synapse errcode / 网络错误)映射成友好中文(bug3)。
 *  邮箱登录走后端、报错本就是中文;这里主要救账号登录直连 Synapse 的原始英文码。 */
function friendlyLoginError(e: any): string {
  const code = e?.errcode || e?.data?.errcode || ''
  const msg = String(e?.message || '')
  if (code === 'M_USER_DEACTIVATED') return '该账号已被停用，请联系管理员'
  if (code === 'M_LIMIT_EXCEEDED' || /429|too many|limit/i.test(msg)) return '尝试过于频繁，请稍后再试'
  if (code === 'M_FORBIDDEN' || /invalid|forbidden|password|unknown|not found|403/i.test(msg)) return '用户名或密码错误'
  if (/network|fetch|timeout|failed to fetch/i.test(msg)) return '网络异常，请检查网络后重试'
  // 兜底:凡是没有中文的消息(英文原始错误/MatrixError/带URL技术细节)一律收敛成友好中文
  // ——原始报错对用户没意义只会吓人(实测出现过 MatrixError: [400] ... 裸奔)。
  if (!msg || !/[\u4e00-\u9fa5]/.test(msg) || /matrixerror|https?:\/\//i.test(msg)) {
    return '登录失败，请检查账号和密码后重试'
  }
  return msg
}

/** 登录：账号走 Synapse，邮箱走 cosmac 后端；都用「只认证不启动」，成功后路由进主应用。 */
async function doLogin() {
  error.value = ''
  // 空输入本地先拦:别发一个注定失败的请求、拿一句语义模糊的「用户名或密码错误」
  if (loginBy.value === 'email') {
    if (!email.value.trim() || !password.value) { error.value = '请输入邮箱和密码'; return }
  } else {
    if (!user.value.trim() || !password.value) { error.value = '请输入用户名或邮箱，以及密码'; return }
  }
  loading.value = true
  try {
    const code = stepUp.value ? stepUpCode.value.trim() : ''
    if (stepUp.value && !code) { error.value = '请输入邮件里的 6 位验证码'; loading.value = false; return }
    const { byEmail, id } = loginIdentity()
    const res = byEmail
      ? await loginWithEmailNoStart(HS, id, password.value, code)
      : await loginNoStart(HS, id, password.value, code)
    if (res?.stepUp) {
      // 异地登录:后端已发验证码到绑定邮箱,切到"输码"状态,输完再点登录(带 code 重试)
      stepUp.value = true
      stepUpHint.value = res.emailHint || '你的绑定邮箱'
      stepUpCode.value = ''
      return
    }
    proceed()
  } catch (e: any) {
    error.value = friendlyLoginError(e)
  } finally {
    loading.value = false
  }
}

/** L17：step-up 挑战里「重新发送验证码」——用当前用户名/邮箱+密码再走一次登录(不带 code)，
 *  后端据此重新发码(受冷却/每小时上限约束，M14 已修正误判)。避免"没收到码只能退出重来"的自锁。 */
async function resendStepUpCode() {
  if (!stepUp.value || loading.value) return
  error.value = ''; info.value = ''
  loading.value = true
  try {
    const { byEmail, id } = loginIdentity()
    const res = byEmail
      ? await loginWithEmailNoStart(HS, id, password.value, '')
      : await loginNoStart(HS, id, password.value, '')
    if (res?.stepUp) {
      stepUpHint.value = res.emailHint || stepUpHint.value
      info.value = '验证码已重新发送，请查收邮箱。'
    } else {
      proceed()   // 极少数：这次不再要求 step-up(如已成常用地区) → 直接进
    }
  } catch (e: any) {
    error.value = friendlyLoginError(e)
  } finally {
    loading.value = false
  }
}

/** 注册：校验 → 验码建号 → 用同一套用户名/密码认证 → 进主应用（LiveView 会触发首次引导）。 */
async function doRegister() {
  error.value = ''
  const u = user.value.trim()
  const e = email.value.trim()
  if (!e) { error.value = '请填邮箱'; return }
  if (!emailCode.value.trim()) { error.value = '请填邮箱验证码'; return }
  if (!u || !password.value) { error.value = '请填用户名和密码'; return }
  if (password.value.length < 8) { error.value = '密码至少 8 位'; return }
  // 提交前用强度结果拦一道(与后端同规则):弱密码别白跑一次后端再被拒
  if (pwStrength.value.level <= 1) { error.value = pwStrength.value.warn || '密码太弱，请换一个'; return }
  if (password.value !== password2.value) { error.value = '两次输入的密码不一致'; return }
  loading.value = true
  try {
    // L18：注册成功即返回可用会话，registerVerify 内部已 saveSession；只有老后端没回 token 时
    // 才回退登录一次（不再无条件 loginNoStart 多建一个 device/token）。
    const reg = await registerVerify(HS, { email: e, code: emailCode.value.trim(), username: u, password: password.value })
    if (!reg?.access_token) await loginNoStart(HS, u, password.value)
    proceed()
  } catch (err: any) {
    error.value = err?.message || String(err)
  } finally {
    loading.value = false
  }
}

/** 找回密码：验码 → 重置 → 回登录页用新密码登录（停在本页，不跳转）。 */
async function doResetPassword() {
  error.value = ''; info.value = ''
  const e = email.value.trim()
  if (!e) { error.value = '请填邮箱'; return }
  if (!emailCode.value.trim()) { error.value = '请填邮箱验证码'; return }
  if (password.value.length < 8) { error.value = '新密码至少 8 位'; return }
  // L16：与注册页同一道弱密码门禁——否则注册拦、重置不拦，用户白跑一次请求才被后端拒。
  if (pwStrength.value.level <= 1) { error.value = pwStrength.value.warn || '密码太弱，请换一个'; return }
  if (password.value !== password2.value) { error.value = '两次输入的密码不一致'; return }
  loading.value = true
  try {
    await resetVerify(HS, { email: e, code: emailCode.value.trim(), password: password.value })
    switchAuthMode('login')
    password.value = ''
    info.value = '密码已重置，请用新密码登录'
  } catch (err: any) {
    error.value = err?.message || String(err)
  } finally {
    loading.value = false
  }
}

/** 切换登录/注册/找回密码。清空**所有**表单字段——避免"登录页填的用户名/邮箱被带进注册页"
 *  这类跨页面残留（bug4）。每种模式都从干净表单开始。 */
function switchAuthMode(m: 'login' | 'register' | 'reset') {
  authMode.value = m
  error.value = ''
  info.value = ''
  stepUp.value = false
  stepUpHint.value = ''
  stepUpCode.value = ''
  user.value = ''
  password.value = ''
  password2.value = ''
  email.value = ''
  emailCode.value = ''
}
</script>

<template>
  <div class="login">
    <div class="login-card">
      <!-- 添加账号：给个「返回当前账号」（当前会话仍在，直接回主应用）-->
      <button v-if="isAdd" class="add-acct-back" @click="router.push('/')">← 返回当前账号</button>
      <!-- 顶部：品牌 + tab/标题 -->
      <div class="auth-top">
        <div class="brand login-brand"><img :src="logoUrl" class="brand-logo" alt="" />GuDuu OS</div>
        <div class="auth-tabs" v-if="authMode !== 'reset'">
          <button class="auth-tab" :class="{ active: authMode === 'login' }" @click="switchAuthMode('login')">登录</button>
          <button class="auth-tab" :class="{ active: authMode === 'register' }" @click="switchAuthMode('register')">注册</button>
        </div>
        <div v-else class="auth-reset-title">重置密码</div>
      </div>

      <!-- 中部：表单字段 -->
      <div class="auth-fields">
        <!-- ===== 登录：账号 / 邮箱 二选一 ===== -->
        <template v-if="authMode === 'login'">
          <div class="auth-subtabs">
            <button class="auth-subtab" :class="{ active: loginBy === 'account' }" @click="switchLoginBy('account')">账号登录</button>
            <button class="auth-subtab" :class="{ active: loginBy === 'email' }" @click="switchLoginBy('email')">邮箱登录</button>
          </div>
          <!-- key 必须不同:账号框/邮箱框是同位置 v-if/v-else,不给 key 时 Vue 会复用同一个 DOM
               input,切 Tab 后上一个 Tab 的输入值残留在复用元素里刷不掉(负责人实报:切到账号登录
               仍回显邮箱)。加不同 key 强制各建独立 input。 -->
          <input v-if="loginBy === 'account'" key="login-account" v-model="user" name="login-username" autocomplete="username" placeholder="用户名或邮箱" @keyup.enter="doLogin" />
          <input v-else key="login-email" v-model="email" type="email" name="login-email" autocomplete="email" placeholder="邮箱" @keyup.enter="doLogin" />
          <div class="pw-wrap">
            <input v-model="password" :type="showPwd ? 'text' : 'password'" autocomplete="current-password" placeholder="密码" @keyup.enter="doLogin" />
            <button type="button" class="pw-eye" :aria-label="showPwd ? '隐藏密码' : '显示密码'" :title="showPwd ? '隐藏密码' : '显示密码'" @click="showPwd = !showPwd" v-html="showPwd ? EYE_OPEN : EYE_OFF"></button>
          </div>
          <!-- 异地登录二次验证(阶段2):密码对了但新地点,输邮箱码完成验证 -->
          <div v-if="stepUp" class="stepup-box">
            <div class="stepup-tip"><Icon name="lock" :size="13" /> 检测到新设备/新地点登录，验证码已发送至 <b>{{ stepUpHint }}</b></div>
            <input v-model="stepUpCode" name="login-otp" autocomplete="one-time-code" inputmode="numeric" maxlength="6"
                   placeholder="邮件里的 6 位验证码" @keyup.enter="doLogin" />
            <!-- L17：没收到码时可原地重发（不必退出重来），重发受后端冷却/每小时上限约束 -->
            <button type="button" class="stepup-resend" :disabled="loading" @click="resendStepUpCode">
              没收到？重新发送验证码
            </button>
          </div>
        </template>

        <!-- ===== 注册 / 找回密码 ===== -->
        <template v-else>
          <div class="auth-code-row">
            <input v-model="email" type="email" name="reg-email" autocomplete="email" placeholder="邮箱" />
            <button class="auth-code-btn" :disabled="codeCooldown > 0 || sendingCode || !email.trim()" @click="sendCode">
              {{ codeCooldown > 0 ? `${codeCooldown}s` : (sendingCode ? '发送中…' : '发送验证码') }}
            </button>
          </div>
          <!-- 人机验证挂件（后端启用时才显示） -->
          <div v-if="tsEnabled" ref="tsBoxRef" class="ts-box"></div>
          <input v-model="emailCode" name="reg-otp" autocomplete="one-time-code" inputmode="numeric" maxlength="6"
                 placeholder="6 位验证码（填邮件里的数字）"
                 @keyup.enter="authMode === 'reset' ? doResetPassword() : doRegister()" />
          <input v-if="authMode === 'register'" v-model="user" name="reg-username" autocomplete="username" placeholder="用户名" />
          <div class="pw-wrap">
            <input v-model="password" :type="showPwd ? 'text' : 'password'" autocomplete="new-password"
                   :placeholder="authMode === 'reset' ? '新密码（至少 8 位）' : '密码（至少 8 位）'"
                   @keyup.enter="authMode === 'reset' ? doResetPassword() : doRegister()" />
            <button type="button" class="pw-eye" :aria-label="showPwd ? '隐藏密码' : '显示密码'" :title="showPwd ? '隐藏密码' : '显示密码'" @click="showPwd = !showPwd" v-html="showPwd ? EYE_OPEN : EYE_OFF"></button>
          </div>
          <!-- 密码强度即时提示（与后端同规则;弱=提交会被拒,提前告知） -->
          <div v-if="password" class="pw-meter">
            <div class="pw-bars">
              <span v-for="i in 3" :key="i" class="pw-bar" :class="{ on: pwStrength.level >= i, weak: pwStrength.level <= 1, mid: pwStrength.level === 2, strong: pwStrength.level === 3 }"></span>
            </div>
            <span class="pw-label" :class="{ warn: pwStrength.level <= 1 }">
              {{ pwStrength.warn || `密码强度：${pwStrength.label}` }}
            </span>
          </div>
          <div class="pw-wrap">
            <input v-model="password2" :type="showPwd2 ? 'text' : 'password'" autocomplete="new-password"
                   :placeholder="authMode === 'reset' ? '确认新密码' : '确认密码'"
                   @keyup.enter="authMode === 'reset' ? doResetPassword() : doRegister()" />
            <button type="button" class="pw-eye" :aria-label="showPwd2 ? '隐藏密码' : '显示密码'" :title="showPwd2 ? '隐藏密码' : '显示密码'" @click="showPwd2 = !showPwd2" v-html="showPwd2 ? EYE_OPEN : EYE_OFF"></button>
          </div>
        </template>
      </div>

      <!-- 底部：提交按钮 + 提示/错误 + 切换链接 -->
      <div class="auth-bottom">
        <button v-if="authMode === 'login'" class="login-btn" :disabled="loading" @click="doLogin">{{ loading ? '登录中…' : '登录' }}</button>
        <button v-else-if="authMode === 'register'" class="login-btn" :disabled="loading" @click="doRegister">{{ loading ? '注册中…' : '注册并进入' }}</button>
        <button v-else class="login-btn" :disabled="loading" @click="doResetPassword">{{ loading ? '重置中…' : '重置密码' }}</button>
        <p class="ok" v-if="info">{{ info }}</p>
        <p class="err" v-if="error">{{ authMode === 'login' ? '登录失败' : (authMode === 'reset' ? '重置失败' : '注册失败') }}：{{ error }}</p>
        <p class="auth-switch" v-if="authMode === 'login'">还没有账号？<a @click="switchAuthMode('register')">注册一个</a> · <a @click="switchAuthMode('reset')">忘记密码？</a></p>
        <p class="auth-switch" v-else-if="authMode === 'register'">已有账号？<a @click="switchAuthMode('login')">去登录</a></p>
        <p class="auth-switch" v-else>想起来了？<a @click="switchAuthMode('login')">返回登录</a></p>
        <!-- 平台自己的帮助/隐私入口(站内弹层)。人机验证组件里的"隐私·条款"链接是 Cloudflare 的,改不了 -->
        <p class="auth-links"><a @click="openSitePage('help')">帮助</a> · <a @click="openSitePage('privacy')">隐私政策</a></p>
      </div>
    </div>

    <!-- 帮助/隐私政策 弹层（内容在管理后台「页面内容」可编辑,未配置用系统默认稿） -->
    <div v-if="pageOpen" class="auth-page-mask" @click.self="pageOpen = ''">
      <div class="auth-page-card">
        <div class="auth-page-head">
          <b>{{ pageTitle }}</b>
          <button class="auth-page-x" @click="pageOpen = ''">×</button>
        </div>
        <div class="auth-page-body">{{ pageLoading ? '加载中…' : pageBody }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 与原 LiveView 登录块完全一致的样式（搬迁，不改观感）。CSS 变量来自全局 tokens.css。 */
.login { height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(180deg, var(--bg-panel), var(--bg-soft)); font-family: var(--font-body); }
.login-card { width: 640px; max-width: 92vw; min-height: 502px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between; gap: 20px; padding: 40px; background: #fff; border: 1px solid var(--border); border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,.08); }
.auth-top { display: flex; flex-direction: column; gap: 16px; }
.auth-fields { display: flex; flex-direction: column; gap: 14px; }
.auth-bottom { display: flex; flex-direction: column; gap: 12px; }
.login-brand { font-weight: 800; font-size: 22px; color: var(--text); display: inline-flex; align-items: center; gap: 8px; }
.login-brand span { color: var(--accent); margin-left: 4px; }
.brand-logo { width: 26px; height: 26px; object-fit: contain; border-radius: 6px; }
.login-card input { padding: 13px 15px; border: 1px solid var(--border); border-radius: 10px; font-size: 15px; }
.login-btn { padding: 14px; border: 0; border-radius: 10px; background: var(--action); color: #fff; font-size: 15px; font-weight: 600; cursor: pointer; }
.login-btn:disabled { opacity: .6; cursor: default; }
.auth-tabs { display: flex; gap: 4px; padding: 4px; background: var(--bg, #f1efe9); border: 1px solid var(--border); border-radius: 10px; }
.auth-tab { flex: 1; padding: 10px; border: 0; background: transparent; color: var(--text-3); font-size: 15px; font-weight: 600; border-radius: 8px; cursor: pointer; }
.auth-tab.active { background: #fff; color: var(--text); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.auth-subtabs { display: flex; gap: 18px; padding: 0 2px; }
.auth-subtab { border: 0; background: transparent; color: var(--text-3); font-size: 14px; font-weight: 600; padding: 2px 0 6px; cursor: pointer; border-bottom: 2px solid transparent; }
.auth-subtab.active { color: var(--accent); border-bottom-color: var(--accent); }
.auth-code-row { display: flex; gap: 8px; }
.auth-code-row input { flex: 1; min-width: 0; }
/* 密码框 + 右侧小眼睛(负责人建议):相对定位包一层,眼睛绝对定位在右内侧;
   输入框右内边距留出图标位,避免长密码文字压到图标下面。 */
.pw-wrap { position: relative; display: flex; }
.pw-wrap input { flex: 1; min-width: 0; padding-right: 44px; }
.pw-eye {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
  border: 0; background: transparent; color: var(--text-3); cursor: pointer;
  border-radius: 8px; padding: 0; transition: color .12s ease, background .12s ease;
}
.pw-eye:hover { color: var(--text); background: var(--bg, #f1efe9); }
.pw-eye:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.auth-code-btn { flex-shrink: 0; padding: 0 12px; border: 1px solid var(--border); background: var(--bg-panel, #fff); color: var(--accent); font-size: 13px; font-weight: 600; border-radius: 10px; cursor: pointer; white-space: nowrap; }
.auth-code-btn:disabled { opacity: .5; cursor: default; color: var(--text-3); }
.auth-reset-title { font-size: 16px; font-weight: 700; color: var(--text); text-align: center; padding: 2px 0; }
.auth-switch { color: var(--text-3); font-size: 13px; text-align: center; margin: 0; }
.auth-switch a { color: var(--accent); cursor: pointer; font-weight: 600; }
.auth-switch a:hover { text-decoration: underline; }
/* 帮助/隐私政策入口 + 弹层 */
.auth-links { margin-top: 10px; text-align: center; font-size: 12px; color: var(--text-3); }
.auth-links a { color: var(--text-3); cursor: pointer; }
.auth-links a:hover { color: var(--accent); text-decoration: underline; }
.auth-page-mask { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); display: flex; align-items: center; justify-content: center; z-index: 60; }
.auth-page-card { width: min(640px, 92vw); max-height: 80vh; background: var(--bg-panel, #fff); border-radius: 14px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.18); }
.auth-page-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid var(--border, #eee); font-size: 16px; }
.auth-page-x { border: 0; background: transparent; font-size: 20px; cursor: pointer; color: var(--text-3, #999); line-height: 1; }
.auth-page-body { padding: 16px 18px; overflow-y: auto; white-space: pre-wrap; font-size: 13px; line-height: 1.75; color: var(--text, #333); }
.err { color: var(--danger); font-size: 13px; }
.ok { color: var(--accent); font-size: 13px; margin: 0; }
.pw-meter { display: flex; align-items: center; gap: 10px; margin-top: -6px; }
.pw-bars { display: flex; gap: 4px; }
.pw-bar { width: 34px; height: 4px; border-radius: 2px; background: var(--border); }
.pw-bar.on.weak { background: #d9534f; }
.pw-bar.on.mid { background: #e8a33d; }
.pw-bar.on.strong { background: #4c9a5f; }
.pw-label { font-size: 12px; color: var(--text-3); }
.pw-label.warn { color: #d9534f; }
.ts-box { min-height: 0; }
.stepup-box { display: flex; flex-direction: column; gap: 10px; padding: 12px; background: var(--bg, #f7f5ef); border: 1px solid var(--border); border-radius: 10px; }
.stepup-tip { font-size: 13px; color: var(--text-2, #55504a); line-height: 1.6; }
.add-acct-back { align-self: flex-start; border: none; background: transparent; color: var(--text-3); font-size: 13px; cursor: pointer; padding: 0; }
</style>
