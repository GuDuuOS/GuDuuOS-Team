import { ref, reactive } from 'vue'
import {
  isOnboarded, setOnboarded, reportOnboardingTemplate,
  createSpace, createChannelInSpace, setChannelConfig, onboardIngestKb,
  getOnboardingTemplates, type OnboardingTemplateDef,
  payGetMe, MEMBER_TIERS, memberTierLabel,
} from '@/matrix/client'
import { ONBOARDING_TEMPLATES } from '@/data/onboardingTemplates'

/**
 * 首次引导（注册/登录后的「主 AI 问答」向导）。
 *
 * 机制（负责人定）：**前端脚本化对话向导** + **后台可配模板**——
 *  · 行业模板优先读后台 `cosmac.onboarding_templates`（管理员在「入驻模板」页配）；后台没配则
 *    回退到内置 ONBOARDING_TEMPLATES，保证总能用。
 *  · 选完按模板真建 Space + 频道；**把人设(+RULE)写进每个频道的 `cosmac.channel_config.persona`**，
 *    bot 读它后在该工作区以这个人设回应——**房间级配置普通用户自己有权限写，所以人设真生效**
 *    （旧版写全局控制室 setAiConfig 是管理员级、普通用户静默失败，故弃用）。
 *  · 模型/技能/知识库/默认工作流的绑定要写 DB 或建全局智能体，留 P2b。
 *
 * 步骤：选模板 → 工作区名 → 初始频道(可增删) → 主 AI 人设 → 确认创建。
 * 完成/跳过都写 account data `cosmac.onboarding`，不再重复弹。
 */

export type OnbStep = 'template' | 'name' | 'channels' | 'persona' | 'confirm' | 'creating' | 'done'

/** 聊天气泡 */
export interface OnbMsg { role: 'ai' | 'user'; text: string }

/** 引导里展示/使用的模板（后台模板与内置模板归一成这个形状）。 */
export interface OnbPickTemplate {
  key: string
  label: string
  icon: string
  desc: string
  channels: string[]
  aiName: string
  aiPersona: string
  rules: string
  model: string
  skillSlugs: string[]
  kbDocs: { title: string; content: string }[]
  workflowSlugs: string[]
  tier: string
  paid: boolean
}

interface OnbAnswers {
  templateKey: string
  workspace: string
  channels: string[]
  aiName: string
  aiPersona: string
  rules: string
  model: string
  skillSlugs: string[]
  kbDocs: { title: string; content: string }[]
  workflowSlugs: string[]
}

/* ===== 模块级单例 ===== */
const visible = ref(false)
const step = ref<OnbStep>('template')
const messages = ref<OnbMsg[]>([])
const busy = ref(false)
const error = ref('')
const createdSpaceId = ref('')
const templates = ref<OnbPickTemplate[]>([])
const userTier = ref('free') // 当前用户会员等级（用于付费模板门控）
const answers = reactive<OnbAnswers>({
  templateKey: '', workspace: '', channels: [], aiName: '', aiPersona: '', rules: '',
  model: '', skillSlugs: [], kbDocs: [], workflowSlugs: [],
})

// 点「跳过」先弹确认提醒（skipConfirm=true），不再直接空跳；坚持跳才用下面的默认工作区。
const skipConfirm = ref(false)
// 坚持跳过时给的默认工作区——营销方向（GuDuu OS 面向个人创业者，营销最通用，不留空）。
const MARKETING_DEFAULT = {
  workspace: '营销工作区',
  channels: ['内容策划', '社媒运营', '活动策划', '数据看板'],
  aiName: '营销助手',
  aiPersona: '你是这个营销团队的中枢 AI 助手，帮助策划内容、运营社媒、维护客户、分析数据、推进营销任务。回答简洁、专业、可执行。',
}

function ai(text: string) { messages.value.push({ role: 'ai', text }) }
function user(text: string) { messages.value.push({ role: 'user', text }) }

/** 把后台模板定义归一成引导用的形状。 */
function fromBackend(t: OnboardingTemplateDef): OnbPickTemplate {
  return {
    key: t.key, label: t.label, icon: t.icon || '🧩', desc: t.desc,
    channels: [...t.channels],
    aiName: '中枢 AI',           // 后台模板没单独的 AI 名字段，用默认；用户可在人设步改
    aiPersona: t.persona,
    rules: t.rules,
    model: t.model,
    skillSlugs: [...t.skillSlugs],
    kbDocs: t.kbDocs.map((d) => ({ ...d })),
    workflowSlugs: [...t.workflowSlugs],
    tier: t.tier || 'free',
    paid: (t.tier || 'free') !== 'free',
  }
}

/** 内置模板（后台没配时回退）。 */
function builtinTemplates(): OnbPickTemplate[] {
  return ONBOARDING_TEMPLATES.map((t) => ({
    key: t.key, label: t.label, icon: t.icon, desc: t.desc,
    channels: [...t.channels], aiName: t.aiName, aiPersona: t.aiPersona,
    rules: '', model: '', skillSlugs: [], kbDocs: [], workflowSlugs: [], tier: 'free', paid: false,
  }))
}

