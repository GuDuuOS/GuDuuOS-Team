<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import { instanceBrand } from '@/config/instance'

type GuideKind = 'console' | 'install'
type NoteTone = 'info' | 'warning' | 'success'

interface GuideTable {
  headers: string[]
  rows: string[][]
}

interface GuideSection {
  id: string
  number: string
  title: string
  summary: string
  steps?: string[]
  bullets?: string[]
  image?: string
  caption?: string
  code?: string
  table?: GuideTable
  note?: { title: string; text: string; tone?: NoteTone }
  extraTitle?: string
  extraCode?: string
  extraBullets?: string[]
}

interface GuideDefinition {
  label: string
  title: string
  description: string
  version: string
  updated: string
  readingTime: string
  intro: string
  sections: GuideSection[]
}

const props = defineProps<{ guide: GuideKind }>()
const guideShell = ref<HTMLElement | null>(null)

const consoleGuide: GuideDefinition = {
  label: 'OEM CONSOLE GUIDE',
  title: 'OEM 企业控制台使用指南',
  description: '从登录控制台到领取 KEY，了解实例、邀请、版本、购买和授权的完整操作流程。',
  version: 'V1.16.1',
  updated: '2026 年 8 月 2 日',
  readingTime: '约 12 分钟',
  intro: '本文面向 OEM 企业账号。页面示例中的企业名、域名、金额、订单和授权编号均为演示数据。',
  sections: [
    {
      id: 'console-start', number: '01', title: '开始使用',
      summary: '先登录企业控制台，再从左侧导航进入各项业务功能。',
      steps: [
        '打开 OEM 企业控制台，输入注册时使用的企业邮箱和密码。',
        '首次合作可切换到“OEM 注册”，完整填写企业、联系人、联系方式与邀请人。',
        '登录后确认右上角显示的是自己的企业名称；离开时主动退出。',
      ],
      table: {
        headers: ['页面', '可以完成的事情'],
        rows: [
          ['我的首页', '查看自有实例与节点运行详情'],
          ['邀请与层级', '复制邀请链接、生成二维码并查看网络统计'],
          ['版本公告', '查看节点更新和平台公告'],
          ['购买与充值', '购买节点授权或为自有节点充值 Token'],
          ['授权申请', '跟踪付款、补资料、签发与领取进度'],
          ['我的 KEY', '查看授权状态并核对绑定节点'],
        ],
      },
      note: { title: '入口提示', text: '收到邀请链接时，邀请人会自动填写；直接合作客户按页面提示填写 GUDUU。' },
    },
    {
      id: 'console-overview', number: '02', title: '我的首页：查看实例运行状态',
      summary: '首页只展示当前企业拥有的实例。点击实例卡片，可以在页面下方展开运行详情。',
      image: '/resources/oem-console/overview.png', caption: '我的首页与节点运行详情（演示数据）',
      steps: [
        '先看状态标签：“在线”表示心跳正常；“迟滞”表示心跳超过 15 分钟；“离线”表示长时间未上报。',
        '点击“查看详情”，核对实例域名、当前版本、最近心跳和 Token 余额。',
        '继续查看账号、频道、有效会员、知识库、Skill、AI Agent 与工作流等运营指标。',
      ],
      note: { title: '判断标准', text: '节点显示迟滞或离线时，先确认服务器与服务进程是否正常，不要仅凭一次刷新判断数据丢失。', tone: 'warning' },
    },
    {
      id: 'console-network', number: '03', title: '邀请与层级：分享注册链接',
      summary: '邀请页提供普通用户与合作伙伴两类入口，使用同一稳定分享码建立归属关系。',
      image: '/resources/oem-console/network.png', caption: '邀请链接、二维码与层级统计（演示数据）',
      steps: [
        '邀请普通用户：复制用户注册链接或二维码，发送给准备使用你节点的用户。',
        '邀请合作伙伴：复制 OEM 邀请链接，对方注册成功后成为你的直属下级 OEM。',
        '核对自己的分享码，避免手工修改链接中的 ref 参数。',
      ],
      note: { title: '可见范围', text: '层级统计可能因平台功能开关暂时隐藏，但分享链接仍可使用，关闭不会删除既有归属。' },
    },
    {
      id: 'console-releases', number: '04', title: '版本公告：判断是否需要操作',
      summary: '版本公告分为节点版本与 Nexus 平台更新，两类公告的处理方式不同。',
      image: '/resources/oem-console/announcements.png', caption: '节点更新与平台公告（演示数据）',
      bullets: [
        '节点版本公告：只在你的节点成功安装对应版本后展示。',
        '平台公告：属于集中托管控制台更新，通常不需要在自己的服务器安装。',
        '公告未出现时先刷新数据，再确认该版本是否适用于你的节点。',
      ],
    },
    {
      id: 'console-purchase', number: '05', title: '购买节点授权',
      summary: '一张申请只对应一种履约方式，请按真实付款路径选择，不要重复创建相同申请。',
      image: '/resources/oem-console/commerce.png', caption: '购买节点授权与 Token 充值（演示数据）',
      steps: [
        '进入“购买与充值”，确认服务端展示的当前价格。',
        '选择在线支付、企业转账或合同/免费授权。',
        '企业转账需上传 JPG、PNG 或 WebP 凭证；合同授权需填写计划域名、用途与 Token 需求。',
        '提交后转到“授权申请”跟踪，不要因页面刷新慢而重复付款。',
      ],
      note: { title: '付款安全', text: '凭证上传不等于已经到账；只有系统确认真实到账后才会签发授权。', tone: 'warning' },
      extraTitle: '给自有节点充值 Token',
      extraBullets: ['选择实例并核对实例名称与域名。', '填写数量并创建订单，按页面渠道付款。', '支付后回到首页核对 Token 余额。'],
    },
    {
      id: 'console-applications', number: '06', title: '授权申请：跟踪进度与补资料',
      summary: '所有购买和人工授权都会形成申请记录，状态决定下一步操作。',
      image: '/resources/oem-console/licenses.png', caption: '授权申请状态与可执行动作（演示数据）',
      table: {
        headers: ['状态', '正确操作'],
        rows: [
          ['待处理 / 待支付', '完成付款或等待处理，不要重复提交'],
          ['待补资料', '补充计划域名、用途或企业信息'],
          ['已批准', '在领取期限内领取 KEY'],
          ['已拒绝', '查看原因，修正条件后重新申请'],
          ['已撤回', '本申请已结束，需要时重新发起'],
        ],
      },
    },
    {
      id: 'console-keys', number: '07', title: '我的 KEY：领取、保存与绑定',
      summary: 'KEY 是节点授权凭据。明文只在限时领取时显示一次，领取后应立即安全保存。',
      image: '/resources/oem-console/keys.png', caption: '授权卡片、绑定和运行状态（演示数据）',
      steps: [
        '找到状态为“未兑换”的授权卡片，核对用途和领取期限。',
        '点击“限时领取 KEY”，明文出现后立即复制到密码管理器或服务器安全配置。',
        '节点完成兑换后，确认状态变为已绑定/运行中，并核对域名与实例名称。',
      ],
      note: { title: '关键提醒', text: '不要把 KEY 放进聊天记录、截图、公开网盘或普通文档，也不要把同一 KEY 用于多个节点。', tone: 'warning' },
    },
    {
      id: 'console-faq', number: '08', title: '常见问题',
      summary: '遇到问题先看状态与归属，再刷新数据，不要用重复付款或反复提交来碰运气。',
      table: {
        headers: ['问题', '建议处理'],
        rows: [
          ['看不到层级统计', '分享功能仍可使用；统计开启后既有关系会恢复显示'],
          ['实例迟滞或离线', '检查服务器网络、服务进程和最近心跳'],
          ['支付后状态未变化', '保留订单号和凭证，稍后刷新，不要再次付款'],
          ['KEY 已领取但未绑定', '检查 KEY 是否完整、环境变量是否生效、节点能否连接 Nexus'],
          ['账号无法登录', '提供企业名称与注册邮箱，联系服务支持完成身份核验'],
        ],
      },
      note: { title: '操作自检', text: '付款前核对金额和订单，充值前核对目标实例；重要操作后回到首页、申请页或 KEY 页确认最终状态。', tone: 'success' },
    },
  ],
}

