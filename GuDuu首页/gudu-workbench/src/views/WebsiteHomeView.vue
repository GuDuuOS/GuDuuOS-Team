<template>
  <div ref="siteShell" class="site-shell" @scroll.passive="updateScroll">
    <header class="site-nav" :class="{ scrolled }">
      <a class="site-brand" href="#top" aria-label="GuDuu OS 首页" @click.prevent="scrollToSection('top')">
        <img src="/gudu-logo.svg" alt="" />
        <span>GuDuu OS</span>
      </a>

      <nav class="edition-switch" aria-label="版本切换">
        <RouterLink class="edition-off" :to="{ name: 'website' }">个人版</RouterLink>
        <span class="edition-on">企业版</span>
      </nav>

      <nav class="site-nav-links" aria-label="官网导航">
        <a href="#product" @click.prevent="scrollToSection('product')">产品</a>
        <a href="#solutions" @click.prevent="scrollToSection('solutions')">解决方案</a>
        <a href="#advantages" @click.prevent="scrollToSection('advantages')">特点</a>
        <a href="#case" @click.prevent="scrollToSection('case')">案例</a>
      </nav>

      <div class="nav-actions">
        <RouterLink class="site-nav-cta cta-orange" :to="{ name: 'dashboard' }">
          进入案例
          <span>↗</span>
        </RouterLink>
        <a class="site-nav-login dim" :href="appHref">登录 / 注册</a>
      </div>
    </header>

    <main id="top">
      <section class="hero-section">
        <div class="hero-aurora hero-aurora-one"></div>
        <div class="hero-aurora hero-aurora-two"></div>
        <div class="hero-grid"></div>

        <div class="hero-copy">
          <div class="hero-kicker reveal reveal-1">
            <span class="status-pulse"></span>
            企业级 AI 协作操作系统
          </div>
          <h1 class="reveal reveal-2">
            让组织拥有<br />
            <span class="gradient-text">会工作的<br class="hero-h1-br" />智能分身</span>
          </h1>
          <p class="hero-lead reveal reveal-3">
            GuDuu OS 连接员工、智能分身、企业知识、数据与现有业务系统，
            为企业构建从理解、决策到执行的 AI 原生工作方式。
          </p>
          <div class="hero-actions reveal reveal-4">
            <RouterLink class="primary-button" :to="{ name: 'dashboard' }">
              体验 GuDuu OS
              <span class="button-arrow">→</span>
            </RouterLink>
            <a class="ghost-button dim" :href="appHref">
              登录 / 注册
              <span class="button-arrow">→</span>
            </a>
            <a class="text-button" href="#product" @click.prevent="scrollToSection('product')">
              探索 GuDuu OS
              <span>↓</span>
            </a>
          </div>
          <div class="hero-proof reveal reveal-5">
            <span>连接每个业务角色</span>
            <i></i>
            <span>理解每份组织知识</span>
            <i></i>
            <span>持续执行真实任务</span>
          </div>
        </div>

        <div class="hero-system reveal reveal-3" aria-label="GuDuu OS 智能协作界面动态演示">
          <div class="orbit orbit-one"></div>
          <div class="orbit orbit-two"></div>
          <div class="system-glow"></div>

          <div class="agent-node node-sales">
            <span class="node-icon">销</span>
            <span class="node-copy"><b>销售分身</b><small>发现加急订单</small></span>
          </div>
          <div class="agent-node node-data">
            <span class="node-icon">数</span>
            <span class="node-copy"><b>数据分身</b><small>已完成经营分析</small></span>
          </div>
          <div class="agent-node node-ops">
            <span class="node-icon">运</span>
            <span class="node-copy"><b>运营分身</b><small>正在调配资源</small></span>
          </div>

          <div class="os-window">
            <div class="window-topbar">
              <div class="window-brand">
                <img src="/gudu-logo.svg" alt="" />
                <span>GuDuu OS</span>
              </div>
              <div class="window-search">搜索工作、知识或同事</div>
              <div class="window-avatar">林</div>
            </div>
            <div class="window-body">
              <aside class="window-rail">
                <span class="rail-dot active"></span>
                <span class="rail-dot"></span>
                <span class="rail-dot"></span>
                <span class="rail-dot"></span>
              </aside>
              <aside class="window-sidebar">
                <div class="sidebar-title">示例企业</div>
                <div class="sidebar-label">智能频道</div>
                <div class="sidebar-item active"><i></i>企业经营驾驶舱</div>
                <div class="sidebar-item"><i></i>项目与运营</div>
                <div class="sidebar-item"><i></i>客户与增长</div>
                <div class="sidebar-label second">AI 分身</div>
                <div class="sidebar-person"><b>G</b><span>GuDuu 总控</span><em></em></div>
                <div class="sidebar-person"><b>销</b><span>销售分身</span><em></em></div>
              </aside>
              <div class="window-content">
                <div class="content-heading">
                  <div><b>企业经营驾驶舱</b><span>实时业务协作空间</span></div>
                  <span class="live-badge">LIVE</span>
                </div>
                <div class="mini-kpis">
                  <div><small>经营目标</small><strong>82<em>%</em></strong><span>↑ 12.8%</span></div>
                  <div><small>待推进事项</small><strong>18<em>项</em></strong><span>跨 4 部门</span></div>
                  <div><small>AI 今日协同</small><strong>86<em>次</em></strong><span>节省 6.5h</span></div>
                </div>
                <div class="activity-card">
                  <div class="activity-head">
                    <span><b>G</b> GuDuu 总控</span>
                    <small>刚刚</small>
                  </div>
                  <p>已完成经营数据分析，识别 3 项风险并生成跨部门执行计划。</p>
                  <div class="task-flow">
                    <span class="done">数据核验</span><i>→</i>
                    <span class="done">责任匹配</span><i>→</i>
                    <span class="working">任务推进</span>
                  </div>
                </div>
                <div class="command-bar">
                  <span class="command-spark">✦</span>
                  <span class="command-text">{{ typedCommand }}<i></i></span>
                  <kbd>⌘ ↵</kbd>
                </div>
              </div>
            </div>
          </div>

          <div class="signal-card">
            <span class="signal-icon">✓</span>
            <span><b>任务已自动推进</b><small>3 个分身完成协作</small></span>
          </div>
        </div>

        <a href="#product" class="scroll-hint" aria-label="向下浏览" @click.prevent="scrollToSection('product')">
          <span></span>
          SCROLL TO EXPLORE
        </a>
      </section>

      <section id="product" class="manifesto-section">
        <div class="section-eyebrow">THE OPERATING SYSTEM FOR AI WORK</div>
        <h2>不是孤立的 AI 工具。<br />是企业智能化的<span>统一工作底座。</span></h2>
        <div class="manifesto-grid">
          <article>
            <strong>01</strong>
            <h3>统一连接</h3>
            <p>连接员工、知识、数据、SaaS 与业务系统，为智能工作建立完整上下文。</p>
          </article>
          <article>
            <strong>02</strong>
            <h3>智能协同</h3>
            <p>总控与岗位分身组成协作网络，主动发现问题、拆解任务并协调资源。</p>
          </article>
          <article>
            <strong>03</strong>
            <h3>落地执行</h3>
            <p>在权限和规则约束下调用企业系统，让 AI 从给出建议走向完成工作。</p>
          </article>
        </div>
      </section>

      <section id="solutions" class="bridge-section">
        <div class="bridge-heading">
          <div>
            <div class="section-eyebrow">ENTERPRISE INTELLIGENCE BRIDGE</div>
            <h2>让企业 SaaS、数据与 GuDuu OS<br />真正连接起来</h2>
          </div>
          <p>
            企业智能衔接层将分散在数据库、数据仓库、SaaS 和业务系统中的信息，
            转换为 AI 能理解、能查询、能调用的可信业务能力。
          </p>
        </div>

        <div class="bridge-stage">
          <div class="bridge-sources">
            <div class="source-card"><i>CRM</i><span>客户与销售</span></div>
            <div class="source-card"><i>ERP</i><span>经营与供应链</span></div>
            <div class="source-card"><i>DB</i><span>数据库 / 数仓</span></div>
            <div class="source-card"><i>OA</i><span>流程与组织</span></div>
          </div>

          <div class="bridge-lines" aria-hidden="true">
            <span></span><span></span><span></span><span></span>
          </div>

          <div class="bridge-core">
            <div class="core-kicker">GUDUU DATA INTELLIGENCE</div>
            <h3>企业智能衔接层</h3>
            <p>统一语义 · 可信指标 · 自然语言分析 · 安全 API</p>
            <div class="core-query">
              <span>✦</span>
              <b>分析本季度客户增长放缓的原因</b>
            </div>
            <div class="core-steps">
              <span class="active">理解业务语义</span>
              <span class="active">生成可信查询</span>
              <span>交付 Agent 执行</span>
            </div>
            <RouterLink class="bridge-demo-link" :to="{ name: 'data-canvas' }">
              打开数据智能画布
              <span>↗</span>
            </RouterLink>
          </div>

          <div class="bridge-lines bridge-lines-right" aria-hidden="true">
            <span></span><span></span><span></span>
          </div>

          <div class="bridge-outputs">
            <div class="output-card main-output">
              <img src="/gudu-logo.svg" alt="" />
              <span><b>GuDuu OS</b><small>智能协作与执行中枢</small></span>
            </div>
            <div class="output-card"><i>分</i><span><b>岗位分身</b><small>获取实时业务上下文</small></span></div>
            <div class="output-card"><i>API</i><span><b>企业应用</b><small>复用统一智能能力</small></span></div>
          </div>
        </div>

        <div class="bridge-values">
          <div><strong>01</strong><span><b>自然语言问数</b><small>员工无需理解表结构，也能获得有业务口径的答案。</small></span></div>
          <div><strong>02</strong><span><b>统一语义模型</b><small>把技术字段转换为企业共识，避免同一指标多种解释。</small></span></div>
          <div><strong>03</strong><span><b>可信数据服务</b><small>权限、血缘与查询过程可追踪，让 Agent 安全使用数据。</small></span></div>
          <div><strong>04</strong><span><b>开放能力接口</b><small>既服务 GuDuu OS，也可嵌入现有 SaaS 与企业应用。</small></span></div>
        </div>
      </section>

      <section id="capabilities" class="capabilities-section">
        <div class="section-heading">
          <div>
            <div class="section-eyebrow">ONE SYSTEM, EVERY TEAM</div>
            <h2>把智能，放进工作的每一环</h2>
          </div>
          <p>GuDuu OS 不是替换已有系统，而是让系统之间产生理解、协作与行动。</p>
        </div>

        <div class="capability-grid">
          <article class="capability-card card-wide">
            <div class="capability-copy">
              <span>智能工作空间</span>
              <h3>人与 Agent，在同一个频道工作</h3>
              <p>信息、决策与行动自然汇聚，重要上下文不再散落。</p>
            </div>
            <div class="channel-visual">
              <div class="channel-message muted"><b>林经理</b><span>请分析本月经营风险并推动责任部门处理。</span></div>
              <div class="channel-message ai"><b>✦ GuDuu</b><span>正在读取经营数据，并召集销售、财务与运营分身...</span></div>
              <div class="agent-row">
                <i>销</i><i>财</i><i>运</i>
                <small>3 个分身正在协作</small>
              </div>
            </div>
          </article>

          <article class="capability-card card-dark">
            <div class="capability-copy">
              <span>Agent 网络</span>
              <h3>每个角色，都有一个数字搭档</h3>
            </div>
            <div class="agent-network">
              <div class="network-core">G</div>
              <span class="network-node n1">销</span>
              <span class="network-node n2">数</span>
              <span class="network-node n3">运</span>
              <span class="network-node n4">质</span>
            </div>
          </article>

          <article class="capability-card card-accent">
            <div class="capability-copy">
              <span>企业知识</span>
              <h3>让经验随时可用，让知识持续生长</h3>
            </div>
            <div class="knowledge-stack">
              <div><i>↗</i><span>SOP 与制度</span><b>860</b></div>
              <div><i>⌁</i><span>业务知识图谱</span><b>12.4k</b></div>
              <div><i>✦</i><span>实时决策记忆</span><b>LIVE</b></div>
            </div>
          </article>
        </div>
      </section>

      <section id="advantages" class="advantages-section">
        <div class="section-heading advantages-heading">
          <div>
            <div class="section-eyebrow">WHY GUDUU OS</div>
            <h2>为真实企业，而不是演示场景设计</h2>
          </div>
          <p>从组织关系到执行权限，GuDuu OS 关注 AI 如何安全、持续地进入企业日常工作。</p>
        </div>

        <div class="advantages-grid">
          <article>
            <span>01</span>
            <div class="advantage-icon">◎</div>
            <h3>组织级上下文</h3>
            <p>理解部门、岗位、项目、客户与业务目标，让每次响应都基于企业真实语境。</p>
          </article>
          <article>
            <span>02</span>
            <div class="advantage-icon">✦</div>
            <h3>多分身协同</h3>
            <p>总控分身负责规划与协调，岗位分身携带专业知识共同完成复杂任务。</p>
          </article>
          <article>
            <span>03</span>
            <div class="advantage-icon">↗</div>
            <h3>主动推进工作</h3>
            <p>持续监测事件、识别风险、召集责任人，并跟进任务直至形成结果。</p>
          </article>
          <article>
            <span>04</span>
            <div class="advantage-icon">◇</div>
            <h3>人机共同治理</h3>
            <p>重要节点由人审批，执行过程可回溯，让效率提升不以失去控制为代价。</p>
          </article>
          <article>
            <span>05</span>
            <div class="advantage-icon">⌘</div>
            <h3>开放连接现有系统</h3>
            <p>通过连接器、API 与智能衔接层复用 ERP、CRM、OA、数据库及企业 SaaS。</p>
          </article>
          <article>
            <span>06</span>
            <div class="advantage-icon">▣</div>
            <h3>企业级安全边界</h3>
            <p>支持细粒度权限、规则约束、操作审计与灵活部署，保护企业数据资产。</p>
          </article>
        </div>
      </section>

      <section id="case" class="case-section">
        <div class="case-library-heading">
          <div>
            <div class="section-eyebrow light">GUDUU SOLUTIONS & CASES</div>
            <h2>一套企业智能底座，<br />适配不同业务场景。</h2>
          </div>
          <p>以 GuDuu OS 为统一底座，围绕不同组织、行业与流程快速构建智能分身协作方案。</p>
        </div>

        <div class="case-library">
          <RouterLink class="case-tile data-case" :to="{ name: 'data-canvas' }">
            <div class="case-tile-top">
              <span>产品案例 01</span>
              <i>可体验 ↗</i>
            </div>
            <div class="data-case-visual">
              <span class="data-mini-node dn1">CRM</span>
              <span class="data-mini-node dn2">订单</span>
              <span class="data-mini-node dn3">客户</span>
              <span class="data-mini-node dn4">收入指标</span>
              <span class="data-mini-node dn5">GuDuu Agent</span>
              <svg viewBox="0 0 320 190" aria-hidden="true">
                <path d="M55 52 C100 52 92 90 136 90" />
                <path d="M55 136 C100 136 92 104 136 104" />
                <path d="M174 96 C210 96 210 57 249 57" />
                <path d="M174 96 C210 96 210 137 249 137" />
              </svg>
            </div>
            <div class="case-tile-copy">
              <small>企业数据智能衔接层</small>
              <h3>从数据模型到 Agent 服务的<br />可视化语义画布</h3>
              <p>连接企业数据源、定义统一指标，并将可信数据能力发布给 GuDuu OS。</p>
            </div>
          </RouterLink>

          <RouterLink class="case-tile featured-case" :to="{ name: 'dashboard' }">
            <div class="case-tile-top">
              <span>行业案例 01</span>
              <i>可体验 ↗</i>
            </div>
            <div class="case-tile-visual">
              <div class="industry-ring ring-one"></div>
              <div class="industry-ring ring-two"></div>
              <div class="industry-core"><img src="/gudu-logo.svg" alt="" /></div>
              <span class="industry-point ip1">生产</span>
              <span class="industry-point ip2">供应</span>
              <span class="industry-point ip3">质检</span>
              <span class="industry-point ip4">销售</span>
            </div>
            <div class="case-tile-copy">
              <small>海洋渔业全产业链</small>
              <h3>跨生产、供应、质检与销售的<br />全链路智能协作</h3>
              <p>查看 GuDuu OS 如何将多个业务角色与智能分身组织在同一工作空间。</p>
            </div>
          </RouterLink>

          <article class="case-tile future-case">
            <div class="case-tile-top"><span>企业方案</span><i>PLANNED</i></div>
            <div class="future-case-icon">制</div>
            <div class="case-tile-copy">
              <small>智能制造</small>
              <h3>生产运营与设备协同</h3>
              <p>连接计划、设备、质量与供应链，主动协调生产异常。</p>
            </div>
          </article>

          <article class="case-tile future-case">
            <div class="case-tile-top"><span>企业方案</span><i>PLANNED</i></div>
            <div class="future-case-icon">服</div>
            <div class="case-tile-copy">
              <small>现代服务业</small>
              <h3>客户经营与交付协同</h3>
              <p>让销售、服务、项目与财务围绕客户目标持续推进。</p>
            </div>
          </article>
        </div>
      </section>

      <section id="about" class="closing-section">
        <div class="closing-orb"></div>
        <img src="/gudu-logo.svg" alt="" />
        <div class="section-eyebrow">THE NEXT WAY OF WORKING</div>
        <h2>让 AI 不止回答问题，<br />开始与你一起完成工作。</h2>
        <RouterLink class="primary-button light-button" :to="{ name: 'dashboard' }">
          立即体验 GuDuu OS
          <span class="button-arrow">→</span>
        </RouterLink>
      </section>
    </main>

    <footer class="site-footer">
      <a class="site-brand footer-brand" href="#top" @click.prevent="scrollToSection('top')">
        <img src="/gudu-logo.svg" alt="" />
        <span>GuDuu OS</span>
      </a>
      <p>AI-native operating system for modern organizations.</p>
      <span>© {{ new Date().getFullYear() }} GuDuu</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { appUrl } from '@/config/app'