/** 加载模板：优先后台已上架的；没有则回退内置。同时查当前用户会员等级（付费门控用）。 */
async function loadTemplates() {
  try {
    const backend = await getOnboardingTemplates()
    const enabled = backend.filter((t) => t.enabled)
    templates.value = enabled.length ? enabled.map(fromBackend) : builtinTemplates()
  } catch {
    templates.value = builtinTemplates()
  }
  try {
    const me = await payGetMe()
    userTier.value = me?.tier || 'free'
  } catch {
    userTier.value = 'free'
  }
}

/** 等级排序：free < paid < creator（按 MEMBER_TIERS 顺序）。 */
function tierRank(slug: string): number {
  const i = MEMBER_TIERS.findIndex((t) => t.slug === slug)
  return i < 0 ? 0 : i
}
/** 该模板是否被当前会员等级锁住（付费模板高于用户等级）。 */
function templateLocked(t: OnbPickTemplate): boolean {
  return tierRank(t.tier) > tierRank(userTier.value)
}

/** 复位到初始问候 */
function reset() {
  step.value = 'template'
  messages.value = []
  busy.value = false
  error.value = ''
  createdSpaceId.value = ''
  answers.templateKey = ''
  answers.workspace = ''
  answers.channels = []
  answers.aiName = ''
  answers.aiPersona = ''
  answers.rules = ''
  answers.model = ''
  answers.skillSlugs = []
  answers.kbDocs = []
  answers.workflowSlugs = []
  ai('👋 欢迎来到 GuDuu OS！我是你的中枢 AI。')
  ai('先花一分钟把你的工作台搭起来——你主要做哪个方向？')
}

