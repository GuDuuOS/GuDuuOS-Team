<script setup lang="ts">
import Icon from '@/components/Icon.vue'
/**
 * 升级会员 / Token 充值弹窗（模块4 交易系统 · 用户侧）。
 * - 「会员套餐」页签：读 bot 公开套餐 → 选套餐+货币 → 下单 → (测试通道)模拟支付 → 会员开通。
 * - 「Token 充值」页签（Token 经济 1d）：余额 + 今日免费额度 + 充值包 + 收支明细。
 *   总开关（控制室 cosmac.token_config.enabled）关着时不显示该页签——现网默认关、零打扰。
 * 真实支付渠道(Stripe/PayPal/USDT/支付宝/微信)接入后，这里按地区给出对应支付方式。
 */
import { computed, onMounted, ref } from 'vue'
import { formatServerDateTime } from '@/utils/dateTime'
import {
  payGetPlans, payCheckout, payManualConfirm, payGetMe,
  walletGetMe, walletGetLedger, walletCheckout,
  type PayPlan, type CheckoutResp, type PayMe,
  type WalletMe, type WalletLedgerItem, type WalletCheckoutResp,
} from '@/matrix/client'

const emit = defineEmits<{ (e: 'close'): void }>()

/* —— 页签：member（会员套餐）/ token（Token 充值）—— */
const tab = ref<'member' | 'token'>('member')

const me = ref<PayMe | null>(null)   // 当前会员状态（顶部展示）
const meText = computed(() => {
  if (!me.value || me.value.tier === 'free') return ''
  const exp = me.value.expires_ts
  const tail = exp > 0 ? ` · 到期 ${new Date(exp * 1000).toLocaleDateString()}` : '（永久）'
  return `你当前是「${me.value.tier_label}」${tail}`
})

const CUR_LABEL: Record<string, string> = { usd: '$', cny: '¥', usdt: 'USDT ' }
const TIER_LABEL: Record<string, string> = { paid: '付费会员', creator: '创作者会员' }

const loading = ref(true)
const loadErr = ref('')
const plans = ref<PayPlan[]>([])
const currency = ref('')
const selectedSlug = ref('')
const busy = ref(false)
const errMsg = ref('')
const order = ref<CheckoutResp | null>(null)   // 下单后拿到的订单/支付方式
const doneMsg = ref('')                          // 开通成功提示

/* —— Token 钱包状态 —— */
const wallet = ref<WalletMe | null>(null)
const wSelected = ref('')                        // 选中的充值包 slug
const wOrder = ref<WalletCheckoutResp | null>(null)
const wErr = ref('')
const wDone = ref('')
const ledger = ref<WalletLedgerItem[]>([])
const ledgerOpen = ref(false)

/** 所有套餐支持的货币并集（做货币切换）。 */
const currencies = computed(() => {
  const set = new Set<string>()
  for (const p of plans.value) for (const c of Object.keys(p.prices || {})) set.add(c)
  return [...set]
})

/** 当前货币下、有定价的套餐。价格做数值守卫：服务端若回字符串/null，Number() 兜底避免 NaN 比较。 */
const shownPlans = computed(() =>
  plans.value.filter((p) => {
    const cents = Number(p.prices?.[currency.value])
    return Number.isFinite(cents) && cents > 0
  }))

function priceText(p: PayPlan): string {
  const cents = Number(p.prices?.[currency.value])
  const safe = Number.isFinite(cents) ? cents : 0
  return `${CUR_LABEL[currency.value] || ''}${(safe / 100).toFixed(2)}`
}

function periodText(days: number): string {
  if (days % 365 === 0) return `${days / 365} 年`
  if (days % 30 === 0) return `${days / 30} 个月`
  return `${days} 天`
}

/* —— Token：充值包按 cny 优先定价展示（当前主推国内渠道）—— */
function pkgPrice(p: { prices: Record<string, number> }): string {
  const cny = Number(p.prices?.cny)
  if (Number.isFinite(cny) && cny > 0) return `¥${(cny / 100).toFixed(2)}`
  const first = Object.entries(p.prices || {})[0]
  if (!first) return ''
  return `${CUR_LABEL[first[0]] || first[0]}${(Number(first[1]) / 100).toFixed(2)}`
}

