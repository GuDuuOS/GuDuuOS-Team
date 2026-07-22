import { reactive, ref } from 'vue'
import { workspaces, workspaceDataMap, type WorkspaceMeta } from '@/data/channels'
import type { ChannelItem, DmItem } from '@/types/channel'
import { startHeartbeat } from '@/composables/useDemoHeartbeat'

/* 企业品牌常量：必须在模块加载即执行的 stripForSetup() 之前声明（避免 TDZ）*/
const BRAND_NAME = '蓝湾渔业'
const NEUTRAL_NAME = '我的企业'

/* ===== 向导消息模型 ===== */
export interface WizStep { label: string; done: boolean }
export interface WizAgentPlan {
  avatar: string
  name: string
  duty: string
  /** 来源：按描述创建 / 行业模板补齐 */
  src: '按你的描述' | '模板补齐'
}
export interface WizMsg {
  id: number
  role: 'ai' | 'user'
  text?: string
  steps?: WizStep[]
  /** 邀请卡（二维码 / 企业码）*/
  invite?: { method: string; code: string }
  /** 分身配置清单卡 */
  agents?: WizAgentPlan[]
}

/* ===== 开场先把工作台「拆」成基础界面（模块加载即生效，首屏即空白态）===== */
let pendingWorkspaces: WorkspaceMeta[] = []
let pendingChannels: ChannelItem[] = []
let pendingHumanDms: DmItem[] = []
let pendingBotDms: DmItem[] = []
/** 完整快照（跳过时按原始顺序精确复原）*/
let snapWorkspaces: WorkspaceMeta[] = []
let snapChannels: ChannelItem[] = []
let snapDms: DmItem[] = []
let stripped = false

function stripForSetup() {
  if (stripped) return
  stripped = true
  pendingWorkspaces = workspaces.splice(1) // 只留总控
  snapWorkspaces = [...pendingWorkspaces]
  pendingChannels = workspaceDataMap.hq.channels.splice(0)
  snapChannels = [...pendingChannels]
  const dms = workspaceDataMap.hq.dms.splice(0)
  snapDms = [...dms]
  pendingHumanDms = dms.filter((d) => !d.bot)
  pendingBotDms = dms.filter((d) => d.bot)
  // 品牌与工作区名先置中性，行业选定后再挂上「蓝湾渔业」
  workspaceDataMap.hq.name = NEUTRAL_NAME
  workspaces[0].title = `${NEUTRAL_NAME}（待初始化）`
  // 复位到驾驶舱作为搭建背景：必须在 router 初始化「之前」完成（本模块随 App 导入，早于 router 模块），
  // 否则深链接（如 #/ops/conflict）刷新后会露出未搭建却有内容的频道。
  const workbenchDeepLink = /^#\/(?:safety|energy|office|duu|todo|ops(?:\/|$))/
  if (typeof window !== 'undefined' && workbenchDeepLink.test(window.location.hash)) {
    window.location.hash = '#/case'
  }
}
stripForSetup()

/* ===== 向导状态 ===== */
export const wizardActive = ref(true)
export const wizMsgs = reactive<WizMsg[]>([])
export const wizQuick = ref<string[]>([])
export const wizBusy = ref(false)
export const wizStage = ref(0)
export const WIZ_TOTAL = 7

/** 品牌是否已就绪（行业选定后才挂上「蓝湾渔业」品牌，否则显示中性「我的企业」）*/
export const brandReady = ref(false)
/** 驾驶舱数据是否已就绪（导入数据那步才点亮，否则空态占位）*/
export const dataReady = ref(false)

let seq = 0
const pushAi = (text: string) => wizMsgs.push({ id: ++seq, role: 'ai', text })
const pushUser = (text: string) => wizMsgs.push({ id: ++seq, role: 'user', text })

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/** 思考动画：逐步打勾 */
async function think(labels: string[], stepMs = 500): Promise<void> {
  const m: WizMsg = reactive({
    id: ++seq,
    role: 'ai',
    steps: labels.map((label) => ({ label, done: false }))
  })
  wizMsgs.push(m)
  for (const s of m.steps!) {
    await wait(stepMs)
    s.done = true
  }
  await wait(220)
}

/** 把暂存条目逐个"长"回界面 */
async function revealAll<T>(target: T[], source: T[], ms = 420): Promise<void> {
  while (source.length) {
    target.push(source.shift() as T)
    await wait(ms)
  }
}

