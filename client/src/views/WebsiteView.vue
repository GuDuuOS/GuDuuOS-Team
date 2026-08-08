<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { instanceBrand, instanceWebsite } from '@/config/instance'

interface EditionContent {
  eyebrow: string
  headline: string
  description: string
  capabilityTitle: string
  previewTitle: string
  previewLabel: string
  features: Array<{ title: string; description: string }>
  ctaTitle: string
}

const route = useRoute()
const siteShell = ref<HTMLElement | null>(null)
// 当前官网优先交付个人版；企业版内容保留，待正式开放时只需恢复对应路由与入口。
const isPersonal = computed(() => route.path !== '/enterprise')
const year = new Date().getFullYear()
const ownerName = computed(() => instanceBrand.companyName || instanceBrand.productName)
const footerLine = computed(() => instanceWebsite.footerText || `© ${year} ${ownerName.value}`)
const officialCompany = '中富通集团股份有限公司'
const officialStockCode = '深交所创业板 · 股票代码 300560'
// 生产环境只允许激活实例 #3 注入中富通官方信息；本地开发保留预览能力。
const isOfficialWebsite = computed(() => instanceBrand.instanceId === 3
  || (import.meta.env.DEV && instanceBrand.instanceId === null))
const footerAbout = computed(() => isOfficialWebsite.value
  ? 'GuDuu OS 是一套面向个人与团队的本地部署智能协作系统。它以主 AI 为统一入口，连接频道、专业 Agent、知识、任务和工作流，让沟通、记忆与执行持续发生在同一个空间。'
  : instanceWebsite.description)
const contactCompany = computed(() => instanceBrand.companyName
  || (isOfficialWebsite.value ? officialCompany : instanceBrand.productName))
const contactEmail = computed(() => instanceWebsite.contactEmail
  || (isOfficialWebsite.value ? 'ftii@zftii.com' : ''))
const contactPhone = computed(() => instanceWebsite.contactPhone
  || (isOfficialWebsite.value ? '0591-83769999' : ''))
const contactAddress = computed(() => instanceWebsite.contactAddress
  || (isOfficialWebsite.value
    ? '福建省福州市鼓楼区铜盘路软件大道89号软件园F区4号楼20、21、22层'
    : ''))
const contactWebsite = computed(() => isOfficialWebsite.value
  ? 'https://www.zftii.com/' : instanceWebsite.supportUrl)
const emailHref = computed(() => contactEmail.value ? `mailto:${contactEmail.value}` : '')
const phoneHref = computed(() => contactPhone.value
  ? `tel:${contactPhone.value.replace(/[^+\d]/g, '')}` : '')

const enterpriseContent = computed<EditionContent>(() => ({
  eyebrow: '企业智能协作 · 私有部署 · 数据自主',
  headline: instanceWebsite.headline,
  description: instanceWebsite.description,
  capabilityTitle: '一个入口，连接团队的日常工作',
  previewTitle: '企业协作中枢',
  previewLabel: 'ENTERPRISE',
  features: [
    { title: '统一沟通', description: '频道、群组与私信集中管理，让信息始终留在团队上下文中。' },
    { title: '智能协作', description: '主 AI、知识与任务协同工作，帮助团队把讨论更快变成行动。' },
    { title: '企业自主', description: '独立部署、品牌定制与多模型接入，让企业掌握自己的配置与数据。' },
  ],
  ctaTitle: `让团队从一次对话，走向持续交付`,
}))

const personalContent: EditionContent = {
  eyebrow: '个人智能工作台 · AI 团队 · 本地部署',
  headline: '一个人，也可以拥有一支随时待命的智能团队',
  description: '把主 AI、智能体、知识、任务和工作流放进同一个空间，让想法真正被组织、执行并持续推进。',
  capabilityTitle: '不止与 AI 对话，更让 AI 开始工作',
  previewTitle: '我的 AI 工作台',
  previewLabel: 'PERSONAL',
  features: [
    { title: '主 AI 中枢', description: '用自然语言交代目标，由主 AI 拆解任务、组建专班并持续跟进。' },
    { title: 'AI 同事团队', description: '创建研究、文案、运营等专属智能体，让不同角色各司其职。' },
    { title: '任务与知识', description: '把项目频道、任务看板和个人知识库连成可追踪的执行过程。' },
  ],
  ctaTitle: '一个人，也能把复杂的事情持续推进',
}

const content = computed(() => isPersonal.value ? personalContent : enterpriseContent.value)

const memoryLayers = [
  { index: 'L1', label: '全局中枢', title: '主 AI 记忆', description: '持续理解你的身份、偏好、长期目标与重要决定，负责在不同工作之间保持整体连续性。' },
  { index: 'L2', label: '频道沙盒', title: '频道独立记忆', description: '每个频道拥有隔离的上下文、规则、知识与任务，频道之间不会随意串用信息。' },
  { index: 'L3', label: '专业个体', title: 'AI Agent 独立记忆', description: '每个 Agent 保留自己的角色、专业知识与执行经历，协作时按职责调用，不互相覆盖。' },
]

const collaborationFlow = [
  { index: '01', title: '交代目标', description: '用自然语言说明想做什么，以及时间、质量和边界要求。' },
  { index: '02', title: '主 AI 拆解', description: '识别任务结构，补齐关键信息，并规划合适的执行路径。' },
  { index: '03', title: 'AI 协同执行', description: '调度研究、文案、数据、项目等专业 Agent 分工协作。' },
  { index: '04', title: '真人确认', description: '关键结果回到你面前审核，确认后再完成对外动作。' },
]

const downloadGroups = [
  {
    eyebrow: 'DESKTOP',
    title: '桌面端',
    description: '为长时间工作和多窗口协作设计，支持 macOS 与 Windows。',
    platforms: [
      { mark: '⌘', name: 'macOS', detail: 'Apple Silicon / Intel' },
      { mark: '▦', name: 'Windows', detail: 'Windows 10 / 11' },
    ],
  },
  {
    eyebrow: 'MOBILE',
    title: '手机端',
    description: '随时接收消息、跟进任务，并与自己的 AI 团队保持连接。',
    platforms: [
      { mark: '●', name: 'iPhone / iPad', detail: 'iOS / iPadOS' },
      { mark: '▲', name: 'Android', detail: '手机 / 平板' },
    ],
  },
]