const installGuide: GuideDefinition = {
  label: 'OEM DEPLOYMENT GUIDE',
  title: 'OEM 节点安装与上线指南',
  description: '领取 KEY、准备服务器、配置 DNS、一键安装、激活配置，再完成上线验收。',
  version: 'V1.30.2',
  updated: '2026 年 8 月 8 日',
  readingTime: '约 18 分钟',
  intro: '完整流程：领取 KEY → 复制安装命令 → SSH 执行 → 解析域名 → 浏览器激活 → 完成首次配置 → 运行 doctor.sh 验收。',
  sections: [
    {
      id: 'install-prepare', number: '01', title: '部署前准备',
      summary: '先把服务器、域名、网络和授权准备好，再执行安装命令。',
      table: {
        headers: ['项目', '最低要求', '推荐做法'],
        rows: [
          ['系统', 'Ubuntu 22.04/24.04 或 Debian 12', '使用干净服务器，不与现有业务混装'],
          ['配置', '2 核 / 4 GB / 40 GB', '4 核 / 8 GB，并预留备份空间'],
          ['权限', 'root 或可 sudo 的 SSH 账号', '使用独立运维账号'],
          ['域名', '已审批的完整域名', '提前确认可修改 DNS A 记录'],
          ['网络', '开放 TCP 80、443', '首次解析使用“仅 DNS”'],
          ['授权', '已审批、待部署的 OEM KEY', '核对域名与严格公网 IP'],
        ],
      },
      note: { title: '安全说明', text: '安装脚本会在终端询问 KEY。不要把 KEY 写进群聊、工单截图或 Shell 历史。', tone: 'warning' },
    },
    {
      id: 'install-key', number: '02', title: '领取 KEY 并复制安装命令',
      summary: '安装命令由 Nexus 根据批准域名生成，正常情况下无需手工修改参数。',
      image: '/resources/oem-install/key.png', caption: '在 OEM 门户复制绑定域名的一键安装命令',
      steps: ['登录 OEM 企业控制台。', '打开“我的 KEY”，找到“已批准·待部署”的授权。', '核对审批域名和授权状态，点击“复制安装命令”。'],
      note: { title: '域名参数', text: '门户命令已包含批准域名。不要改成未审批域名，否则激活会失败。', tone: 'warning' },
    },
    {
      id: 'install-command', number: '03', title: 'SSH 执行一键安装',
      summary: '在干净服务器粘贴一条命令，脚本会安装依赖、校验授权并拉取批准镜像。',
      code: 'curl -fsSL https://dev-nexus.guduu.co/portal/install.sh | sudo bash -s -- --domain im.example.com',
      image: '/resources/oem-install/terminal.png', caption: '一键安装终端过程与完成信息',
      steps: ['通过 SSH 登录服务器，将门户命令原样粘贴执行。', '按提示输入管理员邮箱、OEM KEY 和地区代码；KEY 不会回显。', '等待服务初始化，保存最终显示的访问地址与一次性初始密码。'],
    },
    {
      id: 'install-dns', number: '04', title: '配置 DNS 与自动 HTTPS',
      summary: '把批准域名解析到服务器公网 IP，DNS 生效后即可通过 HTTPS 访问。',
      image: '/resources/oem-install/dns.png', caption: 'DNS A 记录示例',
      steps: ['为子域名添加 A 记录，记录值填写服务器公网 IPv4。', '首次安装关闭 CDN/代理，保持“仅 DNS”，让 Caddy 直接申请证书。', '等待解析生效后访问 HTTPS 地址。'],
      note: { title: '严格 IP 绑定', text: 'Cloudflare、NAT 或错误代理都可能让实际出口 IP 与授权不一致，触发激活失败。', tone: 'warning' },
      extraTitle: '服务器已有反向代理时',
      extraCode: 'curl -fsSL https://dev-nexus.guduu.co/portal/install.sh | sudo bash -s -- --domain im.example.com --behind-proxy --proxy-port 8080',
    },
    {
      id: 'install-activation', number: '05', title: '首次访问与授权激活',
      summary: '浏览器会从节点服务器安全地向 Nexus 验证授权、域名和来源 IP。',
      image: '/resources/oem-install/activation.png', caption: 'OEM 节点授权激活页',
      steps: ['打开安装完成时显示的 HTTPS 地址。', '点击“重新验证并激活”。', '成功后进入首次配置；失败时核对域名、DNS、公网出口 IP 和系统时间。'],
    },
    {
      id: 'install-brand', number: '06', title: '首次配置 1：品牌名称与 Logo',
      summary: '外部 OEM 必须使用自己的品牌，登录页、工作台和管理后台会同步应用。',
      image: '/resources/oem-install/brand.png', caption: '品牌名称与 Logo 配置',
      steps: ['填写面向用户的产品名称。', '填写企业或组织名称。', '上传清晰的正方形 Logo 并确认品牌规则。'],
      note: { title: '品牌规则', text: '只有官网正式节点 #3 可以使用 GuDuu OS、中富通及其官方联系信息，其他节点必须使用自己的名称和 Logo。', tone: 'warning' },
    },
    {
      id: 'install-email', number: '07', title: '首次配置 2：发信邮箱',
      summary: 'SMTP 用于注册、登录验证和找回密码，开放正式用户前必须完成真实邮件测试。',
      image: '/resources/oem-install/email.png', caption: 'SMTP 发信邮箱配置',
      steps: ['填写 SMTP 主机、端口、账号与密码。', '设置发件地址、名称和 SSL/TLS 模式。', '发送测试邮件，确认邮件能真实到达。'],
      note: { title: '凭据保存', text: '统一从网页配置，不要再手工维护第二套 .env 值；密钥保存后不会回显原文。' },
    },
    {
      id: 'install-ai', number: '08', title: '首次配置 3：主 AI 与 API',
      summary: '可以使用平台官方 AI，也可以接入企业自己购买的模型 API。',
      image: '/resources/oem-install/ai.png', caption: '主 AI 接入方式选择',
      table: {
        headers: ['方式', '需要填写', '适合场景'],
        rows: [
          ['平台官方 AI', '提供方与模型，无需 API Key', '希望快速开通并用 Token 结算'],
          ['企业自有 API', '模型 ID、Base URL、API Key', '已有模型服务账号'],
        ],
      },
      note: { title: '安全边界', text: 'API Key 只录入节点后台，禁止发到聊天群、代码仓库、截图或工单。', tone: 'warning' },
    },
    {
      id: 'install-payment', number: '09', title: '首次配置 4：支付宝与微信支付 API',
      summary: '支付凭据可以在后台维护，但“已保存”不代表已经具备正式收款能力。',
      image: '/resources/oem-install/payment.png', caption: '支付宝与微信支付 API 配置',
      bullets: ['支付宝需准备 APPID、RSA2 应用私钥和支付宝公钥。', '微信支付需准备商户号、AppID、APIv3 密钥、商户私钥与平台证书。', '未配置完整凭据时，不向用户展示不可用渠道。'],
      note: { title: '上线门槛', text: '必须完成回调验签、订单幂等履约与沙箱交易验收，渠道才可以正式启用。', tone: 'warning' },
    },
    {
      id: 'install-confirm', number: '10', title: '首次配置 5：确认并进入系统',
      summary: '复核品牌、邮箱、主 AI 和支付状态；保存后仍可从系统设置修改。',
      image: '/resources/oem-install/confirm.png', caption: '首次部署配置确认页',
      steps: ['逐项检查产品名称、发信邮箱、主 AI 与支付状态。', '记录尚未完成的上线前待办。', '保存并进入系统，登录后立即修改初始密码。'],
    },
    {
      id: 'install-acceptance', number: '11', title: '上线前验收',
      summary: '页面能打开不代表部署合格，至少完成系统体检、登录、邮件、AI 和节点上报检查。',
      code: 'cd /opt/guduu-os\n./doctor.sh',
      image: '/resources/oem-install/doctor.png', caption: 'doctor.sh 与上线前业务验收',
      bullets: ['管理员登录成功并已修改初始密码。', '注册、验证和找回密码邮件真实送达。', '主 AI 完成真实对话并正常计量。', 'Nexus 显示正确的节点名称、在线状态和版本。', '更新代理 timer 正常运行。'],
      note: { title: '交付标准', text: '全部检查通过后再开放给正式用户；日志可以提交，但必须先打码所有敏感信息。', tone: 'success' },
    },
    {
      id: 'install-updates', number: '12', title: '版本更新如何工作',
      summary: '节点主动轮询并拉取镜像，正常情况下不会被平台远程强制升级。',
      steps: ['Nexus 发布节点版本后，更新代理定时拉取信息。', 'OEM 管理员阅读说明并确认安装。', '宿主代理备份数据库并拉取清单冻结的镜像 digest。', '健康检查通过后切换；失败则回到原镜像并上报原因。'],
      extraTitle: '检查更新代理',
      extraCode: 'sudo systemctl status guduu-update-agent.timer\nsudo journalctl -u guduu-update-agent.service -n 100 --no-pager',
      note: { title: '更新原则', text: '不是远程 SSH 强推，也不是强制升级；由节点自行拉取，并由 OEM 管理员确认。' },
    },
    {
      id: 'install-troubleshooting', number: '13', title: '常见问题与处理',
      summary: '按错误类别排查域名、网络、授权、镜像和宿主代理，再联系技术支持。',
      table: {
        headers: ['现象', '常见原因', '处理方法'],
        rows: [
          ['激活 IP 不匹配', '实际出口 IP 与严格绑定 IP 不一致', '核对公网出口、Cloudflare/NAT 与授权 IP'],
          ['域名打不开或证书失败', 'DNS 未生效、端口占用或开启代理', '先用仅 DNS，检查端口与防火墙'],
          ['镜像下载很慢', '服务器到镜像仓网络慢', '配置合规加速并保留足够磁盘空间'],
          ['KEY 无效', '域名不匹配或已绑定其他实例', '回到“我的 KEY”核对原申请'],
          ['更新提示无权限', '宿主 timer、目录权限或工具过旧', '检查 systemd 日志并按发布说明修复'],
        ],
      },
      note: { title: '禁止提供', text: '不要向技术支持提供 OEM KEY、管理员密码、API Key、支付私钥、数据库备份或完整 .env。', tone: 'warning' },
    },
  ],
}