/* ===== 分身职能库：按用户描述语义匹配 ===== */
const AGENT_DEFS: { re: RegExp; avatar: string; name: string; duty: string }[] = [
  { re: /出海|打渔|捕捞|渔船|渔获/, avatar: '捕', name: '捕捞分身',     duty: '渔船调度 · 渔获上报 · 出海安全预警' },
  { re: /养鱼|养殖|塘|网箱|苗种/,   avatar: '养', name: '养殖分身',     duty: '苗种管护 · 水质病害监测 · 出塘报备' },
  { re: /加工|车间|分拣|预制/,      avatar: '加', name: '加工分身',     duty: '车间排产 · 生鲜分拣 · 产能管控' },
  { re: /卖货|销售|订单|渠道|客户/, avatar: '销', name: '销售分身',     duty: '订单渠道 · 客户对接 · 市场行情分析' },
  { re: /发货|仓储|仓库|物流|冷链|配送/, avatar: '仓', name: '仓储物流分身', duty: '冷库管理 · 冷链调度 · 配送跟踪' },
  { re: /质量|质检|检测|食安|溯源/, avatar: '质', name: '质检分身',     duty: '渔获抽检 · 食安检测 · 溯源报告' },
  { re: /天气|海况|风险|预警|盯着|设备/, avatar: '警', name: '运维预警分身', duty: '天气海况 · 设备冷链 · 风险实时预警' },
  { re: /总控|统筹|调度中心|管理/,  avatar: 'G', name: 'GuDuu 总控分身', duty: '全局调度 · 异常审批 · 数据汇总复盘' }
]

function planAgents(text: string): WizAgentPlan[] {
  return AGENT_DEFS.map((d) => ({
    avatar: d.avatar,
    name: d.name,
    duty: d.duty,
    src: d.re.test(text) ? ('按你的描述' as const) : ('模板补齐' as const)
  }))
}

/* ===== 对话剧本（7 步）===== */

export function startWizard() {
  if (wizMsgs.length) return
  pushAi(
    '👋 你好，我是 GuDuu 总控分身。这是一个全新的工作台——告诉我你的企业主营什么业务？我来为你搭建专属的智能分身协作体系。'
  )
  wizQuick.value = ['海洋渔业全产业链（捕捞 / 养殖 / 加工 / 销售）']
}