export function useOnboarding() {
  return {
    visible, step, messages, busy, error, answers, createdSpaceId, templates, userTier,
    templateLocked, skipConfirm,

    /** 登录后调用：没引导过才自动弹（已引导/已跳过则什么都不做）。 */
    maybeAutoStart() {
      if (isOnboarded()) return
      reset()
      loadTemplates()
      visible.value = true
    },
    /** 手动打开（如设置里「重新引导」）。 */
    open() { reset(); loadTemplates(); visible.value = true },
    close() { visible.value = false },

    /** ① 选模板 → 预填后进入「工作区名」（付费模板高于用户等级则拦截、提示升级）*/
    pickTemplate(key: string) {
      const t = templates.value.find((x) => x.key === key)
      if (!t) return
      if (templateLocked(t)) {
        user(`${t.icon} ${t.label}`)
        ai(`「${t.label}」是${memberTierLabel(t.tier)}专享方案，你当前是${memberTierLabel(userTier.value)}。先选个免费方案，或升级会员后再用～`)
        return
      }
      answers.templateKey = key
      answers.channels = [...t.channels]
      answers.aiName = t.aiName
      answers.aiPersona = t.aiPersona
      answers.rules = t.rules
      answers.model = t.model
      answers.skillSlugs = [...t.skillSlugs]
      answers.kbDocs = t.kbDocs.map((d) => ({ ...d }))
      answers.workflowSlugs = [...t.workflowSlugs]
      user(`${t.icon} ${t.label}`)
      ai(`好的，按「${t.label}」给你预置了一套频道和助手人设，后面都能改。`)
      ai('给你的工作区起个名字吧？这个名字会显示在左上角。')
      step.value = 'name'
    },

    /** ② 工作区名 → 进入「初始频道」 */
    submitName(v: string) {
      const name = v.trim()
      if (!name) return
      answers.workspace = name
      user(name)
      ai(`「${name}」收到。我先按模板给你建这几个频道，你可以加/删：`)
      step.value = 'channels'
    },

    /** ③ 频道增删 */
    addChannel(v: string) {
      const n = v.trim()
      if (n && !answers.channels.includes(n)) answers.channels.push(n)
    },
    removeChannel(i: number) { answers.channels.splice(i, 1) },

    /** 频道确认 → 进入「主 AI 人设」 */
    confirmChannels() {
      user(answers.channels.length ? answers.channels.join('、') : '（先不建频道）')
      ai('最后，给你的中枢 AI 起个名字、定个人设——它会用这个身份帮你干活：')
      step.value = 'persona'
    },

    /** ④ 主 AI 人设 → 进入「确认」 */
    submitPersona(name: string, persona: string) {
      answers.aiName = name.trim() || answers.aiName
      answers.aiPersona = persona.trim() || answers.aiPersona
      user(`${answers.aiName}：${answers.aiPersona}`)
      ai('都齐了！确认一下，我这就帮你把工作台搭起来：')
      step.value = 'confirm'
    },

    /** 回到上一步重填某项 */
    goStep(s: OnbStep) { step.value = s },

    /**
     * ⑤ 确认创建：真建 Space + 频道 + 给每个频道写人设(+RULE)，完成后标记已引导。
     * 返回新建的 spaceId（失败抛错，由 UI 显示）。
     */
    async runCreate(): Promise<string> {
      // 重入守卫：防止快速双击/重复触发并发跑两遍，建出两个工作区。
      if (busy.value) throw new Error('正在创建中，请稍候…')
      busy.value = true
      error.value = ''
      step.value = 'creating'
      try {
        // 1) 建工作区（私有）
        const sid = await createSpace(answers.workspace, { public: false, label: answers.workspace.slice(0, 2) })
        createdSpaceId.value = sid
        // 2) 逐个建频道（单个失败不阻断其余），收集成功的房间 id。
        //    ⚠️ 一口气建"空间 + 多个频道 + 每个都邀 bot"会在很短时间内打出几十个事件,
        //    容易触发 Synapse 突发限流(rc_message/rc_invites);此时**靠后**的频道创建会失败,
        //    旧代码的 catch{} 又把错误吞了 → 用户加的那个频道(通常排最后)悄悄没建上(线上实测:
        //    "每日站会"计数=0)。改成:①频道之间留间隔;②失败退避重试几次,让它有机会等限流窗口过去。
        const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
        const channelIds: string[] = []
        for (let idx = 0; idx < answers.channels.length; idx++) {
          const cn = answers.channels[idx]
          if (idx > 0) await sleep(350)   // 频道之间留点间隔,别打成一梭子触发限流
          let cid = ''
          for (let attempt = 0; attempt < 3 && !cid; attempt++) {
            if (attempt > 0) await sleep(800 * attempt)   // 失败退避:0.8s、1.6s
            try { cid = await createChannelInSpace(sid, cn, { public: false }) } catch { /* 重试 */ }
          }
          if (cid) channelIds.push(cid)
        }
        // 3) 把人设(+RULE)写进每个频道的 channel_config.persona（房间级，普通用户有权限写）
        //    bot 的 _group_context 读 persona.prompt → 在该群以此人设回应，**真生效**。
        const prompt = answers.rules
          ? `${answers.aiPersona}\n\n[平台规则]\n${answers.rules}`
          : answers.aiPersona
        // 人设 + 模型 + 技能 + 默认工作流一起写进频道配置；bot 的 _group_context 会读
        // persona.model/skill_slugs 与顶层 workflowSlugs（让模板的模型/技能/工作流在本群真生效）。
        const personaPatch = {
          persona: {
            aiName: answers.aiName, prompt,
            model: answers.model, skill_slugs: answers.skillSlugs,
          },
          workflowSlugs: answers.workflowSlugs,
        }
        for (const cid of channelIds) {
          try { await setChannelConfig(cid, personaPatch) } catch { /* 单频道写失败不阻断 */ }
        }
        // 4) 把模板预置知识库文档灌进本人个人知识库（best-effort，灌不进不阻断引导）
        if (answers.kbDocs.length) {
          try { await onboardIngestKb(answers.kbDocs) } catch { /* 忽略 */ }
        }
        // 5) 标记已引导 + 上报所选模板给 bot(资源级权限「指定模板可用」据此判定)
        try { await setOnboarded(true) } catch { /* 标记失败也无妨，下次最多再问一次 */ }
        if (answers.templateKey) {
          try { await reportOnboardingTemplate(answers.templateKey) } catch { /* best-effort */ }
        }
        step.value = 'done'
        // 如实反馈：用户要了 N 个频道但一个都没建成时，别假装"搭好了"。工作区已建好(sid 有效)，
        // 故仍进入工作区，只是把频道没建上的实情说清楚，引导用户进去手动补。
        const wantCh = answers.channels.length
        if (wantCh > 0 && channelIds.length === 0) {
          ai('⚠️ 工作区已创建，但频道没能建上（可能是网络或权限问题）。先带你进去，可在里面手动新建频道。')
        } else if (channelIds.length < wantCh) {
          ai(`✅ 工作区搭好了！${wantCh} 个频道建成了 ${channelIds.length} 个，其余可进去手动补。正在带你进入…`)
        } else {
          ai('🎉 搭好了！正在把你带进新工作区…')
        }
        return sid
      } catch (e: any) {
        error.value = e?.message || '创建失败，请重试'
        step.value = 'confirm' // 退回确认页让用户重试
        throw e
      } finally {
        busy.value = false
      }
    },

    /** 点「跳过」：不再直接空跳，先弹确认提醒（skipConfirm，组件据此弹二次确认）。 */
    skip() { skipConfirm.value = true },
    /** 确认弹窗「继续设置」：收起提醒、回到引导。 */
    cancelSkip() { skipConfirm.value = false },
    /** 确认弹窗「仍要跳过」：填入默认营销工作区答案（随后组件调 runCreate 真建，不留空）。 */
    fillMarketingDefault() {
      skipConfirm.value = false
      Object.assign(answers, {
        templateKey: '', rules: '', model: '', skillSlugs: [], kbDocs: [], workflowSlugs: [],
        ...MARKETING_DEFAULT,
      })
    },
  }
}