const currentGuide = computed(() => props.guide === 'install' ? installGuide : consoleGuide)

watch(() => props.guide, async () => {
  await nextTick()
  guideShell.value?.scrollTo({ top: 0, behavior: 'auto' })
}, { immediate: true })

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <main ref="guideShell" class="guide-shell">
    <template v-if="instanceBrand.reservedBrandAllowed">
      <header class="guide-nav">
        <router-link class="guide-brand" to="/">
          <img v-if="instanceBrand.logoUrl" :src="instanceBrand.logoUrl" alt="" />
          <strong>{{ instanceBrand.productName }}</strong>
        </router-link>
        <nav aria-label="指南导航">
          <router-link to="/guides/oem-console" :class="{ active: props.guide === 'console' }">控制台指南</router-link>
          <router-link to="/guides/oem-install" :class="{ active: props.guide === 'install' }">安装指南</router-link>
          <router-link class="back-home" to="/">返回首页</router-link>
        </nav>
      </header>

      <section class="guide-hero">
        <div>
          <span>{{ currentGuide.label }}</span>
          <h1>{{ currentGuide.title }}</h1>
          <p>{{ currentGuide.description }}</p>
          <div class="guide-meta"><b>{{ currentGuide.version }}</b><span>更新于 {{ currentGuide.updated }}</span><span>{{ currentGuide.readingTime }}</span></div>
        </div>
      </section>

      <section class="guide-layout">
        <aside class="guide-toc">
          <small>本页目录</small>
          <button v-for="section in currentGuide.sections" :key="section.id" type="button" @click="scrollToSection(section.id)">
            <span>{{ section.number }}</span>{{ section.title }}
          </button>
        </aside>

        <article class="guide-article">
          <div class="guide-intro"><span>阅读说明</span><p>{{ currentGuide.intro }}</p></div>

          <section v-for="section in currentGuide.sections" :id="section.id" :key="section.id" class="guide-section">
            <div class="section-title"><span>{{ section.number }}</span><div><h2>{{ section.title }}</h2><p>{{ section.summary }}</p></div></div>

            <figure v-if="section.image">
              <img :src="section.image" :alt="section.caption || section.title" loading="lazy" />
              <figcaption>{{ section.caption }}</figcaption>
            </figure>

            <pre v-if="section.code"><code>{{ section.code }}</code></pre>

            <ol v-if="section.steps" class="guide-steps">
              <li v-for="(step, index) in section.steps" :key="step"><span>{{ index + 1 }}</span><p>{{ step }}</p></li>
            </ol>

            <ul v-if="section.bullets" class="guide-bullets">
              <li v-for="item in section.bullets" :key="item">{{ item }}</li>
            </ul>

            <div v-if="section.table" class="table-wrap">
              <table>
                <thead><tr><th v-for="header in section.table.headers" :key="header">{{ header }}</th></tr></thead>
                <tbody><tr v-for="row in section.table.rows" :key="row.join('|')"><td v-for="cell in row" :key="cell">{{ cell }}</td></tr></tbody>
              </table>
            </div>

            <div v-if="section.note" class="guide-note" :class="section.note.tone || 'info'">
              <strong>{{ section.note.title }}</strong><p>{{ section.note.text }}</p>
            </div>

            <div v-if="section.extraTitle" class="guide-extra">
              <h3>{{ section.extraTitle }}</h3>
              <pre v-if="section.extraCode"><code>{{ section.extraCode }}</code></pre>
              <ul v-if="section.extraBullets" class="guide-bullets"><li v-for="item in section.extraBullets" :key="item">{{ item }}</li></ul>
            </div>
          </section>

          <div class="guide-finish">
            <span>指南阅读完成</span>
            <h2>{{ props.guide === 'console' ? '接下来，可以开始申请 OEM 授权' : '准备完成后，请按步骤逐项部署与验收' }}</h2>
            <a href="https://dev-nexus.guduu.co/portal/?register=1#oem-licenses" target="_blank" rel="noopener">进入 OEM 企业控制台 <span>↗</span></a>
          </div>
        </article>
      </section>
    </template>

    <section v-else class="guide-unavailable">
      <h1>该资料仅在官方站点提供</h1>
      <p>请返回当前实例首页，查看由该实例运营方提供的帮助资料。</p>
      <router-link to="/">返回首页</router-link>
    </section>
  </main>