export async function answerWizard(text: string) {
  if (wizBusy.value || !wizardActive.value) return
  wizBusy.value = true
  wizQuick.value = []
  pushUser(text)

  switch (wizStage.value) {
    /* 第 1 步：识别行业 → 搭工作区 */
    case 0: {
      await think(['解析业务形态', '匹配「海洋渔业」行业模板', '规划组织结构'])
      pushAi('明白了！海洋渔业讲究全链路协同。已为你创建「蓝湾渔业」企业空间，按 四大核心业态 + 总控中心 创建工作区——注意看左侧 👈')
      // 挂上正式品牌：顶栏 + 侧边栏工作区名同步刷新
      workspaceDataMap.hq.name = BRAND_NAME
      workspaces[0].title = `${BRAND_NAME}（总控中心）`
      brandReady.value = true
      await wait(600)
      await revealAll(workspaces, pendingWorkspaces, 480)
      await wait(300)
      pushAi('工作区已就绪 ✅ 接下来把你的团队请进来。选择一种邀请方式：')
      wizQuick.value = ['二维码 / 企业码邀请', '短信批量邀请', '邮箱批量邀请']
      break
    }
    /* 第 2 步：邀请成员（多渠道）+ 角色权限 */
    case 1: {
      const method = /短信|手机/.test(text) ? '短信邀请' : /邮箱|邮件/.test(text) ? '邮箱邀请' : '二维码 / 企业码'
      wizMsgs.push({
        id: ++seq,
        role: 'ai',
        text: `好的，已生成「${method}」入口（企业码长期有效，二维码 24 小时有效）：`,
        invite: { method, code: 'LWYY-2026' }
      })
      await think(
        method === '二维码 / 企业码'
          ? ['邀请入口已分发到管理员', '成员扫码加入中…', '8 位成员全部加入 ✅']
          : [`通过${method}发送 8 份邀请`, '成员点击链接加入中…', '8 位成员全部加入 ✅'],
        620
      )
      pushAi('成员到齐 👏 私信栏可以看到核心成员。正在按岗位分配角色权限——这一步很关键：关键操作的终审权永远在人手里。')
      await wait(400)
      await revealAll(workspaceDataMap.hq.dms, pendingHumanDms, 420)
      await think(
        [
          '林经理 · 企业负责人 → 终审 / 审批 / 调价权',
          '赵船长 · 捕捞队长 → 出海作业确认权',
          '钱厂长 · 加工厂长 → 排产确认权',
          '孙库管 · 仓储主管 → 出入库复核权',
          '周专员 / 黄塘长 / 徐技术员 / 吴大副 → 岗位数据读写权'
        ],
        460
      )
      pushAi('成员与权限配置完成 ✅ 现在到最有意思的部分——告诉我你想让 AI 替你做什么？用大白话描述就行，我会理解并生成对应职能的分身。')
      wizQuick.value = ['出海打渔、塘里养鱼、车间加工、卖货发货都要管，再帮我盯着天气和质量']
      break
    }
    /* 第 3 步：智能创建分身（语义理解 → 职能清单 → 上线）*/
    case 2: {
      await think(['理解需求语义', '拆解职能与岗位映射', '生成分身配置方案'])
      const plan = planAgents(text)
      const matched = plan.filter((p) => p.src === '按你的描述').length
      const filled = plan.length - matched
      wizMsgs.push({
        id: ++seq,
        role: 'ai',
        text:
          `我从你的描述里识别出 ${matched} 类职能，另外根据渔业模板补齐了 ${filled} 个你没提到但必须有的角色（比如总控调度）。这是分身配置方案：`,
        agents: plan
      })
      await wait(900)
      pushAi('开始创建并上线（私信栏 👈）。再次强调：分身只有建议权和执行权，紧急调货、停产、出海审批等关键动作必须经过第 2 步授权的人确认。')
      await wait(400)
      /* 分身按原始顺序插到人类成员前面，保持侧边栏排序 */
      let insertIdx = 0
      while (pendingBotDms.length) {
        workspaceDataMap.hq.dms.splice(insertIdx++, 0, pendingBotDms.shift() as DmItem)
        await wait(420)
      }
      await wait(300)
      pushAi('8 个分身全部在线 ✅ 现在让它们"长出眼睛"——接入物联网与业务系统数据源？')
      wizQuick.value = ['一键接入推荐数据源']
      break
    }
    /* 第 4 步：接入数据源 */
    case 3: {
      await think(
        [
          '渔船定位 / AIS · 已接通',
          '水质传感物联网（36 点位）· 已接通',
          'MES 加工执行 · 已接通',
          '冷链温控平台 · 已接通',
          '溯源存证平台 · 已接通',
          '电商订单平台 · 已接通'
        ],
        420
      )
      pushAi('数据源全部接通 ✅ 分身能实时感知渔船、塘口、车间与冷链了。眼睛有了，再给它们"装上手"——从技能市场安装作业技能？')
      wizQuick.value = ['安装推荐技能包']
      break
    }
    /* 第 5 步：AI 技能装配 */
    case 4: {
      await think(
        [
          '货源智能调度 /dispatch · 已安装',
          '批次溯源查询 /trace · 已安装',
          '行情分析建议 /market · 已安装',
          '质检报告生成 /qc · 已安装',
          '产销日报 /report · 已安装'
        ],
        440
      )
      pushAi('技能装配完成 ✅ 任意频道输入 / 即可调用。最后一步：创建协同频道，并给每个群设定权限边界与自动化规则。')
      wizQuick.value = ['创建频道并设定群权限']
      break
    }
    /* 第 6 步：频道 + 群权限 + 自动化规则 */
    case 5: {
      await think([
        '创建 5 个协同频道',
        '设定群权限（公开 / 私密 · 成员范围）',
        '配置数据隔离（AI 记忆仅本群 · ERP 财务对分身禁用）',
        '写入自动化规则（入厂必检 / 出海双签 / 冷链越限秒级告警）'
      ])
      pushAi('频道创建中，看左侧频道列表 👈 其中「审批-异常裁定」设为私密群，仅负责人与总控分身可见。')
      await wait(500)
      await revealAll(workspaceDataMap.hq.channels, pendingChannels, 460)
      await wait(300)
      pushAi('频道与群权限就绪 ✅ 每个群的 AI 都被关进了"数据笼子"：只能调取本群授权的数据，记忆默认不出群。要不要导入今日演示数据，让整个体系跑起来？')
      wizQuick.value = ['导入数据并启动 🚀']
      break
    }
    /* 第 7 步：导入数据 + 启动 */
    case 6: {
      await think(['导入订单 / 批次 / 行情数据', '点亮全链路驾驶舱', '启动 8 个分身实时协同', '开启风险监测心跳'])
      // 驾驶舱数据点亮（KPI / 图表 / 业务环节状态）
      dataReady.value = true
      pushAi(
        '搭建完成 🎉 蓝湾渔业全链路智能协作体系上线：5 个工作区 · 8 名成员（权限分级）· 8 个 AI 分身 · 6 类数据源 · 5 项技能 · 21 个频道（含群权限与数据隔离）。我会常驻右侧栏，随时听候调度。'
      )
      wizQuick.value = ['进入工作台 →']
      break
    }
    default: {
      finishWizard()
      wizBusy.value = false
      return
    }
  }

  wizStage.value++
  wizBusy.value = false
}

/** 完成：关闭向导并启动演示心跳 */
export function finishWizard() {
  restoreExact()
  wizardActive.value = false
  startHeartbeat()
}

/** 跳过：按原始顺序一次性精确复原 */
export function skipWizard() {
  restoreExact()
  wizardActive.value = false
  startHeartbeat()
}

function restoreExact() {
  workspaces.splice(1)
  workspaces.push(...snapWorkspaces)
  workspaceDataMap.hq.channels.splice(0)
  workspaceDataMap.hq.channels.push(...snapChannels)
  workspaceDataMap.hq.dms.splice(0)
  workspaceDataMap.hq.dms.push(...snapDms)
  // 品牌与数据一并就绪（跳过时一步到位）
  workspaceDataMap.hq.name = BRAND_NAME
  workspaces[0].title = `${BRAND_NAME}（总控中心）`
  brandReady.value = true
  dataReady.value = true
  pendingWorkspaces = []
  pendingChannels = []
  pendingHumanDms = []
  pendingBotDms = []
}