watch(isPersonal, async () => {
  await nextTick()
  siteShell.value?.scrollTo({ top: 0, behavior: 'auto' })
})

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <main ref="siteShell" class="site-shell" :class="{ personal: isPersonal }">
    <header class="site-nav">
      <div class="nav-start">
        <router-link class="site-brand" to="/" aria-label="官网首页">
          <img v-if="instanceBrand.logoUrl" :src="instanceBrand.logoUrl" alt="" />
          <span v-else class="brand-mark">{{ instanceBrand.productName.slice(0, 1) }}</span>
          <strong>{{ instanceBrand.productName }}</strong>
        </router-link>
        <nav class="edition-switch" aria-label="版本切换">
          <router-link to="/" aria-current="page">个人版</router-link>
          <span class="edition-disabled" aria-disabled="true">
            <span>企业版</span><em>COMING SOON</em>
          </span>
        </nav>
      </div>
      <nav class="site-links" aria-label="官网导航">
        <button type="button" @click="scrollToSection('capabilities')">产品能力</button>
        <button type="button" @click="scrollToSection('advantages')">核心优势</button>
        <button v-if="instanceBrand.reservedBrandAllowed" type="button" @click="scrollToSection('downloads')">客户端下载</button>
        <button v-if="instanceBrand.reservedBrandAllowed" type="button" @click="scrollToSection('resources')">白皮书与指南</button>
        <a v-if="instanceBrand.reservedBrandAllowed" class="nav-oem" href="https://dev-nexus.guduu.co/portal/?register=1#oem-licenses" target="_blank" rel="noopener">OEM 申请</a>
        <button type="button" @click="scrollToSection('contact')">联系我们</button>
        <router-link class="nav-login" to="/login">登录</router-link>
      </nav>
    </header>

    <section class="hero">
      <div class="hero-copy">
        <span class="eyebrow">{{ content.eyebrow }}</span>
        <h1>{{ content.headline }}</h1>
        <p>{{ content.description }}</p>
        <div class="hero-actions">
          <router-link class="primary" to="/login">进入{{ isPersonal ? '个人版' : '企业版' }}</router-link>
          <button class="secondary" type="button" @click="scrollToSection('capabilities')">了解产品能力</button>
        </div>
        <small v-if="instanceBrand.companyName">由 {{ instanceBrand.companyName }} 提供</small>
      </div>

      <div class="product-preview" :aria-label="`${content.previewTitle}界面示意`">
        <img
          v-if="instanceBrand.reservedBrandAllowed"
          class="workbench-shot"
          src="/product-workbench.jpg"
          :alt="`${instanceBrand.productName} 工作台界面：工作区、数据看板与中枢 AI`"
        />
        <template v-else>
          <div class="preview-top">
          <span class="window-dots"><i /><i /><i /></span>
          <span>{{ instanceBrand.productName }}</span>
          <em>{{ content.previewLabel }}</em>
          </div>
          <div class="preview-body">
            <aside>
              <span class="mini-logo">{{ isPersonal ? '我' : '企' }}</span>
              <b class="active" /><b /><b /><b />
            </aside>
            <section>
              <div class="preview-heading">
                <div><small>{{ isPersonal ? '今天，和你的 AI 团队一起' : '实时连接每一个团队' }}</small><div class="preview-title">{{ content.previewTitle }}</div></div>
                <span class="online-pill"><i /> ONLINE</span>
              </div>
              <template v-if="!isPersonal">
                <div class="preview-cards">
                  <article><span>协作空间</span><strong>12</strong></article>
                  <article><span>进行中任务</span><strong>36</strong></article>
                  <article><span>AI 执行</span><strong>128</strong></article>
                </div>
                <div class="preview-activity"><span class="activity-avatar">AI</span><div><b>中枢 AI 正在推进项目</b><small>已完成任务拆解，等待团队确认</small></div><em>刚刚</em></div>
              </template>
              <template v-else>
                <div class="personal-command"><span class="spark">✦</span><div><small>向主 AI 交代一个目标</small><b>帮我规划下个月的内容发布，并组建一个创作专班</b></div><span class="send-arrow">↗</span></div>
                <div class="agent-row">
                  <article><span>研</span><div><b>研究员</b><small>整理资料中</small></div></article>
                  <article><span>文</span><div><b>文案搭档</b><small>等待任务</small></div></article>
                  <article><span>项</span><div><b>项目经理</b><small>跟进进度</small></div></article>
                </div>
              </template>
            </section>
          </div>
        </template>
      </div>
    </section>

    <section id="capabilities" class="capabilities">
      <div class="section-head"><span>{{ isPersonal ? 'PERSONAL' : 'ENTERPRISE' }}</span><h2>{{ content.capabilityTitle }}</h2></div>
      <div class="feature-grid">
        <article v-for="(feature, index) in content.features" :key="feature.title">
          <i>0{{ index + 1 }}</i><h3>{{ feature.title }}</h3><p>{{ feature.description }}</p>
        </article>
      </div>
    </section>

    <section id="advantages" class="advantages">
      <div class="section-head advantage-head">
        <span>WHY {{ instanceBrand.productName.toUpperCase() }}</span>
        <h2>不是多一个聊天框，<br />而是拥有一套真正属于你的 AI 工作系统</h2>
        <p>从部署位置、记忆方式到多 AI 协作，每一层都围绕“持续工作”设计，而不只是回答一次问题。</p>
      </div>

      <div class="advantage-showcase">
        <article class="local-first-card">
          <div class="advantage-copy">
            <span class="detail-index">01 · LOCAL FIRST</span>
            <h3>本地部署，数据与能力都由你掌握</h3>
            <p>系统可以部署在你自己的服务器或受控环境中。聊天、知识、工作流和模型配置不需要依附某个单一云端产品，敏感信息的边界更清楚。</p>
            <ul>
              <li><i />独立实例与自有域名</li>
              <li><i />可选择国内外模型、本地模型或接入自有 API</li>
              <li><i />知识、规则与工作流留在自己的工作空间</li>
            </ul>
          </div>
          <div class="deployment-visual" aria-label="本地部署架构示意">
            <div class="deploy-cloud">
              <span>国内外模型自由选择</span>
              <b>DeepSeek · 通义千问 · 豆包 · 智谱 GLM · Kimi · 文心一言</b>
              <small>OpenAI · Claude · Gemini · 本地模型 · 自有 API</small>
            </div>
            <span class="deploy-line">安全连接</span>
            <div class="deploy-server">
              <span class="server-status"><i /> YOUR SERVER</span>
              <b>你的独立工作空间</b>
              <div><span>沟通</span><span>知识</span><span>AI</span><span>工作流</span></div>
            </div>
            <small>数据边界由你决定</small>
          </div>
        </article>

        <article class="memory-card">
          <div class="advantage-copy">
            <span class="detail-index">02 · THREE-LAYER MEMORY</span>
            <h3>三层记忆，让 AI 越来越懂你的工作</h3>
            <p>记忆按照归属范围分层：主 AI 负责全局连续性，频道像独立沙盒一样保存自己的上下文，每个 Agent 则拥有互不覆盖的专业记忆。</p>
          </div>
          <div class="memory-stack">
            <div v-for="layer in memoryLayers" :key="layer.index" class="memory-layer">
              <span>{{ layer.index }}</span>
              <div><small>{{ layer.label }}</small><b>{{ layer.title }}</b><p>{{ layer.description }}</p></div>
            </div>
          </div>
        </article>
      </div>

      <article class="collaboration-card">
        <div class="collab-copy">
          <span class="detail-index">03 · AI WORKS WITH AI</span>
          <h3>一个主 AI，组织多个专业 AI 一起完成目标</h3>
          <p>你只需要面对一个主入口。主 AI 负责理解意图、拆解任务和协调进度，专业 Agent 各自处理研究、创作、分析与执行，并把关键决定交回给人。</p>
          <div class="collab-tags"><span>统一入口</span><span>专业分工</span><span>共享上下文</span><span>真人审核</span></div>
        </div>
        <div class="ai-orbit" aria-label="主 AI 协同多个专业 AI 示意">
          <div class="orbit-core"><small>MAIN AI</small><b>主 AI</b><span>正在协调 4 项工作</span></div>
          <div class="orbit-agent agent-a"><i>研</i><b>研究 Agent</b><small>资料分析中</small></div>
          <div class="orbit-agent agent-b"><i>文</i><b>文案 Agent</b><small>等待资料</small></div>
          <div class="orbit-agent agent-c"><i>数</i><b>数据 Agent</b><small>指标已整理</small></div>
          <div class="orbit-agent agent-d"><i>项</i><b>项目 Agent</b><small>跟进节点</small></div>
        </div>
      </article>

      <div class="collaboration-flow" aria-label="AI 协作流程">
        <article v-for="step in collaborationFlow" :key="step.index">
          <span>{{ step.index }}</span><h3>{{ step.title }}</h3><p>{{ step.description }}</p>
        </article>
      </div>
    </section>

    <section v-if="instanceBrand.reservedBrandAllowed" id="downloads" class="downloads">
      <div class="download-heading">
        <div class="section-head">
          <span>DOWNLOAD</span>
          <h2>从电脑到手机，<br />随时回到你的工作空间</h2>
        </div>
        <div class="web-ready">
          <span><i /> WEB AVAILABLE</span>
          <p>桌面端与手机端正在打磨中，现在可以先使用网页版。</p>
          <router-link to="/login">进入网页版 <b>→</b></router-link>
        </div>
      </div>

      <div class="download-grid">
        <article v-for="group in downloadGroups" :key="group.title" class="download-group">
          <span>{{ group.eyebrow }}</span>
          <h3>{{ group.title }}</h3>
          <p>{{ group.description }}</p>
          <div class="platform-list">
            <button v-for="platform in group.platforms" :key="platform.name" type="button" disabled>
              <i>{{ platform.mark }}</i>
              <span><b>{{ platform.name }}</b><small>{{ platform.detail }}</small></span>
              <em>COMING SOON</em>
            </button>
          </div>
        </article>
      </div>
      <p class="download-note">正式安装包与应用商店入口开放后将在这里提供。当前不提供测试包或非官方来源下载。</p>
    </section>

    <section v-if="instanceBrand.reservedBrandAllowed" id="oem" class="oem-section">
      <div class="oem-copy">
        <span class="oem-kicker">OEM PARTNER PROGRAM</span>
        <h2>用你的品牌，交付一套完整的智能协作系统</h2>
        <p>面向服务商、行业解决方案团队与企业合作伙伴，提供独立品牌、节点授权、私有部署和持续版本支持。</p>
        <div class="oem-actions">
          <a href="https://dev-nexus.guduu.co/portal/?register=1#oem-licenses" target="_blank" rel="noopener">申请成为 OEM <span>↗</span></a>
          <button type="button" @click="scrollToSection('resources')">先看 OEM 教程</button>
        </div>
      </div>
      <ol class="oem-steps" aria-label="OEM 申请流程">
        <li><span>01</span><div><b>提交申请</b><p>注册企业控制台，填写品牌、部署域名与使用场景。</p></div></li>
        <li><span>02</span><div><b>审核与授权</b><p>平台主管审核资料，完成付款或授权后领取专属 KEY。</p></div></li>
        <li><span>03</span><div><b>部署与交付</b><p>按图文指南安装节点，通过体检后开放给正式用户。</p></div></li>
      </ol>
    </section>

    <section v-if="instanceBrand.reservedBrandAllowed" id="resources" class="resources">
      <div class="section-head">
        <span>RESOURCE LIBRARY</span>
        <h2>白皮书与指南</h2>
        <p>从申请授权到节点交付，把关键流程整理成可以直接照着操作的资料。</p>
      </div>
      <div class="resource-grid">
        <router-link class="resource-card" to="/guides/oem-console">
          <div class="resource-cover dark"><img src="/resources/oem-console-guide-cover.png" alt="OEM 企业控制台界面预览" /></div>
          <div class="resource-info">
            <span class="resource-format">网页指南 · V1.16.1</span>
            <h3>OEM 企业控制台使用指南</h3>
            <p>查看实例、邀请层级、版本公告、充值、授权申请与 KEY 管理的完整操作说明。</p>
            <strong>打开指南 <span>→</span></strong>
          </div>
        </router-link>
        <router-link class="resource-card" to="/guides/oem-install">
          <div class="resource-cover"><img src="/resources/oem-install-guide-cover.png" alt="OEM 节点安装验收界面预览" /></div>
          <div class="resource-info">
            <span class="resource-format">网页指南 · V1.30.2</span>
            <h3>OEM 节点一键安装图文指南</h3>
            <p>覆盖申请 KEY、准备服务器、配置 DNS、一键安装、激活配置与上线验收。</p>
            <strong>打开指南 <span>→</span></strong>
          </div>
        </router-link>
        <article class="resource-card coming" aria-label="产品白皮书即将推出">
          <div class="resource-cover whitepaper-cover">
            <span>GU DUU OS</span><b>AI 工作方式<br />产品白皮书</b><em>COMING SOON</em>
          </div>
          <div class="resource-info">
            <span class="resource-format">WHITEPAPER · 整理中</span>
            <h3>GuDuu OS 产品白皮书</h3>
            <p>系统介绍主 AI、智能体团队、知识、任务、工作流与私有部署的产品方法。</p>
            <strong>即将发布</strong>
          </div>
        </article>
      </div>
    </section>

    <section class="cta">
      <div><span>READY TO START</span><h2>{{ content.ctaTitle }}</h2></div>
      <router-link to="/login">进入{{ isPersonal ? '个人版' : '企业版' }}</router-link>
    </section>

    <footer id="contact" class="site-footer">
      <div class="footer-about">
        <div class="footer-brand">
          <img v-if="instanceBrand.logoUrl" :src="instanceBrand.logoUrl" alt="" />
          <span v-else class="brand-mark">{{ instanceBrand.productName.slice(0, 1) }}</span>
          <strong>{{ instanceBrand.productName }}</strong>
        </div>
        <h2>关于 {{ instanceBrand.productName }}</h2>
        <p>{{ footerAbout }}</p>
        <div class="footer-values"><span>本地部署</span><span>三层记忆</span><span>多 AI 协作</span></div>
      </div>
      <div class="contacts">
        <span class="footer-kicker">CONTACT US</span>
        <h2>联系我们</h2>
        <strong>{{ contactCompany }}</strong>
        <span v-if="isOfficialWebsite" class="contact-stock">{{ officialStockCode }}</span>
        <dl v-if="contactEmail || contactPhone || contactAddress">
          <div v-if="contactPhone"><dt>电话</dt><dd><a :href="phoneHref">{{ contactPhone }}</a></dd></div>
          <div v-if="contactEmail"><dt>邮箱</dt><dd><a :href="emailHref">{{ contactEmail }}</a></dd></div>
          <div v-if="contactAddress"><dt>地址</dt><dd>{{ contactAddress }}</dd></div>
        </dl>
        <p v-else class="contact-empty">联系方式暂未填写</p>
        <a v-if="contactWebsite" class="contact-website" :href="contactWebsite" target="_blank" rel="noopener">{{ isOfficialWebsite ? '访问中富通官网' : '访问帮助中心' }} <span>↗</span></a>
      </div>
      <div class="footer-links">
        <h3>快速入口</h3>
        <router-link to="/">个人版</router-link>
        <span class="footer-coming">企业版 <small>COMING SOON</small></span>
        <button v-if="instanceBrand.reservedBrandAllowed" type="button" @click="scrollToSection('downloads')">客户端下载</button>
        <a v-if="instanceBrand.reservedBrandAllowed" href="https://dev-nexus.guduu.co/portal/?register=1#oem-licenses" target="_blank" rel="noopener">OEM 申请</a>
        <button v-if="instanceBrand.reservedBrandAllowed" type="button" @click="scrollToSection('resources')">白皮书与指南</button>
        <a v-if="instanceWebsite.supportUrl" :href="instanceWebsite.supportUrl">帮助中心</a>
        <a v-if="instanceWebsite.privacyUrl" :href="instanceWebsite.privacyUrl">隐私政策</a>
      </div>
      <p class="copyright">{{ footerLine }}</p>
    </footer>
  </main>
