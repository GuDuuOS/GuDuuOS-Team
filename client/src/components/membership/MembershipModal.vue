<script setup lang="ts">
import Icon from '@/components/Icon.vue'
/**
 * 升级会员弹窗（模块4 交易系统 · 用户侧）。
 * 读 bot 公开的套餐 → 选套餐+货币 → 下单 → (测试通道)模拟支付 → 会员开通。
 * 真实支付渠道(Stripe/PayPal/USDT...)接入后，这里按地区给出对应支付方式。
 */
import { computed, onMounted, ref } from 'vue'
import {
  payGetPlans, payCheckout, payManualConfirm, payGetMe,
  type PayPlan, type CheckoutResp, type PayMe,
} from '@/matrix/client'

const emit = defineEmits<{ (e: 'close'): void }>()

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

async function load() {
  loading.value = true; loadErr.value = ''
  try {
    me.value = await payGetMe()    // 当前会员状态（失败返回 null，不阻断）
    plans.value = await payGetPlans()
    if (!currencies.value.includes(currency.value)) currency.value = currencies.value[0] || ''
    if (!shownPlans.value.find((p) => p.slug === selectedSlug.value)) {
      selectedSlug.value = shownPlans.value[0]?.slug || ''
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

onMounted(load)
</script>

<template>
  <div class="mm-mask" @click.self="emit('close')">
    <div class="mm-card">
      <header class="mm-head">
        <span class="mm-title"><Icon name="sparkle" :size="15" /> 升级会员</span>
        <button class="mm-x" @click="emit('close')"><Icon name="close" :size="16" /></button>
      </header>

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
    </div>
  </div>
</template>

<style scoped>
.mm-mask { position: fixed; inset: 0; background: rgba(0,0,0,.42); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.mm-card { width: 460px; max-width: 92vw; background: var(--surface-1, #fff); border-radius: 16px; padding: 20px; box-shadow: 0 20px 60px rgba(0,0,0,.28); }
.mm-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.mm-title { font-size: 17px; font-weight: 700; color: var(--text-1, #222); }
.mm-x { border: none; background: none; font-size: 16px; cursor: pointer; color: var(--text-3, #999); }
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
.mm-buy { width: 100%; border: none; background: linear-gradient(90deg, var(--accent, #c96442), var(--warn, #e0883a)); color: #fff; font-weight: 700; font-size: 15px; padding: 11px; border-radius: 10px; cursor: pointer; }
.mm-buy:disabled { opacity: .6; cursor: default; }
.mm-link { border: none; background: none; color: var(--text-3, #999); cursor: pointer; font-size: 13px; margin-top: 8px; width: 100%; }
.mm-note { font-size: 11.5px; color: var(--text-3, #999); margin-top: 10px; line-height: 1.5; text-align: center; }
.mm-order { font-size: 13px; color: var(--text-2, #666); margin-bottom: 12px; text-align: center; }
.mm-err { color: #c0392b; font-size: 13px; margin: 8px 0; text-align: center; }
.mm-done-msg { font-size: 15px; color: var(--text-1, #222); margin-bottom: 18px; line-height: 1.6; }
code { background: var(--surface-2, #f0f0f0); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
</style>