// 主站地址：运行时按当前主域推导，不写死域名（见 config/app.ts）
const appHref = appUrl()

const scrolled = ref(false)
const siteShell = ref<HTMLElement | null>(null)
const typedCommand = ref('')
const commands = [
  '分析本月经营风险并推动责任部门处理',
  '总结本周经营风险并生成行动计划',
  '读取客户与项目数据，生成管理层简报'
]
let commandIndex = 0
let charIndex = 0
let deleting = false
let typingTimer: number | undefined

function updateScroll() {
  scrolled.value = (siteShell.value?.scrollTop ?? 0) > 24
}

function scrollToSection(id: string) {
  const shell = siteShell.value
  const target = document.getElementById(id)
  if (!shell || !target) return

  const shellTop = shell.getBoundingClientRect().top
  const targetTop = target.getBoundingClientRect().top
  const navOffset = id === 'top' ? 0 : 65
  shell.scrollTo({
    top: shell.scrollTop + targetTop - shellTop - navOffset,
    behavior: 'smooth'
  })
}

function typeCommand() {
  const command = commands[commandIndex]
  if (!deleting) {
    charIndex += 1
    typedCommand.value = command.slice(0, charIndex)
    if (charIndex === command.length) {
      deleting = true
      typingTimer = window.setTimeout(typeCommand, 1800)
      return
    }
  } else {
    charIndex -= 1
    typedCommand.value = command.slice(0, charIndex)
    if (charIndex === 0) {
      deleting = false
      commandIndex = (commandIndex + 1) % commands.length
    }
  }
  typingTimer = window.setTimeout(typeCommand, deleting ? 38 : 78)
}

onMounted(() => {
  document.title = 'GuDuu OS · 企业级 AI 协作操作系统'
  updateScroll()
  typingTimer = window.setTimeout(typeCommand, 900)
})

onBeforeUnmount(() => {
  document.title = 'GuDuu 工作台 · 蓝湾渔业'
  if (typingTimer) window.clearTimeout(typingTimer)
})
</script>