function pkgCurrency(p: { prices: Record<string, number> }): string {
  if (Number(p.prices?.cny) > 0) return 'cny'
  return Object.keys(p.prices || {})[0] || 'cny'
}

/** token 数展示：万级缩写（10000 → 1万），中文用户好读。 */
function fmtTokens(n: number): string {
  if (n >= 10000 && n % 1000 === 0) return `${(n / 10000).toLocaleString()}万`
  return n.toLocaleString()
}

const REASON_LABEL: Record<string, string> = {
  recharge: '充值', grant: '赠送', ai_usage: 'AI 对话',
  adjust: '人工调整', refund: '退款',
}

async function load() {
  loading.value = true; loadErr.value = ''
  try {
    me.value = await payGetMe()    // 当前会员状态（失败返回 null，不阻断）
    plans.value = await payGetPlans()
    wallet.value = await walletGetMe()   // Token 钱包（关着/失败返回 enabled=false / null）
    if (!currencies.value.includes(currency.value)) currency.value = currencies.value[0] || ''
    if (!shownPlans.value.find((p) => p.slug === selectedSlug.value)) {
      selectedSlug.value = shownPlans.value[0]?.slug || ''
    }
    if (wallet.value?.packages?.length && !wallet.value.packages.find((p) => p.slug === wSelected.value)) {
      wSelected.value = wallet.value.packages[0].slug
    }
  } catch (e: any) {
    loadErr.value = e?.message || '读取套餐失败'
  } finally {
    loading.value = false
  }
}

async function buy() {
  if (!selectedSlug.value || busy.value) return
  busy.value = true; errMsg.value = ''
  try {
    order.value = await payCheckout(selectedSlug.value, currency.value, 'manual')
  } catch (e: any) {
    errMsg.value = e?.message || '下单失败'
  } finally {
    busy.value = false
  }
}

/** 测试通道：模拟支付成功 → 会员开通。 */
async function confirmTest() {
  if (!order.value || busy.value) return
  busy.value = true; errMsg.value = ''
  try {
    await payManualConfirm(order.value.order_no, order.value.checkout?.extra?.confirm_token || '')
    doneMsg.value = `🎉 会员已开通（${TIER_LABEL[order.value.tier] || order.value.tier}），有效期约 ${periodText(order.value.period_days)}`
    me.value = await payGetMe()   // 刷新当前状态
  } catch (e: any) {
    errMsg.value = e?.message || '确认失败'
  } finally {
    busy.value = false
  }
}

function reset() { order.value = null; doneMsg.value = ''; errMsg.value = '' }

/* —— Token 充值流程（与会员同一测试通道；回调复用 /cosmac/pay/callback/manual）—— */
async function wBuy() {
  const pkg = wallet.value?.packages?.find((p) => p.slug === wSelected.value)
  if (!pkg || busy.value) return
  busy.value = true; wErr.value = ''
  try {
    wOrder.value = await walletCheckout(pkg.slug, pkgCurrency(pkg), 'manual')
  } catch (e: any) {
    wErr.value = e?.message || '下单失败'
  } finally {
    busy.value = false
  }
}

async function wConfirmTest() {
  if (!wOrder.value || busy.value) return
  busy.value = true; wErr.value = ''
  try {
    await payManualConfirm(wOrder.value.order_no, wOrder.value.checkout?.extra?.confirm_token || '')
    wDone.value = `🎉 已到账 ${fmtTokens(wOrder.value.tokens)} token`
    wallet.value = await walletGetMe()   // 刷新余额
    if (ledgerOpen.value) ledger.value = await walletGetLedger()
  } catch (e: any) {
    wErr.value = e?.message || '确认失败'
  } finally {
    busy.value = false
  }
}

function wReset() { wOrder.value = null; wDone.value = ''; wErr.value = '' }