</template>

<style scoped>
.site-shell {
  --site-accent: #e96f1d;
  --site-accent-dark: #9b4310;
  height: 100vh;
  overflow: auto;
  background: #fbf7f0;
  color: #241b14;
  font-family: var(--font-body);
  scroll-behavior: smooth;
}
.site-shell.personal { --site-accent: #7965e8; --site-accent-dark: #4f3bbd; }
.site-nav {
  height: 76px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 max(5vw, 28px);
  position: sticky;
  top: 0;
  z-index: 5;
  background: rgba(251, 247, 240, .92);
  backdrop-filter: blur(18px);
  border-bottom: 1px solid rgba(74, 43, 21, .08);
}
.nav-start, .site-brand, .site-links, .edition-switch { display: flex; align-items: center; }
.nav-start { gap: 34px; }
.site-brand { gap: 11px; min-width: 0; }
.site-brand img, .footer-brand img { width: 38px; height: 38px; object-fit: contain; border-radius: 10px; }
.brand-mark { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 10px; background: var(--site-accent); color: white; font-weight: 800; }
.site-brand strong { font-family: var(--font-heading); font-size: 18px; white-space: nowrap; }
.edition-switch { gap: 4px; padding: 4px; border: 1px solid #e7d9cd; border-radius: 999px; background: rgba(255,255,255,.66); }
.edition-switch a, .edition-disabled { min-height: 31px; box-sizing: border-box; padding: 7px 15px; border-radius: 999px; color: #78675a; font-size: 13px; font-weight: 650; transition: .2s ease; }
.edition-switch a[aria-current="page"] { color: #fff; background: #2d211a; box-shadow: 0 4px 12px rgba(45,33,26,.16); }
.site-shell.personal .edition-switch a[aria-current="page"] { background: var(--site-accent-dark); }
.edition-disabled { display: flex; align-items: center; gap: 7px; color: #a69d96; background: #ece8e4; cursor: not-allowed; user-select: none; }
.edition-disabled em { padding: 2px 5px; border-radius: 999px; background: rgba(255,255,255,.8); color: #aaa09a; font-size: 7px; font-style: normal; font-weight: 800; letter-spacing: .08em; line-height: 1; }
.site-links { gap: 28px; color: #6e5d50; font-size: 14px; }
.site-links button { padding: 8px 0; border: 0; background: none; color: inherit; font: inherit; cursor: pointer; }
.site-links button:hover { color: var(--site-accent-dark); }
.nav-oem { padding: 8px 14px; border-radius: 999px; background: rgba(121,101,232,.1); color: var(--site-accent-dark); font-weight: 700; }
.nav-login { padding: 9px 18px; border: 1px solid #d9b99d; border-radius: 999px; color: var(--site-accent-dark); }
.hero {
  min-height: 0;
  padding: 104px max(5vw, 28px) 118px;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  justify-items: center;
  position: relative;
  overflow: hidden;
  text-align: center;
  background: radial-gradient(circle at 85% 15%, rgba(255, 217, 184, .42), transparent 34%), linear-gradient(145deg, #fffaf3, #f6ede2);
}
.personal .hero { background: radial-gradient(circle at 83% 16%, rgba(194, 184, 255, .38), transparent 34%), linear-gradient(145deg, #fffaf6, #f2effb); }
.hero::before { content: 'GUDUU OS'; position: absolute; top: 225px; left: 50%; transform: translateX(-50%); color: rgba(79,59,189,.045); font: 800 clamp(100px,17vw,270px)/.8 var(--font-heading); letter-spacing: -.07em; white-space: nowrap; pointer-events: none; }
.hero-copy { width: min(1060px, 100%); position: relative; z-index: 1; }
.eyebrow, .section-head > span, .cta > div > span { font-size: 12px; letter-spacing: .19em; color: var(--site-accent); font-weight: 800; }
.hero h1 { font-family: var(--font-heading); font-size: clamp(52px, 6.5vw, 92px); line-height: 1.05; letter-spacing: -.055em; margin: 24px auto; text-wrap: balance; }
.hero-copy > p { margin: 0 auto; font-size: 18px; line-height: 1.8; color: #6f5b4d; max-width: 780px; }
.hero-actions { display: flex; justify-content: center; gap: 12px; margin: 34px 0 18px; }
.hero-actions a, .hero-actions button, .cta > a { padding: 13px 22px; border-radius: 10px; font: inherit; font-weight: 750; cursor: pointer; }
.primary, .cta > a { background: var(--site-accent); color: #fff; box-shadow: 0 12px 28px color-mix(in srgb, var(--site-accent) 22%, transparent); }
.secondary { border: 1px solid #d8c2b0; color: #35271e; background: rgba(255,255,255,.7); }
.hero-copy small { color: #9b8170; }
.product-preview { width: min(1240px, 100%); margin-top: 72px; position: relative; z-index: 1; border: 1px solid #ead5c2; background: #fff; box-shadow: 0 35px 90px rgba(104,64,27,.14); border-radius: 24px; overflow: hidden; }
.personal .product-preview { border-color: #ddd6f6; box-shadow: 0 35px 90px rgba(79,59,189,.13); }
.workbench-shot { width: 100%; height: auto; aspect-ratio: 16 / 10; display: block; object-fit: cover; object-position: top left; }
.preview-top { height: 52px; display: flex; align-items: center; gap: 12px; padding: 0 18px; background: #2d211a; color: #ddcfc5; }
.personal .preview-top { background: #27213e; color: #e4def8; }
.window-dots { display: flex; gap: 7px; }
.window-dots i { width: 9px; height: 9px; border-radius: 50%; background: var(--site-accent); }
.window-dots i:nth-child(2) { opacity: .6; }
.window-dots i:nth-child(3) { opacity: .3; }
.preview-top > span:not(.window-dots) { font-size: 12px; }
.preview-top em { margin-left: auto; padding: 4px 8px; border: 1px solid rgba(255,255,255,.16); border-radius: 999px; font-size: 9px; font-style: normal; letter-spacing: .14em; }
.preview-body { height: 390px; display: grid; grid-template-columns: 92px 1fr; }
.preview-body aside { background: #f3e9de; padding: 24px 18px; display: grid; align-content: start; justify-items: center; gap: 20px; }
.personal .preview-body aside { background: #f0edf9; }
.mini-logo { width: 34px; height: 34px; display: grid; place-items: center; margin-bottom: 4px; border-radius: 11px; background: var(--site-accent); color: #fff; font-size: 12px; font-weight: 800; }
.preview-body aside b { width: 54px; height: 9px; border-radius: 8px; background: #d5bdab; }
.personal .preview-body aside b { background: #ccc4eb; }
.preview-body aside b.active { background: var(--site-accent); }
.preview-body section { padding: 34px 36px; }
.preview-heading { display: flex; align-items: center; justify-content: space-between; gap: 15px; }
.preview-heading small { display: block; margin-bottom: 6px; color: #9c8879; font-size: 10px; }
.preview-title { font: 700 24px var(--font-heading); }
.online-pill { display: flex; align-items: center; gap: 5px; padding: 6px 9px; border-radius: 999px; background: #eff8f1; color: #447d51; font-size: 8px; letter-spacing: .12em; }
.online-pill i { width: 5px; height: 5px; border-radius: 50%; background: #55a867; }
.preview-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 27px 0; }
.preview-cards article { min-width: 0; padding: 16px; border-radius: 12px; background: linear-gradient(145deg,#fff6ec,#f5e5d6); border: 1px solid #efdfd0; }
.preview-cards span, .preview-cards strong { display: block; }
.preview-cards span { color: #8e7866; font-size: 10px; }
.preview-cards strong { margin-top: 13px; font: 700 25px var(--font-heading); }
.preview-activity { display: flex; align-items: center; gap: 12px; margin-top: 20px; padding: 15px; border: 1px solid #eee4db; border-radius: 12px; }
.activity-avatar { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 10px; background: #2d211a; color: #fff; font-size: 10px; font-weight: 800; }
.preview-activity div { display: grid; gap: 4px; min-width: 0; }
.preview-activity b { font-size: 11px; }
.preview-activity small { color: #9a8879; font-size: 9px; }
.preview-activity em { margin-left: auto; color: #ad9b8d; font-size: 9px; font-style: normal; }
.personal-command { display: flex; align-items: center; gap: 14px; margin: 27px 0 22px; padding: 19px; border: 1px solid #ded7f6; border-radius: 14px; background: linear-gradient(145deg,#faf8ff,#f0ecff); }
.spark { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 11px; background: var(--site-accent); color: #fff; }
.personal-command div { display: grid; gap: 6px; min-width: 0; }
.personal-command small { color: #8176a5; font-size: 9px; }
.personal-command b { font-size: 11px; line-height: 1.5; }
.send-arrow { margin-left: auto; color: var(--site-accent-dark); font-size: 20px; }
.agent-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.agent-row article { display: flex; align-items: center; gap: 9px; min-width: 0; padding: 13px 11px; border: 1px solid #ebe7f6; border-radius: 12px; }
.agent-row article > span { width: 29px; height: 29px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 9px; background: #eeeaff; color: var(--site-accent-dark); font-size: 10px; font-weight: 800; }
.agent-row article div { min-width: 0; display: grid; gap: 4px; }
.agent-row b, .agent-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-row b { font-size: 10px; }
.agent-row small { color: #9a91b7; font-size: 8px; }
.capabilities { padding: 110px max(5vw,28px); background: #fff; scroll-margin-top: 76px; }
.capabilities .section-head { text-align: center; }
.capabilities .section-head h2 { margin-left: auto; margin-right: auto; }
.section-head h2 { font: 700 clamp(32px,4vw,50px)/1.2 var(--font-heading); margin: 14px 0 48px; max-width: 760px; }
.feature-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 22px; }
.feature-grid article { padding: 30px; border: 1px solid #eaded3; border-radius: 16px; background: #fffdf9; }
.personal .feature-grid article { border-color: #e5e0f5; background: #fdfcff; }
.feature-grid i { font-style: normal; color: var(--site-accent); font-weight: 800; }
.feature-grid h3 { font: 700 22px var(--font-heading); margin: 26px 0 12px; }
.feature-grid p { color: #756457; line-height: 1.75; }
.advantages { padding: 112px max(5vw,28px); overflow: hidden; background: #f5f2fa; scroll-margin-top: 76px; }
.advantage-head { display: grid; grid-template-columns: minmax(0,1fr) minmax(280px,.55fr); column-gap: 8vw; align-items: end; }
.advantage-head > span { grid-column: 1/-1; }
.advantage-head h2 { margin-bottom: 0; max-width: 900px; }
.advantage-head > p { margin: 0 0 5px; color: #736b7f; font-size: 16px; line-height: 1.8; }
.advantage-showcase { margin-top: 58px; display: grid; grid-template-columns: 1.03fr .97fr; gap: 22px; }
.local-first-card, .memory-card, .collaboration-card { min-width: 0; overflow: hidden; border: 1px solid #e1dceb; border-radius: 24px; background: #fff; box-shadow: 0 24px 65px rgba(52,40,91,.07); }
.local-first-card { display: grid; grid-template-rows: auto 1fr; }
.advantage-copy { padding: 42px 42px 34px; }
.detail-index { color: var(--site-accent-dark); font-size: 10px; font-weight: 850; letter-spacing: .15em; }
.advantage-copy h3, .collab-copy h3 { margin: 15px 0 14px; font: 700 clamp(27px,2.5vw,38px)/1.25 var(--font-heading); letter-spacing: -.025em; }
.advantage-copy > p, .collab-copy > p { margin: 0; color: #716879; line-height: 1.8; }
.advantage-copy ul { margin: 25px 0 0; padding: 0; display: grid; gap: 11px; list-style: none; }
.advantage-copy li { display: flex; align-items: center; gap: 10px; color: #50485b; font-size: 13px; }
.advantage-copy li i { width: 17px; height: 17px; display: grid; place-items: center; border-radius: 50%; background: #eae6fb; }
.advantage-copy li i::after { content: '✓'; color: var(--site-accent-dark); font-size: 9px; font-style: normal; font-weight: 900; }
.deployment-visual { min-height: 330px; box-sizing: border-box; padding: 32px; display: grid; place-items: center; align-content: center; position: relative; background: radial-gradient(circle at 50% 70%, rgba(121,101,232,.26), transparent 42%), #29243a; color: #fff; }
.deploy-cloud { width: min(86%, 540px); box-sizing: border-box; padding: 16px 20px; display: grid; gap: 6px; position: relative; z-index: 1; border: 1px solid rgba(255,255,255,.13); border-radius: 13px; background: rgba(255,255,255,.07); text-align: center; }
.deploy-cloud span { color: #aba2c8; font-size: 9px; letter-spacing: .1em; }
.deploy-cloud b { font-size: 11px; line-height: 1.55; }
.deploy-cloud small { color: #aaa1c0; font-size: 8px; line-height: 1.5; }
.deploy-line { height: 44px; width: 1px; display: grid; place-items: center; position: relative; color: transparent; background: linear-gradient(#8c7be8,rgba(140,123,232,.2)); }
.deploy-line::after { content: ''; width: 7px; height: 7px; border-radius: 50%; position: absolute; top: 18px; background: #8f7af4; box-shadow: 0 0 16px #8f7af4; }
.deploy-server { width: 82%; box-sizing: border-box; padding: 24px; display: grid; gap: 12px; position: relative; z-index: 1; border: 1px solid #8d7beb; border-radius: 17px; background: #f9f7ff; color: #29243a; box-shadow: 0 18px 45px rgba(0,0,0,.26); }
.server-status { display: flex; align-items: center; gap: 7px; color: #7668bb; font-size: 8px; font-weight: 850; letter-spacing: .12em; }
.server-status i { width: 6px; height: 6px; border-radius: 50%; background: #55bd7a; box-shadow: 0 0 9px #55bd7a; }
.deploy-server > b { font: 700 20px var(--font-heading); }
.deploy-server > div { display: grid; grid-template-columns: repeat(4,1fr); gap: 7px; }
.deploy-server > div span { padding: 8px 5px; border-radius: 8px; background: #eeeafd; color: #6859b8; font-size: 9px; text-align: center; }
.deployment-visual > small { margin-top: 16px; color: #aaa1c0; font-size: 9px; letter-spacing: .08em; }
.memory-card { display: flex; flex-direction: column; }
.memory-stack { flex: 1; padding: 0 34px 34px; display: flex; flex-direction: column-reverse; justify-content: flex-end; }
.memory-layer { min-height: 92px; box-sizing: border-box; padding: 18px 20px; display: grid; grid-template-columns: 40px 1fr; gap: 14px; align-items: start; position: relative; border: 1px solid #ded7f2; border-radius: 15px; background: #faf8ff; box-shadow: 0 14px 25px rgba(65,48,122,.07); }
.memory-layer + .memory-layer { margin-bottom: -8px; }
.memory-layer:nth-child(2) { margin-left: 16px; margin-right: 16px; background: #f4f0ff; }
.memory-layer:nth-child(3) { margin-left: 32px; margin-right: 32px; background: #ece7ff; }
.memory-layer > span { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 10px; background: #7763dc; color: #fff; font-size: 10px; font-weight: 850; }
.memory-layer div { min-width: 0; display: grid; gap: 4px; }
.memory-layer small { color: #8b80a9; font-size: 9px; font-weight: 750; letter-spacing: .08em; }
.memory-layer b { font: 700 15px var(--font-heading); }
.memory-layer p { margin: 1px 0 0; color: #746b82; font-size: 11px; line-height: 1.55; }
.collaboration-card { min-height: 510px; margin-top: 22px; display: grid; grid-template-columns: .86fr 1.14fr; background: #28223b; color: #fff; }
.collab-copy { padding: 56px 50px; align-self: center; }
.collab-copy .detail-index { color: #bcb0ff; }
.collab-copy > p { color: #c5bed4; }
.collab-tags { margin-top: 28px; display: flex; flex-wrap: wrap; gap: 8px; }
.collab-tags span { padding: 7px 10px; border: 1px solid rgba(255,255,255,.12); border-radius: 999px; color: #d5cee5; font-size: 10px; }
.ai-orbit { min-height: 510px; position: relative; overflow: hidden; background: radial-gradient(circle at center, rgba(126,105,235,.28), transparent 23%), radial-gradient(circle at center, transparent 34%, rgba(255,255,255,.07) 34.2%, transparent 34.8%), radial-gradient(circle at center, transparent 48%, rgba(255,255,255,.06) 48.2%, transparent 48.8%); }
.orbit-core, .orbit-agent { box-sizing: border-box; position: absolute; display: grid; box-shadow: 0 18px 40px rgba(0,0,0,.25); }
.orbit-core { width: 180px; height: 180px; left: 50%; top: 50%; transform: translate(-50%,-50%); place-content: center; justify-items: center; border: 1px solid #9785f8; border-radius: 50%; background: linear-gradient(145deg,#826ff0,#5542bd); }
.orbit-core small { color: #d9d3ff; font-size: 8px; font-weight: 850; letter-spacing: .15em; }
.orbit-core b { margin: 8px 0; font: 700 28px var(--font-heading); }
.orbit-core span { color: #ded9f8; font-size: 9px; }
.orbit-agent { width: 145px; min-height: 72px; padding: 13px; grid-template-columns: 34px 1fr; gap: 9px; align-items: center; border: 1px solid rgba(255,255,255,.12); border-radius: 13px; background: rgba(255,255,255,.08); backdrop-filter: blur(10px); }
.orbit-agent i { width: 34px; height: 34px; grid-row: 1/3; display: grid; place-items: center; border-radius: 10px; background: #7564d7; color: #fff; font-style: normal; font-size: 11px; font-weight: 800; }
.orbit-agent b { font-size: 11px; }
.orbit-agent small { color: #aaa2ba; font-size: 8px; }
.agent-a { left: 5%; top: 14%; }
.agent-b { right: 5%; top: 14%; }
.agent-c { left: 7%; bottom: 13%; }
.agent-d { right: 7%; bottom: 13%; }
.collaboration-flow { margin-top: 22px; display: grid; grid-template-columns: repeat(4,1fr); gap: 1px; overflow: hidden; border: 1px solid #e2ddea; border-radius: 18px; background: #e2ddea; }
.collaboration-flow article { padding: 28px; position: relative; background: #fff; }
.collaboration-flow article:not(:last-child)::after { content: '→'; position: absolute; right: -9px; top: 28px; z-index: 1; width: 18px; height: 18px; display: grid; place-items: center; border-radius: 50%; background: #7763dc; color: #fff; font-size: 9px; }
.collaboration-flow span { color: #8a7ad8; font-size: 10px; font-weight: 850; }
.collaboration-flow h3 { margin: 18px 0 9px; font: 700 18px var(--font-heading); }
.collaboration-flow p { margin: 0; color: #756d7e; font-size: 12px; line-height: 1.7; }
.downloads { padding: 112px max(5vw,28px); background: #fff; scroll-margin-top: 76px; }
.download-heading { display: grid; grid-template-columns: 1fr minmax(300px,.52fr); gap: 7vw; align-items: end; }
.download-heading .section-head h2 { margin-bottom: 0; }
.web-ready { padding: 26px; border: 1px solid #ded8ef; border-radius: 16px; background: #f8f6fc; }
.web-ready > span { display: flex; align-items: center; gap: 8px; color: #518269; font-size: 9px; font-weight: 850; letter-spacing: .13em; }
.web-ready > span i { width: 7px; height: 7px; border-radius: 50%; background: #55b57b; box-shadow: 0 0 10px rgba(85,181,123,.55); }
.web-ready p { margin: 10px 0 16px; color: #716a79; font-size: 12px; line-height: 1.6; }
.web-ready a { color: var(--site-accent-dark); font-size: 12px; font-weight: 800; }
.web-ready a b { margin-left: 5px; }
.download-grid { margin-top: 50px; display: grid; grid-template-columns: repeat(2,1fr); gap: 22px; }
.download-group { padding: 38px; border: 1px solid #e3deeb; border-radius: 21px; background: #fcfbfe; }
.download-group > span { color: #8b7bd8; font-size: 9px; font-weight: 850; letter-spacing: .16em; }
.download-group > h3 { margin: 12px 0 8px; font: 700 28px var(--font-heading); }
.download-group > p { margin: 0; color: #776f80; line-height: 1.7; }
.platform-list { margin-top: 28px; display: grid; gap: 10px; }
.platform-list button { width: 100%; min-height: 72px; padding: 12px 14px; display: grid; grid-template-columns: 42px 1fr auto; gap: 12px; align-items: center; border: 1px solid #e3dfea; border-radius: 13px; background: #f1eff4; color: #88818e; text-align: left; cursor: not-allowed; }
.platform-list button > i { width: 40px; height: 40px; display: grid; place-items: center; border-radius: 11px; background: #e2dee7; color: #7a737f; font-style: normal; font-size: 17px; font-weight: 800; }
.platform-list button > span { display: grid; gap: 4px; }
.platform-list button b { color: #635d68; font-size: 13px; }
.platform-list button small { font-size: 9px; }
.platform-list button em { padding: 5px 7px; border-radius: 999px; background: #e5e1e8; color: #908a94; font-size: 7px; font-style: normal; font-weight: 850; letter-spacing: .09em; }
.download-note { margin: 18px 0 0; color: #9a939e; font-size: 10px; text-align: center; }
.oem-section { margin: 0 max(5vw,28px) 110px; padding: 64px; display: grid; grid-template-columns: .9fr 1.1fr; gap: 7vw; border-radius: 26px; background: radial-gradient(circle at 10% 10%, rgba(121,101,232,.28), transparent 36%), #27213e; color: #fff; scroll-margin-top: 90px; }
.oem-kicker { color: #bfb4ff; font-size: 11px; font-weight: 800; letter-spacing: .18em; }
.oem-copy h2 { margin: 18px 0; max-width: 620px; font: 700 clamp(30px,3.2vw,48px)/1.2 var(--font-heading); }
.oem-copy > p { max-width: 600px; color: #c8c1dd; font-size: 16px; line-height: 1.8; }
.oem-actions { display: flex; gap: 12px; margin-top: 30px; }
.oem-actions a, .oem-actions button { padding: 13px 20px; border-radius: 10px; font: inherit; font-weight: 750; cursor: pointer; }
.oem-actions a { background: #7965e8; color: #fff; box-shadow: 0 12px 30px rgba(0,0,0,.2); }
.oem-actions a span { margin-left: 8px; }
.oem-actions button { border: 1px solid rgba(255,255,255,.22); background: rgba(255,255,255,.06); color: #fff; }
.oem-steps { margin: 0; padding: 0; display: grid; gap: 12px; list-style: none; }
.oem-steps li { display: grid; grid-template-columns: 42px 1fr; gap: 16px; padding: 18px 20px; border: 1px solid rgba(255,255,255,.12); border-radius: 14px; background: rgba(255,255,255,.055); }
.oem-steps li > span { width: 42px; height: 42px; display: grid; place-items: center; border-radius: 12px; background: rgba(121,101,232,.26); color: #c9c0ff; font-size: 11px; font-weight: 800; }
.oem-steps b { font: 700 16px var(--font-heading); }
.oem-steps p { margin: 6px 0 0; color: #bcb5cf; font-size: 13px; line-height: 1.6; }
.resources { padding: 0 max(5vw,28px) 110px; background: #fff; scroll-margin-top: 90px; }
.resources .section-head > p { max-width: 650px; margin: -32px 0 48px; color: #79695d; font-size: 16px; line-height: 1.75; }
.resource-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 22px; }
.resource-card { min-width: 0; overflow: hidden; display: flex; flex-direction: column; border: 1px solid #e4dfef; border-radius: 18px; background: #fff; box-shadow: 0 18px 45px rgba(54,42,96,.08); transition: transform .2s ease, box-shadow .2s ease; }
a.resource-card:hover { transform: translateY(-4px); box-shadow: 0 24px 58px rgba(54,42,96,.13); }
.resource-cover { height: 210px; overflow: hidden; background: #f6f1eb; border-bottom: 1px solid #ebe5f1; }
.resource-cover img { width: 100%; height: 100%; display: block; object-fit: cover; object-position: center; }
.resource-cover.dark img { object-position: left top; }
.resource-info { flex: 1; padding: 25px; display: flex; flex-direction: column; align-items: flex-start; }
.resource-format { color: var(--site-accent-dark); font-size: 10px; font-weight: 800; letter-spacing: .11em; }
.resource-info h3 { margin: 13px 0 10px; font: 700 21px/1.35 var(--font-heading); }
.resource-info p { margin: 0 0 22px; color: #786b62; line-height: 1.7; }
.resource-info strong { margin-top: auto; color: var(--site-accent-dark); font-size: 13px; }
.resource-info strong span { margin-left: 6px; }
.resource-card.coming { opacity: .72; }
.whitepaper-cover { box-sizing: border-box; padding: 28px; display: flex; flex-direction: column; align-items: flex-start; background: radial-gradient(circle at 85% 15%, #dcd4ff, transparent 34%), linear-gradient(145deg,#f8f5ff,#ece7fb); }
.whitepaper-cover > span { color: #7564d0; font-size: 10px; font-weight: 800; letter-spacing: .18em; }
.whitepaper-cover b { margin-top: 22px; font: 700 25px/1.35 var(--font-heading); }
.whitepaper-cover em { margin-top: auto; padding: 6px 9px; border-radius: 999px; background: #dfdaf4; color: #7564b0; font-size: 8px; font-style: normal; font-weight: 800; letter-spacing: .12em; }
.cta { margin: 0 max(5vw,28px); padding: 55px 60px; border-radius: 22px; background: #2b1e17; color: #fff; display: flex; align-items: center; justify-content: space-between; gap: 30px; }
.personal .cta { background: #27213e; }
.cta h2 { font: 700 clamp(28px,3vw,42px)/1.25 var(--font-heading); margin: 12px 0 0; }
.site-footer { margin-top: 90px; padding: 76px max(5vw,28px) 28px; display: grid; grid-template-columns: minmax(0,1.15fr) minmax(340px,.85fr); gap: 60px 9vw; border-top: 1px solid #dfd0c2; background: #f5f1eb; scroll-margin-top: 76px; }
.footer-brand { display: flex; align-items: center; gap: 11px; }
.footer-about h2, .contacts h2 { margin: 25px 0 14px; font: 700 clamp(28px,3vw,42px)/1.2 var(--font-heading); }
.footer-about > p { max-width: 720px; margin: 0; color: #6f635a; font-size: 15px; line-height: 1.85; }
.footer-values { margin-top: 24px; display: flex; flex-wrap: wrap; gap: 8px; }
.footer-values span { padding: 7px 10px; border: 1px solid #dcd2c9; border-radius: 999px; color: #75685f; font-size: 10px; font-weight: 750; }
.footer-kicker { color: var(--site-accent-dark); font-size: 10px; font-weight: 850; letter-spacing: .16em; }
.contacts { padding: 32px; border: 1px solid #ddd2c9; border-radius: 18px; background: rgba(255,255,255,.58); }
.contacts h2 { margin-top: 10px; }
.contacts > strong { display: block; margin-bottom: 7px; font-size: 14px; }
.contact-stock { display: inline-flex; margin-bottom: 22px; padding: 5px 8px; border-radius: 999px; background: #ebe6fa; color: var(--site-accent-dark); font-size: 9px; font-weight: 800; letter-spacing: .05em; }
.contacts dl { margin: 0; display: grid; gap: 12px; }
.contacts dl > div { display: grid; grid-template-columns: 42px 1fr; gap: 12px; align-items: start; }
.contacts dt { color: #9a8c82; font-size: 11px; }
.contacts dd { margin: 0; color: #665a51; font-size: 12px; line-height: 1.65; }
.contacts dd a { color: inherit; }
.contact-empty { color: #8b7e75; }
.contact-website { display: inline-block; margin-top: 22px; color: var(--site-accent-dark); font-size: 12px; font-weight: 800; }
.contact-website span { margin-left: 6px; }
.footer-links { grid-column: 1/-1; padding-top: 25px; display: flex; align-items: center; flex-wrap: wrap; gap: 10px 22px; border-top: 1px solid #dfd5cc; }
.footer-links h3 { margin: 0 10px 0 0; font-size: 12px; }
.footer-links a { color: #79695d; line-height: 1.5; }
.footer-coming { display: flex; align-items: center; gap: 7px; margin-top: 10px; color: #aaa09a; line-height: 1.5; }
.footer-links .footer-coming { margin-top: 0; }
.footer-coming small { padding: 2px 5px; border-radius: 999px; background: #ece8e4; font-size: 7px; font-weight: 800; letter-spacing: .08em; }
.footer-links button { display: block; margin: 0; padding: 0; border: 0; background: none; color: #79695d; font: inherit; line-height: 1.5; cursor: pointer; }
.copyright { grid-column: 1/-1; border-top: 1px solid #e4d7cb; padding-top: 22px; margin-top: 20px; color: #9a887a; font-size: 12px; }
@media (max-width: 1000px) {
  .nav-start { gap: 18px; }
  .hero { padding-top: 72px; }
  .oem-section { grid-template-columns: 1fr; gap: 38px; padding: 48px; }
  .resource-grid { grid-template-columns: 1fr 1fr; }
  .resource-card.coming { grid-column: 1/-1; }
  .advantage-head, .download-heading { grid-template-columns: 1fr; gap: 28px; }
  .advantage-showcase { grid-template-columns: 1fr; }
  .collaboration-card { grid-template-columns: 1fr; }
  .ai-orbit { min-height: 500px; }
  .collaboration-flow { grid-template-columns: repeat(2,1fr); }
  .collaboration-flow article:nth-child(2)::after { display: none; }
}
@media (max-width: 1120px) { .site-links button { display: none; } }
@media (max-width: 760px) {
  .site-nav { height: auto; min-height: 66px; padding: 10px 20px; gap: 10px; }
  .nav-start { gap: 12px; }
  .site-brand strong { max-width: 130px; overflow: hidden; text-overflow: ellipsis; }
  .edition-switch a, .edition-disabled { padding: 6px 10px; font-size: 12px; }
  .site-links { gap: 8px; }
  .nav-oem { display: none; }
  .hero { padding: 64px 20px 78px; }
  .hero h1 { font-size: 43px; }
  .hero-copy > p { font-size: 16px; }
  .capabilities { padding: 78px 20px; }
  .feature-grid { grid-template-columns: 1fr; }
  .advantages, .downloads { padding: 78px 20px; }
  .advantage-copy, .collab-copy { padding: 34px 26px; }
  .collaboration-flow { grid-template-columns: 1fr; }
  .collaboration-flow article:not(:last-child)::after { content: '↓'; right: 25px; top: auto; bottom: -9px; }
  .download-grid { grid-template-columns: 1fr; }
  .download-group { padding: 30px 24px; }
  .oem-section { margin: 0 20px 78px; padding: 34px 26px; }
  .oem-actions { flex-direction: column; align-items: stretch; text-align: center; }
  .resources { padding: 0 20px 78px; }
  .resource-grid { grid-template-columns: 1fr; }
  .resource-card.coming { grid-column: auto; }
  .cta { margin: 0 20px; padding: 40px; align-items: flex-start; flex-direction: column; }
  .site-footer { padding: 58px 20px 24px; grid-template-columns: 1fr; gap: 38px; }
  .footer-links, .copyright { grid-column: auto; }
}
@media (max-width: 540px) {
  .site-brand img, .brand-mark { width: 32px; height: 32px; }
  .site-brand strong { display: none; }
  .nav-start { flex: 1; }
  .edition-switch { margin-left: auto; }
  .nav-login { padding: 8px 13px; }
  .hero-actions { flex-direction: column; align-items: stretch; text-align: center; }
  .product-preview { display: block; margin-top: 42px; border-radius: 14px; }
  .workbench-shot { aspect-ratio: 16 / 10; }
  .deployment-visual { min-height: 300px; padding: 24px 14px; }
  .deploy-server { width: 94%; }
  .memory-stack { padding: 0 18px 28px; }
  .memory-layer { grid-template-columns: 34px 1fr; padding: 15px; }
  .memory-layer:nth-child(2) { margin-left: 8px; margin-right: 8px; }
  .memory-layer:nth-child(3) { margin-left: 16px; margin-right: 16px; }
  .memory-layer > span { width: 32px; height: 32px; }
  .ai-orbit { min-height: 440px; }
  .orbit-core { width: 145px; height: 145px; }
  .orbit-agent { width: 123px; min-height: 66px; grid-template-columns: 29px 1fr; padding: 10px; }
  .orbit-agent i { width: 29px; height: 29px; }
  .agent-a, .agent-c { left: 3%; }
  .agent-b, .agent-d { right: 3%; }
  .platform-list button { grid-template-columns: 38px 1fr; }
  .platform-list button > i { width: 36px; height: 36px; }
  .platform-list button em { grid-column: 2; justify-self: start; }
  .cta { padding: 32px 24px; }
  .contacts { padding: 26px 22px; }
  .footer-links { align-items: flex-start; flex-direction: column; gap: 12px; }
}
</style>