</template>

<style scoped>
.guide-shell { --guide-accent: #6f5bd4; height: 100vh; overflow: auto; background: #f7f5fb; color: #241f31; font-family: var(--font-body); scroll-behavior: smooth; }
.guide-nav { min-height: 72px; box-sizing: border-box; padding: 12px max(5vw, 28px); position: sticky; top: 0; z-index: 10; display: flex; align-items: center; justify-content: space-between; gap: 24px; border-bottom: 1px solid rgba(50,38,91,.09); background: rgba(250,249,252,.92); backdrop-filter: blur(18px); }
.guide-brand { display: flex; align-items: center; gap: 11px; min-width: 0; }
.guide-brand img { width: 38px; height: 38px; object-fit: contain; border-radius: 10px; }
.guide-brand strong { font: 700 18px var(--font-heading); white-space: nowrap; }
.guide-nav nav { display: flex; align-items: center; gap: 8px; }
.guide-nav nav a { padding: 9px 13px; border-radius: 9px; color: #746c83; font-size: 13px; font-weight: 700; }
.guide-nav nav a.active { color: var(--guide-accent); background: #ebe7fb; }
.guide-nav nav .back-home { margin-left: 8px; color: #fff; background: #2b2538; }
.guide-hero { padding: 92px max(5vw, 28px) 82px; background: radial-gradient(circle at 80% 14%, rgba(172,156,255,.46), transparent 35%), linear-gradient(145deg,#29233b,#45376c); color: #fff; }
.guide-hero > div { max-width: 980px; }
.guide-hero > div > span { color: #c8bdff; font-size: 11px; font-weight: 800; letter-spacing: .2em; }
.guide-hero h1 { margin: 18px 0; font: 700 clamp(42px,5vw,70px)/1.12 var(--font-heading); letter-spacing: -.04em; }
.guide-hero p { max-width: 760px; color: #d7d0e9; font-size: 18px; line-height: 1.8; }
.guide-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 10px 22px; margin-top: 30px; color: #c4badc; font-size: 12px; }
.guide-meta b { padding: 7px 10px; border: 1px solid rgba(255,255,255,.18); border-radius: 999px; color: #fff; }
.guide-layout { max-width: 1280px; margin: 0 auto; padding: 64px max(4vw,24px) 100px; display: grid; grid-template-columns: 250px minmax(0, 850px); justify-content: center; align-items: start; gap: 64px; }
.guide-toc { max-height: calc(100vh - 112px); overflow: auto; position: sticky; top: 98px; display: grid; gap: 4px; padding: 20px; border: 1px solid #e5e0ef; border-radius: 16px; background: #fff; box-shadow: 0 16px 40px rgba(51,39,88,.06); }
.guide-toc small { margin: 2px 8px 12px; color: #9a92a8; font-size: 10px; font-weight: 800; letter-spacing: .14em; }
.guide-toc button { display: grid; grid-template-columns: 25px 1fr; gap: 8px; width: 100%; padding: 8px; border: 0; border-radius: 8px; background: none; color: #5e566a; text-align: left; font: 500 12px/1.45 var(--font-body); cursor: pointer; }
.guide-toc button:hover { color: var(--guide-accent); background: #f5f2ff; }
.guide-toc button span { color: #a297c7; font-size: 10px; font-weight: 800; }
.guide-article { min-width: 0; }
.guide-intro { margin-bottom: 26px; padding: 22px 24px; border: 1px solid #ded8ef; border-radius: 14px; background: #f0ecfb; }
.guide-intro span { color: var(--guide-accent); font-size: 11px; font-weight: 800; letter-spacing: .12em; }
.guide-intro p { margin: 8px 0 0; color: #655d73; line-height: 1.7; }
.guide-section { margin-bottom: 26px; padding: 38px; scroll-margin-top: 96px; border: 1px solid #e5e0ec; border-radius: 20px; background: #fff; box-shadow: 0 18px 50px rgba(46,34,77,.055); }
.section-title { display: grid; grid-template-columns: 46px 1fr; gap: 18px; align-items: start; }
.section-title > span { width: 46px; height: 46px; display: grid; place-items: center; border-radius: 13px; background: #eeeafd; color: var(--guide-accent); font-size: 11px; font-weight: 800; }
.section-title h2 { margin: 0 0 8px; font: 700 27px/1.3 var(--font-heading); }
.section-title p { margin: 0; color: #746d7c; line-height: 1.7; }
figure { margin: 30px 0; overflow: hidden; border: 1px solid #ddd7e7; border-radius: 14px; background: #f4f1f7; }
figure img { width: 100%; height: auto; display: block; }
figcaption { padding: 11px 15px; border-top: 1px solid #e2ddeb; color: #8a8295; background: #faf9fc; font-size: 11px; }
.guide-steps { margin: 28px 0 0; padding: 0; display: grid; gap: 12px; list-style: none; }
.guide-steps li { display: grid; grid-template-columns: 30px 1fr; gap: 12px; align-items: start; }
.guide-steps li > span { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 50%; background: #2c2638; color: #fff; font-size: 10px; font-weight: 800; }
.guide-steps p { margin: 3px 0 0; color: #50495a; line-height: 1.75; }
.guide-bullets { margin: 26px 0 0; padding-left: 20px; color: #50495a; }
.guide-bullets li { margin: 10px 0; padding-left: 5px; line-height: 1.7; }
.guide-bullets li::marker { color: var(--guide-accent); }
pre { margin: 28px 0 0; padding: 18px 20px; overflow-x: auto; border-radius: 12px; background: #292433; color: #f3efff; font: 12px/1.75 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; word-break: break-word; }
.table-wrap { margin-top: 28px; overflow-x: auto; border: 1px solid #e1dce8; border-radius: 12px; }
table { width: 100%; min-width: 560px; border-collapse: collapse; font-size: 13px; }
th, td { padding: 13px 14px; border-bottom: 1px solid #eeeaf2; text-align: left; vertical-align: top; line-height: 1.55; }
th { background: #f1eef8; color: #4e4563; font-size: 11px; }
tr:last-child td { border-bottom: 0; }
td:first-child { color: #3e374b; font-weight: 700; }
.guide-note { margin-top: 28px; padding: 18px 20px; border-left: 4px solid #7863df; border-radius: 10px; background: #f1edff; }
.guide-note.warning { border-left-color: #db7b36; background: #fff4e9; }
.guide-note.success { border-left-color: #3d9a69; background: #edf9f2; }
.guide-note strong { font-size: 13px; }
.guide-note p { margin: 7px 0 0; color: #625a6d; font-size: 13px; line-height: 1.7; }
.guide-extra { margin-top: 30px; padding-top: 26px; border-top: 1px solid #ebe7ef; }
.guide-extra h3 { margin: 0; font: 700 18px var(--font-heading); }
.guide-finish { margin-top: 54px; padding: 45px; border-radius: 20px; background: #2b2538; color: #fff; }
.guide-finish > span { color: #bfb4f7; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.guide-finish h2 { max-width: 650px; margin: 13px 0 28px; font: 700 30px/1.35 var(--font-heading); }
.guide-finish a { display: inline-block; padding: 12px 18px; border-radius: 9px; background: var(--guide-accent); color: #fff; font-size: 13px; font-weight: 800; }
.guide-finish a span { margin-left: 7px; }
.guide-unavailable { min-height: 100vh; box-sizing: border-box; padding: 60px 24px; display: grid; place-content: center; justify-items: center; text-align: center; }
.guide-unavailable h1 { margin: 0; font: 700 32px var(--font-heading); }
.guide-unavailable p { color: #726a7b; }
.guide-unavailable a { margin-top: 14px; padding: 11px 18px; border-radius: 9px; background: #2b2538; color: #fff; }
@media (max-width: 920px) {
  .guide-layout { grid-template-columns: 1fr; gap: 28px; }
  .guide-toc { max-height: none; position: static; grid-template-columns: repeat(2, minmax(0,1fr)); }
  .guide-toc small { grid-column: 1/-1; }
}
@media (max-width: 680px) {
  .guide-nav { align-items: flex-start; }
  .guide-brand strong { display: none; }
  .guide-nav nav { flex-wrap: wrap; justify-content: flex-end; }
  .guide-nav nav a { padding: 8px 9px; font-size: 11px; }
  .guide-nav nav .back-home { margin-left: 0; }
  .guide-hero { padding: 62px 20px 58px; }
  .guide-hero h1 { font-size: 40px; }
  .guide-hero p { font-size: 16px; }
  .guide-layout { padding: 34px 16px 72px; }
  .guide-toc { display: none; }
  .guide-section { padding: 26px 20px; border-radius: 16px; }
  .section-title { grid-template-columns: 38px 1fr; gap: 12px; }
  .section-title > span { width: 38px; height: 38px; border-radius: 11px; }
  .section-title h2 { font-size: 22px; }
  figure { margin: 24px -8px; border-radius: 10px; }
  .guide-finish { padding: 32px 24px; }
  .guide-finish h2 { font-size: 25px; }
}
</style>