async function toggleLedger() {
  ledgerOpen.value = !ledgerOpen.value
  if (ledgerOpen.value && !ledger.value.length) ledger.value = await walletGetLedger()
}

onMounted(load)
</script>

<template>
  <div class="mm-mask" @click.self="emit('close')">
    <div class="mm-card">
      <header class="mm-head">
        <span class="mm-title"><Icon name="sparkle" :size="15" /> 会员与充值</span>
        <button class="mm-x" @click="emit('close')"><Icon name="close" :size="16" /></button>
      </header>

      <!-- 页签：Token 经济开着才显示第二个（关着=老样子只有会员） -->
      <div v-if="wallet?.enabled" class="mm-tabs">
        <button class="mm-tab" :class="{ on: tab === 'member' }" @click="tab = 'member'">会员套餐</button>
        <button class="mm-tab" :class="{ on: tab === 'token' }" @click="tab = 'token'">Token 充值</button>
      </div>

      <!-- ====== 会员套餐页签 ====== -->
      <template v-if="tab === 'member'">
        <div v-if="loading" class="mm-center">加载套餐…</div>
        <div v-else-if="loadErr" class="mm-center mm-err">{{ loadErr }} <button class="mm-link" @click="load">重试</button></div>
        <div v-else-if="!plans.length" class="mm-center">暂未开放套餐，请稍后再来。</div>

        <!-- 开通成功 -->
        <div v-else-if="doneMsg" class="mm-center mm-done">
          <div class="mm-done-msg">{{ doneMsg }}</div>
          <button class="mm-buy" @click="emit('close')">完成</button>
        </div>

        <template v-else>
          <!-- 当前会员状态 -->
          <div v-if="meText" class="mm-me">{{ meText }}</div>

          <!-- 货币切换 -->
          <div v-if="currencies.length > 1" class="mm-cur">
            <button v-for="c in currencies" :key="c" class="mm-cur-b"
              :class="{ on: c === currency }" @click="currency = c; reset()">
              {{ (CUR_LABEL[c] || c).trim() || c.toUpperCase() }}
            </button>
          </div>

          <!-- 套餐卡片 -->
          <div class="mm-plans">
            <button v-for="p in shownPlans" :key="p.slug" class="mm-plan"
              :class="{ on: p.slug === selectedSlug }" @click="selectedSlug = p.slug; reset()">
              <span class="mm-plan-tier">{{ TIER_LABEL[p.tier] || p.tier }}</span>
              <span class="mm-plan-name">{{ p.name }}</span>
              <span class="mm-plan-price">{{ priceText(p) }}</span>
              <span class="mm-plan-period">/ {{ periodText(p.period_days) }}</span>
            </button>
          </div>

          <p v-if="errMsg" class="mm-err">{{ errMsg }}</p>

          <!-- 未下单：购买按钮 -->
          <template v-if="!order">
            <button class="mm-buy" :disabled="!selectedSlug || busy" @click="buy">
              {{ busy ? '处理中…' : (me && me.tier !== 'free' ? '续费 / 升级' : '立即开通') }}
            </button>
            <p class="mm-note">支付渠道(Stripe / PayPal / USDT / 支付宝 / 微信)接入中；当前为<strong>测试通道</strong>。</p>
          </template>

          <!-- 已下单：测试通道确认 -->
          <template v-else>
            <div class="mm-order">订单 <code>{{ order.order_no }}</code> 已创建（测试通道，不收款）</div>
            <button class="mm-buy" :disabled="busy" @click="confirmTest">
              {{ busy ? '确认中…' : '模拟支付成功（测试）' }}
            </button>
            <button class="mm-link" @click="reset">取消</button>
          </template>
        </template>
      </template>

      <!-- ====== Token 充值页签（Token 经济 1d）====== -->
      <template v-else>
        <!-- 余额卡：余额 + 今日免费额度 -->
        <div class="mm-wallet">
          <div class="mm-wal-main">
            <span class="mm-wal-num">{{ fmtTokens(wallet?.balance || 0) }}</span>
            <span class="mm-wal-unit">token</span>
          </div>
          <div class="mm-wal-sub">
            <template v-if="wallet?.exempt">管理员账号不消耗 token</template>
            <template v-else-if="(wallet?.free_daily?.total || 0) > 0">
              今日免费额度：剩 {{ fmtTokens(wallet?.free_daily?.remaining || 0) }} / {{ fmtTokens(wallet?.free_daily?.total || 0) }}（每天重置）
            </template>
            <template v-else>使用 AI 按真实用量消耗 token</template>
          </div>
        </div>

        <!-- 充值成功 -->
        <div v-if="wDone" class="mm-center mm-done">
          <div class="mm-done-msg">{{ wDone }}</div>
          <button class="mm-buy" @click="wReset()">继续充值</button>
        </div>

        <template v-else>
          <!-- 充值包 -->
          <div v-if="wallet?.packages?.length" class="mm-plans">
            <button v-for="p in wallet.packages" :key="p.slug" class="mm-plan"
              :class="{ on: p.slug === wSelected }" @click="wSelected = p.slug; wReset()">
              <span class="mm-plan-name">{{ p.name }}</span>
              <span class="mm-pkg-tokens">{{ fmtTokens(p.tokens) }} token</span>
              <span class="mm-plan-price">{{ pkgPrice(p) }}</span>
            </button>
          </div>
          <div v-else class="mm-center">暂未上架充值包，请稍后再来。</div>

          <p v-if="wErr" class="mm-err">{{ wErr }}</p>

          <template v-if="wallet?.packages?.length && !wOrder">
            <button class="mm-buy" :disabled="!wSelected || busy" @click="wBuy">
              {{ busy ? '处理中…' : '立即充值' }}
            </button>
            <p class="mm-note">支付渠道(支付宝 / 微信)接入中；当前为<strong>测试通道</strong>。</p>
          </template>
          <template v-else-if="wOrder">
            <div class="mm-order">订单 <code>{{ wOrder.order_no }}</code> 已创建（测试通道，不收款）</div>
            <button class="mm-buy" :disabled="busy" @click="wConfirmTest">
              {{ busy ? '确认中…' : '模拟支付成功（测试）' }}
            </button>
            <button class="mm-link" @click="wReset">取消</button>
          </template>
        </template>

        <!-- 收支明细（折叠） -->
        <button class="mm-link" @click="toggleLedger">
          {{ ledgerOpen ? '收起明细 ▲' : '收支明细 ▼' }}
        </button>
        <div v-if="ledgerOpen" class="mm-ledger">
          <div v-if="!ledger.length" class="mm-center">暂无记录</div>
          <div v-for="it in ledger" :key="it.id" class="mm-led-row">
            <span class="mm-led-what">
              {{ REASON_LABEL[it.reason] || it.reason }}
              <em v-if="it.note" class="mm-led-note">{{ it.note }}</em>
            </span>
            <span class="mm-led-delta" :class="{ neg: it.delta < 0 }">
              {{ it.delta > 0 ? '+' : '' }}{{ it.delta.toLocaleString() }}
            </span>
            <span class="mm-led-time">{{ formatServerDateTime(it.created_at) }}</span>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.mm-mask { position: fixed; inset: 0; background: rgba(0,0,0,.42); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.mm-card { width: 460px; max-width: 92vw; max-height: 86vh; overflow-y: auto; background: var(--surface-1, #fff); border-radius: 16px; padding: 20px; box-shadow: 0 20px 60px rgba(0,0,0,.28); }
.mm-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.mm-title { font-size: 17px; font-weight: 700; color: var(--text-1, #222); }
.mm-x { border: none; background: none; font-size: 16px; cursor: pointer; color: var(--text-3, #999); }
.mm-tabs { display: flex; gap: 6px; margin-bottom: 14px; border-bottom: 1px solid var(--border, #eee); }
.mm-tab { border: none; background: none; padding: 7px 12px; font-size: 14px; cursor: pointer; color: var(--text-2, #666); border-bottom: 2px solid transparent; margin-bottom: -1px; }
.mm-tab.on { color: var(--accent, #c96442); border-bottom-color: var(--accent, #c96442); font-weight: 700; }
.mm-center { text-align: center; padding: 30px 10px; color: var(--text-2, #666); }
.mm-me { font-size: 13px; color: var(--text-2, #555); background: var(--accent-soft, #fdf3ef); border: 1px solid var(--accent, #c96442); border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; }
.mm-cur { display: flex; gap: 6px; margin-bottom: 12px; }
.mm-cur-b { border: 1px solid var(--border, #e3e3e3); background: var(--surface-2, #f7f7f7); border-radius: 999px; padding: 4px 14px; cursor: pointer; font-size: 13px; }
.mm-cur-b.on { background: var(--accent, #c96442); color: #fff; border-color: transparent; }
.mm-plans { display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px; }
.mm-plan { display: flex; align-items: baseline; gap: 8px; text-align: left; border: 2px solid var(--border, #e3e3e3); border-radius: 12px; padding: 12px 14px; background: var(--surface-1, #fff); cursor: pointer; transition: border-color .12s; }
.mm-plan.on { border-color: var(--accent, #c96442); background: var(--accent-soft, #fdf3ef); }
.mm-plan-tier { font-size: 11px; font-weight: 700; color: #fff; background: var(--accent, #c96442); border-radius: 6px; padding: 2px 7px; }
.mm-plan-name { font-size: 14px; font-weight: 600; color: var(--text-1, #222); flex: 1; }
.mm-plan-price { font-size: 18px; font-weight: 800; color: var(--accent, #c96442); }
.mm-plan-period { font-size: 12px; color: var(--text-3, #999); }
.mm-pkg-tokens { font-size: 12.5px; color: var(--text-2, #666); }
.mm-buy { width: 100%; border: none; background: linear-gradient(90deg, var(--accent, #c96442), var(--warn, #e0883a)); color: #fff; font-weight: 700; font-size: 15px; padding: 11px; border-radius: 10px; cursor: pointer; }
.mm-buy:disabled { opacity: .6; cursor: default; }
.mm-link { border: none; background: none; color: var(--text-3, #999); cursor: pointer; font-size: 13px; margin-top: 8px; width: 100%; }
.mm-note { font-size: 11.5px; color: var(--text-3, #999); margin-top: 10px; line-height: 1.5; text-align: center; }
.mm-order { font-size: 13px; color: var(--text-2, #666); margin-bottom: 12px; text-align: center; }
.mm-err { color: #c0392b; font-size: 13px; margin: 8px 0; text-align: center; }
.mm-done-msg { font-size: 15px; color: var(--text-1, #222); margin-bottom: 18px; line-height: 1.6; }
code { background: var(--surface-2, #f0f0f0); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
/* —— Token 钱包 —— */
.mm-wallet { background: linear-gradient(120deg, var(--accent-soft, #fdf3ef), var(--surface-2, #faf5f0)); border: 1px solid var(--border, #eee); border-radius: 12px; padding: 14px 16px; margin-bottom: 14px; }
.mm-wal-main { display: flex; align-items: baseline; gap: 6px; }
.mm-wal-num { font-size: 26px; font-weight: 800; color: var(--accent, #c96442); }
.mm-wal-unit { font-size: 13px; color: var(--text-3, #999); }
.mm-wal-sub { font-size: 12px; color: var(--text-2, #666); margin-top: 4px; }
.mm-ledger { border-top: 1px solid var(--border, #eee); margin-top: 8px; max-height: 220px; overflow-y: auto; }
.mm-led-row { display: flex; align-items: baseline; gap: 8px; padding: 8px 2px; border-bottom: 1px dashed var(--border, #f0f0f0); font-size: 12.5px; }
.mm-led-what { flex: 1; color: var(--text-1, #333); }
.mm-led-note { font-style: normal; color: var(--text-3, #aaa); margin-left: 6px; font-size: 11.5px; }
.mm-led-delta { font-weight: 700; color: #2c9a5b; }
.mm-led-delta.neg { color: #c0392b; }
.mm-led-time { color: var(--text-3, #aaa); font-size: 11px; }
</style>
